"""Validation and deterministic paired statistics; no fabricated model scores."""
from collections import defaultdict
import math
import random
import statistics

from .errors import ResearchError, require


def summarize(items, protocol):
    expected = {item["id"]: item for item in protocol["spec"]["items"]}
    require(len(expected) == len(protocol["spec"]["items"]), "INVALID_EVALUATION", "Duplicate protocol item")
    require(isinstance(items, list), "INVALID_EVALUATION", "Items must be a list")
    found, tasks = set(), defaultdict(list)
    for item in items:
        require(isinstance(item, dict), "INVALID_EVALUATION", "Invalid item")
        key = item.get("id")
        require(key in expected and key not in found, "INVALID_EVALUATION", "Missing, unknown or duplicate item")
        require(item.get("task") == expected[key]["task"], "INVALID_EVALUATION", "Item task mismatch")
        score = item.get("score")
        require(isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score)
                and 0 <= score <= 1, "INVALID_EVALUATION", "Score must be finite and in [0,1]")
        require(isinstance(item.get("answer"), str) and isinstance(item.get("finish_reason"), str),
                "INVALID_EVALUATION", "Answer and termination evidence required")
        found.add(key)
        tasks[item["task"]].append(score)
    require(found == set(expected), "INVALID_EVALUATION", "Incomplete evaluation")
    scores = {task: statistics.mean(values) for task, values in tasks.items()}
    return {"task_scores": scores, "score": statistics.mean(scores.values())}


def paired_comparison(left, right, *, seed=42, resamples=2000):
    require(left["protocol_digest"] == right["protocol_digest"], "PROTOCOL_MISMATCH", "Different protocols")
    a, b = {x["id"]: x for x in left["items"]}, {x["id"]: x for x in right["items"]}
    require(set(a) == set(b), "ITEM_MISMATCH", "Comparisons require the same items")
    by_task = defaultdict(list)
    for key in sorted(a):
        require(a[key]["task"] == b[key]["task"], "ITEM_MISMATCH", "Item task changed")
        by_task[a[key]["task"]].append(b[key]["score"] - a[key]["score"])
    differences = {task: statistics.mean(values) for task, values in by_task.items()}
    rng = random.Random(seed)
    draws = sorted(statistics.mean(statistics.mean(rng.choices(v, k=len(v))) for v in by_task.values())
                   for _ in range(resamples))
    return {"delta": statistics.mean(differences.values()), "task_deltas": differences,
            "regressions": [task for task, value in differences.items() if value < 0],
            "confidence_interval": [draws[int(.025 * resamples)], draws[min(resamples - 1, int(.975 * resamples))]],
            "method": "paired-item stratified bootstrap; fixed task weights; iid items within task",
            "resamples": resamples, "seed": seed,
            "interpretation": "Exploratory item uncertainty, not independent training repeats or equivalence proof"}


class UnconfiguredEvaluator:
    def evaluate(self, model, protocol):
        raise ResearchError("EVALUATOR_UNAVAILABLE", "Configure a trusted inference evaluator before requesting scores")
