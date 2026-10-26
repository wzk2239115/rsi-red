import importlib
import subprocess
import sys

from tests.support import BOB, Rig


def test_transcript_chunks_are_durable_team_readable_and_owner_written(tmp_path):
    r = Rig(tmp_path).setup()
    payload = {"campaign_id": r.campaign, "session_id": "alice-session-1", "sequence": 0,
               "text": "Observed output truncation; next inspect item q2."}
    first = r.ok("transcript.append", payload)
    assert r.ok("transcript.append", payload)["id"] == first["id"]
    r.error("transcript.append", dict(payload, text="replace history"), "IDEMPOTENCY_CONFLICT")
    r.error("transcript.append", dict(payload, sequence=1, text="forged"), "FORBIDDEN", token=BOB)
    r.close()
    r.open()
    result = r.ok("transcript.show", {"campaign_id": r.campaign, "session_id": "alice-session-1"}, token=BOB)
    assert result["chunks"][0]["text"] == payload["text"]
    assert result["author"] == "alice"


def test_watcher_resumes_cursor_and_runs_notification_command(tmp_path):
    module = importlib.import_module("rsi_red.watch")
    r = Rig(tmp_path).setup()
    cursor = r.events()[-1]["id"]
    path = tmp_path / "cursor.json"
    module.save_cursor(path, cursor)
    log = tmp_path / "notifications.jsonl"
    script = r.file("notify.py", "import sys\nfrom pathlib import Path\n"
                    f"with Path({str(log)!r}).open('a') as out: out.write(sys.stdin.read().strip()+'\\n')\n")
    job = r.submit()
    r.reconcile()
    r.cluster.set_state(r.job(job["id"])["scheduler_id"], "succeeded")
    r.reconcile()
    command = [sys.executable, str(script)]
    def fetch(after):
        return r.events(after)
    count = module.drain(fetch=fetch, cursor_file=path, command=command)
    assert count >= 1
    content = log.read_text()
    assert "job.succeeded" in content
    assert job["id"] in content
    assert module.drain(fetch=fetch, cursor_file=path, command=command) == 0


def test_failed_notification_keeps_cursor_for_retry(tmp_path):
    module = importlib.import_module("rsi_red.watch")
    path = tmp_path / "cursor.json"
    module.save_cursor(path, "5")
    import pytest
    with pytest.raises(subprocess.CalledProcessError):
        module.drain(fetch=lambda _: [{"id": "6", "type": "job.succeeded"}], cursor_file=path,
                     command=[sys.executable, "-c", "raise SystemExit(2)"])
    assert module.load_cursor(path) == "5"
