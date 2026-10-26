"""Read-only dashboard boundary and HTTP tests."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from rsi_red.kanban import make_server, snapshot


def test_live_snapshot_uses_only_scoped_reads_and_never_invents_bridges():
    calls = []
    def request(operation, payload):
        calls.append((operation, payload))
        return {"items": [{"id": "c1", "name": "research"}]} if operation == "campaign.list" else {"items": []}
    result = snapshot(request)
    assert result["demo"] is False
    assert result["bridges"] == []
    assert result["islands"][0]["id"] == "c1"
    assert {op for op, _ in calls} == {"campaign.list", "job.list", "events.list", "recipe.list", "resource.show", "audit.list", "audit.feedback"}


def test_authorization_failure_does_not_become_demo():
    def request(*_):
        raise RuntimeError("FORBIDDEN")
    with pytest.raises(RuntimeError):
        snapshot(request)


def test_demo_http_is_readonly_and_rejects_foreign_host():
    server = make_server(port=0, demo=True, endpoint="http://127.0.0.1:1", token="secret-never-in-browser")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(url + "/api/snapshot") as response:
            body = response.read()
            assert json.loads(body)["demo"] is True
            assert b"secret-never-in-browser" not in body
        with urllib.request.urlopen(url) as response:
            assert b"secret-never-in-browser" not in response.read()
        for request in [urllib.request.Request(url, headers={"Host": "evil.example"}),
                        urllib.request.Request(url + "/api/snapshot", data=b"{}")]:
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            assert error.value.code in {403, 405}
            error.value.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_real_service_permissions_are_preserved(tmp_path):
    from tests.support import ALICE, OUTSIDER, Rig
    rig = Rig(tmp_path).setup()
    def request(op, p, token):
        result = rig.call(op, p, token=token)
        if result["error"]:
            raise RuntimeError(result["error"]["code"])
        return result["data"]
    try:
        result = snapshot(lambda op, p: request(op, p, ALICE))
        assert [i["id"] for i in result["islands"]] == [rig.campaign]
        assert result["islands"][0]["events"]
        outsider = snapshot(lambda op, p: request(op, p, OUTSIDER))
        assert outsider["islands"] == []
    finally:
        rig.close()


def test_cli_demo_launches_without_credentials_and_stops_cleanly(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
               RSI_TOKEN_FILE=str(tmp_path / "nonexistent-token"))
    process = subprocess.Popen([sys.executable, "-m", "rsi_red", "kanban", "--demo", "--no-open",
                                "--port", "0"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, env=env)
    try:
        # A separate bounded waiter keeps startup regressions from hanging CI.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            line = pool.submit(process.stdout.readline)
            try:
                ready = json.loads(line.result(timeout=10))
            except BaseException:
                process.kill()
                raise
        with urllib.request.urlopen(ready["url"] + "/api/snapshot", timeout=3) as response:
            assert json.load(response)["demo"] is True
        assert process.poll() is None
    finally:
        process.terminate()
        process.communicate(timeout=5)


def test_unreachable_service_returns_error_without_demo_or_token():
    server = make_server(port=0, demo=False, endpoint="http://127.0.0.1:1", token="private-token", timeout=.1)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/api/snapshot")
        assert error.value.code == 503
        body = error.value.read()
        error.value.close()
        assert b"private-token" not in body
        assert b'"demo": true' not in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
