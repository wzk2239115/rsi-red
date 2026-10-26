"""Loopback development HTTP service; put authenticated TLS transport in front for remote use."""
import argparse
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import signal
import threading

from .errors import ResearchError, envelope
from .evaluation import UnconfiguredEvaluator
from .schedulers import create_scheduler
from .schedulers.local import write_json
from .service import ResearchService


def serve(config, ready_file):
    root = Path(config["root"]).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (root / "controller.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    backend = dict(config["scheduler"])
    if backend["backend"] == "local":
        backend["root"] = str(root / "local-jobs")
    scheduler = create_scheduler(backend)
    evaluator = UnconfiguredEvaluator()
    if config.get("evaluator", {}).get("backend") == "simulation":
        from .simulation import SimulationEvaluator
        evaluator = SimulationEvaluator(root=root)
    service = ResearchService(root=root, scheduler=scheduler, evaluator=evaluator,
                              principals=config["principals"])
    host, port = config.get("listen", "127.0.0.1:0").rsplit(":", 1)
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Development server binds loopback only; use a TLS/authenticated proxy or SSH tunnel")
    stop = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            return  # never log bearer credentials or request payloads

        def do_GET(self):
            if self.path == "/health":
                self.reply(200, {"status": "ok", "version": "0.1.0"})
            else:
                self.reply(404, envelope(error=ResearchError("NOT_FOUND", "Endpoint not found")))

        def do_POST(self):
            if self.path != "/v1/request":
                self.reply(404, envelope(error=ResearchError("NOT_FOUND", "Endpoint not found")))
                return
            self.connection.settimeout(10)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4 * 1024 * 1024:
                    raise ValueError("Invalid size")
                body = json.loads(self.rfile.read(length))
                token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                # v1 file operations use service-visible paths. This is NOT a multi-tenant sandbox.
                result = service.dispatch(token=token, operation=body["operation"], payload=body.get("payload", {}))
                self.reply(200, result)
            except (ValueError, KeyError, TypeError):
                self.reply(400, envelope(error=ResearchError("INVALID_REQUEST", "Invalid request body")))

        def reply(self, code, body):
            content = json.dumps(body, allow_nan=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass

    http = ThreadingHTTPServer((host, int(port)), Handler)
    http.daemon_threads = True

    def reconcile(function):
        while not stop.is_set():
            try:
                function()
            except Exception as error:
                logging.error("reconcile failed: %s", type(error).__name__)
            stop.wait(.1)

    threads = [threading.Thread(target=reconcile, args=(function,), daemon=True)
               for function in [service.reconcile_jobs, service.reconcile_evaluations]]
    for thread in threads:
        thread.start()
    endpoint = f"http://127.0.0.1:{http.server_port}"
    write_json(Path(ready_file), {"endpoint": endpoint})

    def shutdown(*_):
        stop.set()
        threading.Thread(target=http.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        http.serve_forever(poll_interval=.1)
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=10)
        http.server_close()
        service.close()
        lock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--ready-file", required=True)
    args = parser.parse_args()
    with Path(args.config).open() as stream:
        config = json.load(stream)
    serve(config, args.ready_file)


if __name__ == "__main__":
    main()
