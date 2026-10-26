"""Machine-readable CLI; each command delegates to one authenticated service operation."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

from . import __version__
from .errors import ResearchError, envelope


class Parser(argparse.ArgumentParser):
    def error(self, message):
        code = "INVALID_COMMAND" if "invalid choice" in message else "INVALID_ARGUMENT"
        raise ResearchError(code, message)


def document(path):
    content = Path(path).read_text()
    if path.endswith((".yaml", ".yml")):
        import yaml
        return yaml.safe_load(content)
    return json.loads(content)


def parser():
    root = Parser(prog="rsi", description="Agent-native post-training: job eval data artifact campaign events")
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--endpoint", default=os.environ.get("RSI_ENDPOINT", "http://127.0.0.1:8787"))
    root.add_argument("--timeout", type=float, default=10)
    root.add_argument("--token-file", default=os.environ.get("RSI_TOKEN_FILE"))
    subs = root.add_subparsers(dest="group", required=True)
    kanban = subs.add_parser("kanban", help="Open the archipelago research dashboard")
    kanban.add_argument("--port", type=int, default=8790)
    kanban.add_argument("--no-open", action="store_true")
    kanban.add_argument("--demo", action="store_true")
    request = subs.add_parser("request")
    request.add_argument("operation")
    request.add_argument("--payload", default="{}")
    subs.add_parser("doctor")
    init = subs.add_parser("init")
    init.add_argument("--output", required=True)
    init.add_argument("--profile", choices=["local", "ray-peers"], default="local")
    init.add_argument("--with-auditor", action="store_true")
    init.add_argument("--ray-address", default="http://127.0.0.1:8265")
    init.add_argument("--python-executable")
    init.add_argument("--cluster-image")
    init.add_argument("--ray-auth-mode", choices=["auto", "token", "disabled"], default="auto")
    init.add_argument("--ray-token-file")
    starter = subs.add_parser("starter")
    starter.add_argument("action", choices=["create"])
    starter.add_argument("--method", required=True, choices=["sft", "grpo", "env_rl", "self_distill", "merge"])
    starter.add_argument("--output", required=True)
    demo = subs.add_parser("demo")
    demo.add_argument("--output", required=True)
    watch = subs.add_parser("watch")
    watch.add_argument("--campaign", required=True)
    watch.add_argument("--cursor-file", required=True)
    watch.add_argument("--command", required=True, help="JSON argv; event is passed on stdin")
    watch.add_argument("--once", action="store_true")
    watch.add_argument("--poll", type=float, default=1)
    events = subs.add_parser("events")
    events.add_argument("--campaign", required=True)
    events.add_argument("--after")
    events.add_argument("--wait", type=float, default=0)
    events.add_argument("--limit", type=int, default=100)
    mappings = {
        "paper": {"policy_register": "spec", "policy_show": "id", "ingest": "spec", "show": "id", "list": "none",
                  "document": "id", "batch_submit": "spec", "batch_show": "id", "batch_retry": "id",
                  "batch_list": "none", "extract": "spec", "recheck": "id",
                  "relationship_evidence": "spec", "review_relationship": "spec"},
        "knowledge": {"create": "spec", "show": "id", "list": "none", "merge": "spec", "revise": "spec",
                      "pack": "spec", "bridge_register": "spec", "bridges": "none"},
        "runner": {"register": "spec", "show": "id", "list": "none"},
        "direction": {"authorize": "spec"},
        "audit": {"configure": "spec", "submit": "spec", "observe": "spec", "show": "id",
                  "list": "campaign", "feedback": "campaign", "ack": "id"},
        "recipe": {"create": "spec", "update": "spec", "show": "id", "list": "campaign"},
        "resource": {"show": "none"},
        "campaign": {"create": "config", "show": "id", "list": "none", "submit": "id", "select": "id"},
        "job": {"validate": "spec", "outputs": "id", "submit": "spec", "show": "id", "list": "campaign", "cancel": "id", "logs": "id"},
        "data": {"import": "spec", "inspect": "id", "sample": "id", "check": "id", "decontaminate": "id"},
        "artifact": {"register": "manifest", "show": "id", "fetch": "id", "lineage": "id"},
        "eval": {"model": "id", "submit": "runner_submit", "config": "id", "cancel": "id", "logs": "id", "show": "id", "list": "campaign", "samples": "id", "compare": "pair", "aggregate": "spec"},
        "protocol": {"register": "spec", "derive": "spec", "show": "id", "list": "none"},
        "note": {"add": "spec", "show": "id"},
        "transcript": {"append": "spec", "show": "spec"},
    }
    for group, operations in mappings.items():
        children = subs.add_parser(group).add_subparsers(dest="verb", required=True)
        for verb, mode in operations.items():
            child = children.add_parser(verb)
            if mode in {"config", "spec", "manifest"}:
                child.add_argument("--" + mode, required=True)
            if mode == "runner_submit":
                child.add_argument("--spec")
                child.add_argument("--runner")
                child.add_argument("--model")
                child.add_argument("--protocol")
                child.add_argument("--idempotency-key")
            if (group, verb) in {("campaign", "select"), ("campaign", "submit")}:
                child.add_argument("--runner")
                child.add_argument("--comparison-digest")
            if (group, verb) == ("runner", "list"):
                child.add_argument("--protocol")
            if mode == "id":
                child.add_argument("id")
            if mode == "pair":
                child.add_argument("left")
                child.add_argument("right")
            child.add_argument("--campaign", required=mode == "campaign")
            if (group, verb) == ("audit", "feedback"):
                child.add_argument("--after")
                child.add_argument("--limit", type=int, default=100)
            if (group, verb) == ("job", "submit"):
                child.add_argument("--idempotency-key")
            if (group, verb) == ("campaign", "submit"):
                child.add_argument("--model", required=True)
            if (group, verb) == ("artifact", "fetch"):
                child.add_argument("--output", required=True)
            if (group, verb) == ("data", "sample"):
                child.add_argument("--count", type=int, default=10)
                child.add_argument("--seed", type=int, default=42)
            if (group, verb) == ("data", "check"):
                child.add_argument("--profile", default="sft")
            if (group, verb) in {("eval", "samples"), ("eval", "logs"), ("job", "logs")}:
                child.add_argument("--limit", type=int, default=100)
                child.add_argument("--offset", type=int, default=0)
                if group == "eval":
                    child.add_argument("--filter")
    return root


def call(endpoint, token, operation, payload, timeout):
    request = urllib.request.Request(endpoint.rstrip("/") + "/v1/request",
        data=json.dumps({"operation": operation, "payload": payload}, allow_nan=False).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ResearchError("SERVICE_UNAVAILABLE", "Control service unavailable", retryable=True) from None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    json_mode = "--json" in argv
    argv = [arg for arg in argv if arg != "--json"]
    try:
        args = vars(parser().parse_args(argv))
        endpoint, timeout = args.pop("endpoint"), args.pop("timeout")
        if not 0 < timeout <= 3600:
            raise ResearchError("INVALID_ARGUMENT", "Timeout must be in (0,3600]")
        token_file = args.pop("token_file")
        token = (Path(token_file).read_text().strip() if token_file else os.environ.get("RSI_TOKEN", "")) \
            if not (args["group"] in {"init", "starter", "demo"} or
                    (args["group"] == "kanban" and args["demo"])) else ""
        group, verb = args.pop("group"), args.pop("verb", None)
        if group == "kanban":
            from .kanban import run
            return run(port=args["port"], demo=args["demo"], no_open=args["no_open"],
                       endpoint=endpoint, token=token, timeout=timeout)
        if group == "init":
            from .dev import initialize
            result = initialize(args["output"], profile=args["profile"], with_auditor=args["with_auditor"],
                                ray_address=args["ray_address"],
                                python_executable=args["python_executable"], cluster_image=args["cluster_image"],
                                ray_auth_mode=args["ray_auth_mode"], ray_token_file=args["ray_token_file"])
            print(json.dumps(envelope({key: str(value) for key, value in result.items()})))
            return 0
        if group == "starter":
            from .starters import create
            print(json.dumps(envelope({"path": str(create(args["method"], args["output"])), "simulation": True})))
            return 0
        if group == "demo":
            from .demo import run
            report = run(args["output"])
            print(json.dumps(envelope({"report": str(Path(args["output"]).resolve() / "report.json"),
                                      "simulation": True, "base_score": report["base_score"],
                                      "final_score": report["final_score"]})))
            return 0
        if group == "watch":
            from .watch import drain
            command = json.loads(args["command"])
            if not isinstance(command, list) or not command or not all(isinstance(arg, str) for arg in command):
                raise ResearchError("INVALID_ARGUMENT", "Notification command must be a JSON argv")
            def fetch(after):
                result = call(endpoint, token, "events.list", {"campaign_id": args["campaign"],
                              "after": after, "limit": 1000}, timeout)
                if result["error"]:
                    raise ResearchError(**result["error"])
                return result["data"]["items"]
            delivered = 0
            while True:
                delivered += drain(fetch=fetch, cursor_file=args["cursor_file"], command=command)
                if args["once"]:
                    print(json.dumps(envelope({"delivered": delivered})))
                    return 0
                time.sleep(max(.1, args["poll"]))
        if group == "request":
            operation, payload = args["operation"], json.loads(args["payload"])
        elif group == "doctor":
            with urllib.request.urlopen(endpoint.rstrip("/") + "/health", timeout=timeout) as response:
                result = envelope(json.load(response))
            print(json.dumps(result, ensure_ascii=False))
            return 0
        elif group == "events":
            operation = "events.list"
            wait = args.pop("wait")
            payload = {"campaign_id": args.pop("campaign"), **args}
            deadline = time.monotonic() + max(0, min(wait, 60))
            while True:
                result = call(endpoint, token, operation, payload, timeout)
                if result["error"] or result["data"]["items"] or time.monotonic() >= deadline:
                    break
                time.sleep(min(.1, max(0, deadline - time.monotonic())))
            print(json.dumps(result, ensure_ascii=False))
            return 1 if result["error"] else 0
        else:
            operation, payload = group + "." + verb, {}
            if (group, verb) == ('eval', 'submit'):
                if args.get('spec'):
                    if any(args.get(k) for k in ('runner', 'model', 'protocol', 'campaign', 'idempotency_key')):
                        raise ResearchError('INVALID_ARGUMENT', 'Do not mix --spec with submission flags')
                elif not (args.get('runner') and args.get('model')):
                    raise ResearchError('INVALID_ARGUMENT', 'Provide --spec or --runner and --model')
            for name in ["config", "spec", "manifest"]:
                if name in args:
                    path = args.pop(name)
                    if path:
                        payload.update(document(path))
            if args.get("campaign"):
                payload["campaign_id"] = args.pop("campaign")
            else:
                args.pop("campaign", None)
            for field in ("runner", "protocol"):
                if args.get(field):
                    args[field + "_id"] = args.pop(field)
            if args.get("model"):
                args["model_id"] = args.pop("model")
            payload.update({key.replace("-", "_"): value for key, value in args.items() if value is not None})
        result = call(endpoint, token, operation, payload, timeout)
        print(json.dumps(result, ensure_ascii=False) if json_mode else json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["error"] else 0
    except ResearchError as error:
        print(json.dumps(envelope(error=error), ensure_ascii=False))
        return 2 if error.code.startswith("INVALID_") else 1
    except (OSError, ValueError, TypeError) as error:
        code = "SERVICE_UNAVAILABLE" if isinstance(error, urllib.error.URLError) else "INVALID_ARGUMENT"
        print(json.dumps(envelope(error=ResearchError(code, "Invalid arguments or inaccessible input", code == "SERVICE_UNAVAILABLE"))))
        return 2 if code == "INVALID_ARGUMENT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
