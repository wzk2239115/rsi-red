"""Validation and deterministic paired statistics; no fabricated model scores."""
from collections import defaultdict
import math
import random
import statistics

from .errors import ResearchError, require
from .directions import NORMALIZATION, task_metadata


def summarize(items, protocol):
    metadata = task_metadata(protocol['spec'])
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
    normalized = {task: value if metadata[task]['direction'] == 'maximize' else 1 - value
                  for task, value in scores.items()}
    return {'raw_task_scores': scores, 'raw_score': statistics.mean(scores.values()),
            'normalized_task_scores': normalized, 'normalized_score': statistics.mean(normalized.values()),
            'task_scores': normalized, 'score': statistics.mean(normalized.values()),
            'task_metrics': metadata, 'normalization': NORMALIZATION}


def paired_comparison(left, right, *, seed=42, resamples=2000):
    require(left["protocol_digest"] == right["protocol_digest"], "PROTOCOL_MISMATCH", "Different protocols")
    a, b = {x["id"]: x for x in left["items"]}, {x["id"]: x for x in right["items"]}
    require(set(a) == set(b), "ITEM_MISMATCH", "Comparisons require the same items")
    metadata = left.get('task_metrics')
    require(metadata and metadata == right.get('task_metrics'), 'DIRECTION_UNCONFIGURED', 'Matching directions required')
    by_task = defaultdict(list)
    for key in sorted(a):
        require(a[key]["task"] == b[key]["task"], "ITEM_MISMATCH", "Item task changed")
        task = a[key]['task']
        sign = 1 if metadata[task]['direction'] == 'maximize' else -1
        by_task[task].append(sign * (b[key]["score"] - a[key]["score"]))
    differences = {task: statistics.mean(values) for task, values in by_task.items()}
    rng = random.Random(seed)
    draws = sorted(statistics.mean(statistics.mean(rng.choices(v, k=len(v))) for v in by_task.values())
                   for _ in range(resamples))
    fields = ('model_id', 'raw_score', 'raw_task_scores', 'normalized_score', 'normalized_task_scores')
    return {"delta": statistics.mean(differences.values()), "task_deltas": differences,
            'task_metrics': metadata, 'normalization': NORMALIZATION,
            'left': dict({k: left[k] for k in fields if k in left}, eval_id=left.get('id')),
            'right': dict({k: right[k] for k in fields if k in right}, eval_id=right.get('id')),
            "regressions": [task for task, value in differences.items() if value < 0],
            "confidence_interval": [draws[int(.025 * resamples)], draws[min(resamples - 1, int(.975 * resamples))]],
            "method": "paired-item stratified bootstrap; fixed task weights; iid items within task",
            "resamples": resamples, "seed": seed,
            "interpretation": "Exploratory item uncertainty, not independent training repeats or equivalence proof"}


class UnconfiguredEvaluator:
    def evaluate(self, model, protocol):
        raise ResearchError("EVALUATOR_UNAVAILABLE", "Configure a trusted inference evaluator before requesting scores")
