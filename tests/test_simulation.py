import importlib
from pathlib import Path
import json
import subprocess
import sys

import pytest


@pytest.mark.parametrize("method", ["sft", "grpo", "env_rl", "self_distill"])
def test_cpu_recipes_really_change_parameters(method):
    module = importlib.import_module("rsi_red.simulation")
    rows = [{"x": [-1.0], "label": 0}, {"x": [1.0], "label": 1}]
    model = module.run_recipe({"method": method, "weights": [0.0], "teacher_weights": [2.0],
                               "rows": rows, "steps": 120, "learning_rate": .2, "seed": 42})
    assert model["format"] == "simulation-linear-v1"
    assert model["weights"][0] > 0.2
    assert model["simulation"] is True
    assert module.loss(model["weights"], rows) < module.loss([0.0], rows)


def test_weight_merge_preserves_both_parents():
    module = importlib.import_module("rsi_red.simulation")
    model = module.run_recipe({"method": "merge", "parents": [[1.0, 3.0], [3.0, 1.0]],
                               "coefficients": [.25, .75]})
    assert model["weights"] == [2.5, 1.5]
    assert model["simulation"] is True


def test_cpu_recipe_does_not_silently_accept_unknown_algorithm():
    module = importlib.import_module("rsi_red.simulation")
    with pytest.raises(ValueError, match="unsupported"):
        module.run_recipe({"method": "fake-autonomous-superintelligence"})


def test_simulation_exports_complete_loadable_model(tmp_path):
    module = importlib.import_module("rsi_red.simulation")
    model = {"format": "simulation-linear-v1", "weights": [1.0], "simulation": True}
    manifest = module.export_model(model, tmp_path / "model")
    assert {x["path"] for x in manifest} == {"config.json", "tokenizer.json", "model.bin"}
    assert json.loads((tmp_path / "model" / "model.bin").read_text())["weights"] == [1.0]


@pytest.mark.parametrize("method", ["sft", "grpo", "env_rl", "self_distill", "merge"])
def test_exported_starter_runs_as_editable_cpu_program(tmp_path, method):
    module = importlib.import_module("rsi_red.starters")
    output = module.create(method, tmp_path / method)
    config = json.loads((output / "recipe.json").read_text())
    config["output"] = str(tmp_path / "model")
    (output / "recipe.json").write_text(json.dumps(config))
    script = output / "train.py"
    env = dict(__import__('os').environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    result = subprocess.run([sys.executable, str(script), "--config", str(output / "recipe.json")],
                             capture_output=True, text=True, timeout=10, env=env)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "model" / "model.bin").is_file()


def test_demo_runs_real_cpu_jobs_and_writes_comparable_evidence(tmp_path):
    module = importlib.import_module("rsi_red.demo")
    report = module.run(tmp_path)
    assert report["simulation"] is True
    assert set(report["methods"]) == {"sft", "grpo", "env_rl", "self_distill", "merge"}
    assert all(job["state"] == "succeeded" for job in report["jobs"])
    assert report["base_score"] < report["final_score"]
    assert len(report["lineage"]["nodes"]) >= 6
    assert len(report["evaluations"]) >= 6
