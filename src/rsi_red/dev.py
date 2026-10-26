"""Create a private, loopback-only CPU development environment."""
import json
from pathlib import Path
import secrets


def initialize(output):
    output = Path(output).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    token = secrets.token_urlsafe(32)
    token_file, config_file = output / "token", output / "service.json"
    config = {"root": str(output / "state"), "listen": "127.0.0.1:8787",
              "scheduler": {"backend": "local", "allow_cpu_only": True},
              "evaluator": {"backend": "simulation"},
              "principals": {token: {"id": "local-operator", "role": "operator"}}}
    for path, text in [(token_file, token + "\n"), (config_file, json.dumps(config, indent=2) + "\n")]:
        with path.open("x") as stream:
            path.chmod(0o600)
            stream.write(text)
    return {"config": config_file, "token_file": token_file, "ready_file": output / "ready.json"}
