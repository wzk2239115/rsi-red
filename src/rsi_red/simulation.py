"""Small CPU research laboratory. These algorithms train a linear binary policy, NOT an LLM."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random


def probability(weights, x):
    z = max(-40, min(40, sum(w * v for w, v in zip(weights, x, strict=True))))
    return 1 / (1 + math.exp(-z))


def loss(weights, rows):
    return -sum(row["label"] * math.log(max(1e-12, probability(weights, row["x"]))) +
                (1 - row["label"]) * math.log(max(1e-12, 1 - probability(weights, row["x"])))
                for row in rows) / len(rows)


def run_recipe(config):
    method = config["method"]
    if method not in {"sft", "grpo", "env_rl", "self_distill", "merge"}:
        raise ValueError("unsupported simulation method")
    if method == "merge":
        parents, coefficients = config["parents"], config["coefficients"]
        if not parents or len(parents) != len(coefficients) or sum(coefficients) == 0:
            raise ValueError("Invalid merge coefficients")
        if len({len(parent) for parent in parents}) != 1:
            raise ValueError("Incompatible model shapes")
        weights = [sum(parent[i] * c for parent, c in zip(parents, coefficients, strict=True)) / sum(coefficients)
                   for i in range(len(parents[0]))]
        history = []
    else:
        weights = list(config["weights"])
        rows, rng = config["rows"], random.Random(config.get("seed", 42))
        rate, steps = config.get("learning_rate", .1), config.get("steps", 100)
        if not rows or not weights or steps <= 0 or rate <= 0:
            raise ValueError("Invalid training recipe")
        history = [{"step": 0, "loss": loss(weights, rows)}]
        for step in range(steps):
            row = rows[step % len(rows)]
            x, label = row["x"], row["label"]
            p = probability(weights, x)
            if method == "sft":
                direction = label - p
            elif method == "self_distill":
                # Reverse-KL distillation on actions sampled from the student's current policy.
                teacher = probability(config["teacher_weights"], x)
                actions = [int(rng.random() < p) for _ in range(config.get("group_size", 8))]
                direction = sum((math.log((teacher if action else 1 - teacher) /
                                          (p if action else 1 - p))) * (action - p)
                                for action in actions) / len(actions)
            elif method == "grpo":
                actions = [int(rng.random() < p) for _ in range(config.get("group_size", 8))]
                rewards = [float(action == label) for action in actions]
                mean = sum(rewards) / len(rewards)
                sd = math.sqrt(sum((reward - mean) ** 2 for reward in rewards) / len(rewards))
                direction = sum((reward - mean) / (sd + 1e-8) * (action - p)
                                for action, reward in zip(actions, rewards, strict=True)) / len(actions)
            else:
                # Two-step environment: both actions must be correct to earn terminal reward.
                actions = [int(rng.random() < p) for _ in range(2)]
                reward = float(all(action == label for action in actions))
                success = p if label else 1 - p
                baseline = success ** 2
                direction = (reward - baseline) * sum(action - p for action in actions)
            weights = [w + rate * direction * feature for w, feature in zip(weights, x, strict=True)]
            if step == steps - 1 or (step + 1) % 20 == 0:
                history.append({"step": step + 1, "loss": loss(weights, rows)})
    return {"format": "simulation-linear-v1", "weights": weights, "simulation": True,
            "method": method, "history": history}


def export_model(model, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    files = {"config.json": {"format": "simulation-linear-v1", "simulation": True,
                              "note": "Not a transformers or safetensors model"},
             "tokenizer.json": {"format": "simulation-symbols", "symbols": ["0", "1"]},
             "model.bin": model}
    manifest = []
    for name, value in files.items():
        content = json.dumps(value, sort_keys=True, allow_nan=False).encode()
        (output / name).write_bytes(content)
        manifest.append({"path": name, "sha256": hashlib.sha256(content).hexdigest()})
    return manifest


class SimulationEvaluator:
    def __init__(self, *, root):
        self.root = Path(root)

    def evaluate(self, model, protocol):
        files = {entry["path"]: entry for entry in model["files"]}
        entry = files["model.bin"]
        content = (self.root / "blobs" / entry["sha256"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise ValueError("Model checksum mismatch")
        state = json.loads(content)
        if state.get("format") != "simulation-linear-v1":
            raise ValueError("Simulation evaluator only accepts simulation-linear-v1")
        items = []
        for item in protocol["spec"]["items"]:
            x = json.loads(item["prompt"])["x"]
            answer = str(int(probability(state["weights"], x) >= .5))
            items.append({"id": item["id"], "task": item["task"], "answer": answer,
                          "score": float(answer == str(item["answer"])), "finish_reason": "stop",
                          "output_tokens": 1})
        return {"items": items, "simulation": True, "backend": "cpu-linear"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    state = run_recipe(config)
    manifest = export_model(state, config["output"])
    print(json.dumps({"simulation": True, "history": state["history"], "files": manifest}))


if __name__ == "__main__":
    main()
