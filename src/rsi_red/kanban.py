"""Read-only, loopback dashboard proxy. Browser never receives the service token."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import webbrowser

from .cli import call


def snapshot(request):
    islands = []
    for campaign in request("campaign.list", {})["items"]:
        campaign_id = campaign["id"]
        events, after = [], None
        while True:
            page = request("events.list", {"campaign_id": campaign_id, "limit": 1000,
                                          **({"after": after} if after else {})})["items"]
            events.extend(page)
            if len(page) < 1000:
                break
            after = page[-1]["id"]
        jobs = request("job.list", {"campaign_id": campaign_id})["items"]
        # Send only presentation fields; no raw specs, paths, logs or credentials.
        islands.append({"id": campaign_id, "name": campaign["name"],
                        "jobs": [{"id": j["id"], "state": j["state"]} for j in jobs],
                        "events": [{k: e[k] for k in ("id", "time", "type", "entity_id")} for e in events]})
    return {"demo": False, "islands": islands, "bridges": [],
            "notice": "已连接控制服务 · 方法桥与研究机制评估接口待实现"}


def demo_snapshot():
    names = ["数据与课程", "学习与优化", "探索与采样", "表示与记忆"]
    islands = [{"id": f"R0{i+1}", "name": name,
                "jobs": [{"id": f"demo-{i}-{n}", "state": "succeeded" if n < 3 else "running"}
                         for n in range(4)],
                "events": [{"id": f"{i}-{n}", "time": n * 12 + i * 2,
                            "type": "job.succeeded" if n < 3 else "job.running",
                            "entity_id": f"demo-{i}-{n}"} for n in range(4)]}
               for i, name in enumerate(names)]
    return {"demo": True, "islands": islands,
            "bridges": [{"id": "BR-014", "source": "R03", "target": "R02", "time": 28,
                         "name": "混合解码 rollout", "status": "已复用 · 待消融",
                         "hypothesis": "在采样轨迹中加入一部分贪心解码轨迹，能否让训练更早遇到部署时的重复循环？",
                         "method": "GRPO rollout · 25% greedy · 保留探索采样",
                         "evidence": "演示迁移记录；本页面未运行任何实验。",
                         "boundary": "同轮数据也有调整，独立收益尚待验证。",
                         "next": "相同数据、相同预算，对照纯采样与混合解码。"}],
            "notice": "设计示意 · 非实时数据 · 不提交训练任务"}


def make_server(*, port, demo, endpoint, token, timeout=10):
    def request(operation, payload):
        result = call(endpoint, token, operation, payload, timeout)
        if result["error"]:
            raise RuntimeError(result["error"]["code"])
        return result["data"]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, content, mime="application/json; charset=utf-8"):
            body = content if isinstance(content, bytes) else json.dumps(content, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            self.reply(405, {"error": "READ_ONLY"})

        def do_GET(self):
            if self.headers.get("Host") not in {f"127.0.0.1:{self.server.server_port}",
                                                f"localhost:{self.server.server_port}"}:
                self.reply(403, {"error": "INVALID_HOST"})
                return
            if self.path == "/api/snapshot":
                try:
                    self.reply(200, demo_snapshot() if demo else snapshot(request))
                except Exception:
                    self.reply(503, {"error": "无法读取控制服务：请检查服务、连接配置与访问权限。"})
                return
            assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                      "/style.css": ("style.css", "text/css")}
            if self.path not in assets:
                self.reply(404, {"error": "NOT_FOUND"})
                return
            name, mime = assets[self.path]
            self.reply(200, (Path(__file__).parent / "web" / name).read_bytes(), mime + "; charset=utf-8")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def run(*, port, demo, endpoint, token, no_open, timeout=10):
    if not 0 <= port <= 65535:
        raise ValueError("Invalid port")
    with make_server(port=port, demo=demo, endpoint=endpoint, token=token, timeout=timeout) as server:
        url = f"http://127.0.0.1:{server.server_port}"
        print(json.dumps({"url": url, "demo": demo}, ensure_ascii=False), flush=True)
        if not no_open:
            webbrowser.open(url)
        try:
            server.serve_forever(poll_interval=.2)
        except KeyboardInterrupt:
            pass
    return 0
