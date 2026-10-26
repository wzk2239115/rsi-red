"""End-to-end CPU campaign: real child processes, artifact lineage and actual toy inference."""
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import time

from .service import ResearchService
from .simulation import SimulationEvaluator, export_model
from .schedulers.local import LocalScheduler
from .starters import create


def run(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    state = root / "state"
    service = ResearchService(root=state, scheduler=LocalScheduler(root=root / "workers", allow_cpu_only=True),
        evaluator=SimulationEvaluator(root=state), principals={"demo": {"id": "operator", "role": "operator"}})
    def call(operation, **payload):
        result = service.dispatch(token="demo", operation=operation, payload=payload)
        if result["error"]:
            raise RuntimeError(result["error"])
        return result["data"]
    rows = [{"x": [-2.0], "label": 0}, {"x": [-1.0], "label": 0},
            {"x": [1.0], "label": 1}, {"x": [2.0], "label": 1}]
    jobs, evaluations, models, states = [], [], {}, {}
    try:
        authorization = call('direction.authorize', tasks={'binary-policy': {'direction': 'maximize'}},
            source_protocol_digest=None, goal='Demo operator explicitly maximizes binary fixture accuracy')
        protocol = call("protocol.register", name="cpu-linear-development", visibility="development",
                        direction='maximize', direction_authorization_id=authorization['id'],
                        items=[{"id": f"q{i}", "task": "binary-policy", "prompt": json.dumps({"x": row["x"]}),
                                "answer": str(row["label"])} for i, row in enumerate(rows)],
                        evaluator_digest="sha256:" + hashlib.sha256(b"cpu-linear-v1").hexdigest(),
                        sampling={"temperature": 0, "max_tokens": 1}, aggregation="task_mean", eval_seed=42)
        campaign = call("campaign.create", name="cpu-simulation", members=["operator"],
                        gpu_hours_budget=1, protocol_id=protocol["id"], require_decontamination=False)["id"]
        data = root / "rows.jsonl"
        data.write_text("".join(json.dumps(row) + "\n" for row in rows))
        dataset = call("data.import", campaign_id=campaign, path=str(data), source="generated-cpu-fixture",
                       revision="binary-v1", license="CC0-1.0")["id"]
        def register(name, model, parents, provenance):
            path = root / "models" / name
            manifest = export_model(model, path)
            result = call("artifact.register", campaign_id=campaign, path=str(path), files=manifest,
                          parents=parents, kind="model", provenance=provenance)
            return result["id"]
        def evaluate(model):
            pending = call("eval.submit", campaign_id=campaign, model_id=model, protocol_id=protocol["id"])
            service.reconcile()
            result = call("eval.show", id=pending["id"])
            if result["state"] != "succeeded":
                raise RuntimeError(result)
            evaluations.append(result)
            return result
        states["base"] = {"format": "simulation-linear-v1", "weights": [0.0], "simulation": True}
        models["base"] = register("base", states["base"], [], {"simulation": True, "source": "zero-init"})
        base = evaluate(models["base"])
        for method, parent_names in [("sft", ["base"]), ("grpo", ["sft"]), ("env_rl", ["base"]),
                                     ("self_distill", ["sft", "grpo"]), ("merge", ["self_distill", "env_rl"])]:
            folder = create(method, root / "recipes" / method)
            output = root / "trained" / method
            recipe = json.loads((folder / "recipe.json").read_text())
            recipe.update(rows=rows, weights=states[parent_names[0]]["weights"], output=str(output),
                          parents=[states[name]["weights"] for name in parent_names],
                          coefficients=[.5, .5], teacher_weights=states["grpo"]["weights"] if "grpo" in states else [2.0])
            (folder / "recipe.json").write_text(json.dumps(recipe))
            archive = root / (method + ".tar")
            with tarfile.open(archive, "w") as package:
                for name in ["train.py", "recipe.json"]:
                    package.add(folder / name, arcname=name)
            pending = call("job.submit", campaign_id=campaign, idempotency_key=method,
                           entrypoint=[sys.executable, "train.py", "--config", "recipe.json"],
                           code={"uri": archive.as_uri(), "digest": "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()},
                           datasets=[dataset], parents=[models[name] for name in parent_names],
                           resources={"gpus": 0, "walltime_seconds": 30}, training_seed=42)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                service.reconcile()
                job = call("job.show", id=pending["id"])
                if job["state"] in {"succeeded", "failed", "timed_out"}:
                    break
                time.sleep(.05)
            if job["state"] != "succeeded":
                raise RuntimeError(job)
            jobs.append(job)
            states[method] = json.loads((output / "model.bin").read_text())
            # Worker creates the files. Register the exact completed output, not a rerun of training.
            manifest = [{"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                        for path in sorted(output.iterdir())]
            models[method] = call("artifact.register", campaign_id=campaign, path=str(output), files=manifest,
                                 parents=[models[name] for name in parent_names], kind="model",
                                 provenance={"simulation": True, "job_id": job["id"],
                                             "teacher_model_id": models.get("grpo") if method == "self_distill" else None})["id"]
            evaluate(models[method])
        call("campaign.submit", id=campaign, model_id=models["merge"])
        report = {"simulation": True, "methods": list(models)[1:], "jobs": jobs, "evaluations": evaluations,
                  "base_score": base["score"], "final_score": evaluations[-1]["score"],
                  "lineage": call("artifact.lineage", id=models["merge"]),
                  "campaign_id": campaign, "note": "Toy CPU policy scores; not LLM or GPU measurements"}
        (root / "report.json").write_text(json.dumps(report, indent=2))
        return report
    finally:
        service.close()
