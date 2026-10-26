"""At-least-once event delivery to a shell-free notification command with durable cursor."""
import json
from pathlib import Path
import subprocess

from .schedulers.local import write_json


def save_cursor(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {"after": value})


def load_cursor(path):
    path = Path(path)
    return json.loads(path.read_text())["after"] if path.exists() else None


def drain(*, fetch, cursor_file, command):
    count = 0
    for event in fetch(load_cursor(cursor_file)):
        subprocess.run(command, input=json.dumps(event), text=True, check=True, timeout=60,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, shell=False)
        save_cursor(cursor_file, event["id"])
        count += 1
    return count
