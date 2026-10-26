"""Transactional research control plane. One reconciler per state directory."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import logging
from pathlib import Path
import random
import re
import shutil
import statistics
import threading
import io
import tarfile
import time
from urllib.parse import unquote, urlparse
import uuid

from .audit import AuditMixin, AUDITOR_OPERATIONS, evaluation_summary
from .decontamination import filter_rows
from .errors import ResearchError, envelope, require
from .evaluation import paired_comparison, summarize
from .store import Store, digest

TERMINAL = {"succeeded", "failed", "cancelled", "timed_out"}
SECRET_KEY = re.compile(r"token|secret|password|credential|api[_-]?key", re.I)


def redact(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if SECRET_KEY.search(k) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class ResearchService(AuditMixin):
    def __init__(self, *, root, scheduler, evaluator, clock=time.time, principals, telemetry=None, scheduler_stall_seconds=300):
        if not isinstance(scheduler_stall_seconds, (int, float)) or not math.isfinite(scheduler_stall_seconds) or scheduler_stall_seconds <= 0:
            raise ValueError("scheduler_stall_seconds must be positive and finite")
        self.store = Store(root)
        self.scheduler, self.evaluator, self.clock = scheduler, evaluator, clock
        self.principals = deepcopy(principals)
        self.telemetry = telemetry
        self.scheduler_stall_seconds = scheduler_stall_seconds
        self.evaluation_lock = threading.Lock()
        self._init_audits()

    def close(self):
        self.store.close()

    def _operator(self, actor):
        require(actor["role"] == "operator", "FORBIDDEN", "Operator identity required")

    def _campaign(self, campaign_id, actor):
        campaign = self.store.get(campaign_id, "campaign")
        require(actor["role"] == "operator" or actor["id"] in campaign["members"], "FORBIDDEN", "Not a team member")
        return campaign

    def _entity(self, item_id, kind, actor):
        item = self.store.get(item_id, kind)
        if item.get("campaign_id"):
            self._campaign(item["campaign_id"], actor)
        return item

    def _event(self, name, entity, actor):
        self.store.event(name, entity, actor["id"] if isinstance(actor, dict) else actor, self.clock())

    def dispatch(self, *, token, operation, payload):
        try:
            actor = self.principals.get(token)
            require(isinstance(operation, str), "UNKNOWN_OPERATION", "Operation must be a string")
            require(actor is not None, "UNAUTHENTICATED", "Invalid service credential")
            require(isinstance(payload, dict), "INVALID_REQUEST", "Payload must be an object")
            handler = getattr(self, "op_" + operation.replace(".", "_"), None)
            require(handler is not None and re.fullmatch(r"[a-z]+\.[a-z_]+", operation),
                    "UNKNOWN_OPERATION", "Unknown operation")
            if actor["role"] == "auditor":
                require(operation in AUDITOR_OPERATIONS, "FORBIDDEN", "Auditor operation not permitted")
            with self.store.transaction():
                result = handler(deepcopy(payload), actor)
            return envelope(result)
        except ResearchError as error:
            return envelope(error=error)
        except TimeoutError as error:
            return envelope(error=ResearchError(getattr(error, "code", "SCHEDULER_UNAVAILABLE"),
                                               "Scheduler request unavailable; inspect job health", retryable=True))
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as error:
            # Do not echo payloads, paths, or secret values into errors.
            return envelope(error=ResearchError("INVALID_REQUEST", f"Invalid request ({type(error).__name__})"))

    def op_campaign_create(self, p, actor):
        self._operator(actor)
        self.store.get(p["protocol_id"], "protocol")
        budget = p["gpu_hours_budget"]
        require(isinstance(budget, (float, int)) and math.isfinite(budget) and budget > 0,
                "INVALID_REQUEST", "Budget must be positive")
        require(isinstance(p.get("members"), list) and p["members"], "INVALID_REQUEST", "Members required")
        campaign = self.store.create("campaign", {"name": p["name"], "members": p["members"],
            "protocol_id": p["protocol_id"], "gpu_hours_budget": budget,
            "require_decontamination": p.get("require_decontamination", True), "state": "open"})
        self._event("campaign.created", campaign, actor)
        return campaign

    def _usage(self, campaign_id):
        jobs = [j for j in self.store.list("job") if j["campaign_id"] == campaign_id]
        return {"gpu_seconds": sum(j["gpu_seconds"] for j in jobs),
                "reserved_gpu_seconds": sum(j["reservation"] for j in jobs if j["state"] not in TERMINAL)}

    def op_campaign_show(self, p, actor):
        item = self._campaign(p["id"], actor)
        return dict(item, usage=self._usage(item["id"]))

    def op_campaign_list(self, p, actor):
        return {"items": [c for c in self.store.list("campaign")
                          if actor["role"] == "operator" or actor["id"] in c["members"]]}

    def op_campaign_submit(self, p, actor):
        campaign = self._campaign(p["id"], actor)
        model = self._entity(p["model_id"], "artifact", actor)
        require(model["campaign_id"] == campaign["id"], "FORBIDDEN", "Model belongs to another campaign")
        self._audit_submission_gate(campaign, model)
        campaign["submission"] = model["id"]
        self.store.save("campaign", campaign)
        self._event("campaign.submitted", campaign, actor)
        return {"model_id": model["id"]}

    def op_protocol_register(self, p, actor):
        self._operator(actor)
        require(p["visibility"] in {"development", "held_out"}, "INVALID_REQUEST", "Invalid visibility")
        require(p["items"] and len({i["id"] for i in p["items"]}) == len(p["items"]),
                "INVALID_REQUEST", "Unique nonempty items required")
        require(p.get("aggregation") == "task_mean", "INVALID_REQUEST", "Unsupported aggregation")
        for item in p["items"]:
            require(all(k in item for k in ["id", "task", "prompt", "answer"]), "INVALID_REQUEST", "Invalid item")
        require(p["sampling"]["max_tokens"] > 0, "INVALID_REQUEST", "Invalid output budget")
        protocol = self.store.create("protocol", {"digest": digest(p), "spec": p})
        self._event("protocol.registered", protocol, actor)
        return protocol

    def _protocol(self, item_id, actor):
        protocol = self.store.get(item_id, "protocol")
        if protocol["spec"]["visibility"] == "held_out":
            self._operator(actor)
        return protocol

    def op_protocol_show(self, p, actor):
        protocol = self._protocol(p["id"], actor)
        if actor["role"] == "operator":
            return protocol
        if actor["role"] == "auditor":
            require(any(x['protocol_id'] == protocol['id'] and actor['id'] in x['auditor_ids']
                        and self.store.get(x['campaign_id'], 'campaign').get('audit_policy_id') == x['id']
                        for x in self.store.list('audit_policy')), 'FORBIDDEN', 'Protocol scope not granted')
        return {'id': protocol['id'], 'digest': protocol['digest'],
                'spec': {k: protocol['spec'][k] for k in ('name', 'visibility', 'sampling', 'aggregation',
                                                        'eval_seed', 'evaluator_digest')}}

    def op_protocol_list(self, p, actor):
        if p.get("campaign_id"):
            campaign = self.store.get(p['campaign_id'], 'campaign')
            self._audit_access(campaign['id'], campaign['protocol_id'], actor)
        granted = {policy['protocol_id'] for policy in self.store.list('audit_policy')
                   if actor['id'] in policy['auditor_ids'] and
                   self.store.get(policy['campaign_id'], 'campaign').get('audit_policy_id') == policy['id']}
        return {"items": [{"id": x["id"], "name": x["spec"]["name"], "digest": x["digest"]}
                          for x in self.store.list("protocol") if actor["role"] == "operator"
                          or (x["spec"]["visibility"] == "development" and
                              (actor['role'] != 'auditor' or x['id'] in granted))]}

    def _dataset(self, rows, metadata, actor):
        content = "".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows).encode()
        key = self.store.blob(content)
        dataset = self.store.create("data", dict(metadata, digest=key, rows=len(rows), blob=key))
        self._event("data.registered", dataset, actor)
        return dataset

    def _rows(self, dataset):
        return [json.loads(line) for line in self.store.read_blob(dataset["blob"]).decode().splitlines() if line.strip()]

    def op_data_import(self, p, actor):
        self._campaign(p["campaign_id"], actor)
        rows = [json.loads(line) for line in Path(p["path"]).read_text().splitlines() if line.strip()]
        require(all(isinstance(row, dict) for row in rows), "INVALID_REQUEST", "JSONL rows must be objects")
        return self._dataset(rows, {"campaign_id": p["campaign_id"], "source": p["source"],
            "revision": p["revision"], "license": p.get("license", "unknown"),
            "decontamination": {"status": "unchecked"}}, actor)

    def op_data_inspect(self, p, actor):
        dataset = self._entity(p["id"], "data", actor)
        self.store.read_blob(dataset["blob"])
        return dataset

    def op_data_sample(self, p, actor):
        rows = self._rows(self._entity(p["id"], "data", actor))
        count = p.get("count", 10)
        require(isinstance(count, int) and 0 <= count <= 1000, "INVALID_ARGUMENT", "Invalid sample count")
        return {"items": random.Random(p.get("seed", 42)).sample(rows, min(count, len(rows)))}

    def op_data_check(self, p, actor):
        rows = self._rows(self._entity(p["id"], "data", actor))
        require(p["profile"] in {"sft", "rl"}, "INVALID_REQUEST", "Unsupported profile")
        issues = []
        for index, row in enumerate(rows):
            if p["profile"] == "sft":
                messages = row.get("messages", [])
                valid = (isinstance(messages, list) and bool(messages)
                         and all(isinstance(m, dict) and m.get("role") in {"system", "user", "assistant", "tool"}
                                 and isinstance(m.get("content"), str) and m["content"].strip() for m in messages)
                         and any(m.get("role") == "assistant" for m in messages))
            else:
                valid = bool(row.get("prompt")) and "answer" in row
            if not valid:
                issues.append({"row": index, "code": "INVALID_SCHEMA"})
        return {"valid": not issues, "invalid_rows": len(issues), "issues": issues[:1000]}

    def op_data_decontaminate(self, p, actor):
        dataset = self._entity(p["id"], "data", actor)
        campaign = self._campaign(p["campaign_id"], actor)
        require(dataset["campaign_id"] == campaign["id"], "FORBIDDEN", "Dataset belongs to another campaign")
        # Trusted service side only. Researcher sees aggregate counts, never hidden matches.
        protocols = self.store.list("protocol")
        targets = [str(item["prompt"]) for prot in protocols for item in prot["spec"]["items"]]
        rows = self._rows(dataset)
        proxy = [{"text": json.dumps(row, ensure_ascii=False), "original": row} for row in rows]
        report = filter_rows(proxy, targets, text_field="text")
        metadata = {k: v for k, v in dataset.items() if k not in {"id", "digest", "rows", "blob"}}
        policy_digest = digest(sorted(prot["digest"] for prot in protocols))
        metadata.update(parent_dataset=dataset["id"], decontamination={"status": "checked",
                        "policy_digest": policy_digest, "method": "normalized-word-13gram-half-coverage"})
        output = self._dataset([row["original"] for row in report["rows"]], metadata, actor)
        return {"output_dataset_id": output["id"], "removed_count": report["removed_count"],
                "semantic_contamination_free": False}

    def op_artifact_register(self, p, actor):
        self._campaign(p["campaign_id"], actor)
        source = Path(p["path"]).resolve()
        files, seen = [], set()
        for entry in p["files"]:
            name = entry["path"]
            relative = Path(name)
            require(not relative.is_absolute() and ".." not in relative.parts and name not in seen,
                    "INVALID_PATH", "Invalid manifest path")
            path = (source / relative).resolve()
            require(path.is_relative_to(source) and not (source / relative).is_symlink(),
                    "INVALID_PATH", "Manifest escapes source")
            content = path.read_bytes()
            require(hashlib.sha256(content).hexdigest() == entry["sha256"], "CHECKSUM_MISMATCH", "Checksum mismatch")
            self.store.blob(content)
            files.append({"path": name, "sha256": entry["sha256"], "bytes": len(content)})
            seen.add(name)
        require("config.json" in seen and ("tokenizer.json" in seen or "tokenizer.model" in seen)
                and any(name.endswith((".safetensors", ".bin")) for name in seen),
                "INCOMPLETE_MODEL", "Model configuration, tokenizer and weights required")
        parents = p.get("parents", [])
        for parent in parents:
            model = self._entity(parent, "artifact", actor)
            require(model["campaign_id"] == p["campaign_id"], "FORBIDDEN", "Parent belongs to another campaign")
        artifact = self.store.create("artifact", {"campaign_id": p["campaign_id"], "kind": p.get("kind", "model"),
            "files": files, "parents": list(dict.fromkeys(parents)), "digest": digest(files),
            "provenance": redact(p.get("provenance", {}))})
        self._event("artifact.registered", artifact, actor)
        return artifact

    def op_artifact_show(self, p, actor):
        return self._entity(p["id"], "artifact", actor)

    def op_artifact_fetch(self, p, actor):
        artifact = self._entity(p["id"], "artifact", actor)
        destination = Path(p["output"]).resolve()
        require(not destination.exists(), "OUTPUT_EXISTS", "Destination already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex)
        temporary.mkdir()
        try:
            for entry in artifact["files"]:
                path = temporary / entry["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(self.store.read_blob(entry["sha256"]))
            temporary.rename(destination)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return {"id": artifact["id"], "digest": artifact["digest"], "output": str(destination)}

    def op_artifact_lineage(self, p, actor):
        nodes, edges, pending = {}, [], [p["id"]]
        while pending:
            key = pending.pop()
            if key in nodes:
                continue
            model = self._entity(key, "artifact", actor)
            nodes[key] = model
            for parent in model["parents"]:
                edges.append({"parent": parent, "child": key})
                pending.append(parent)
        return {"nodes": list(nodes.values()), "edges": edges}

    def op_recipe_create(self, p, actor):
        self._campaign(p["campaign_id"], actor)
        for field in ("title", "hypothesis", "method"):
            require(isinstance(p.get(field), str) and 0 < len(p[field]) <= 4000,
                    "INVALID_REQUEST", "Recipe title, hypothesis and method required")
        for field, kind in (("datasets", "data"), ("parents", "artifact")):
            require(isinstance(p.get(field, []), list), "INVALID_REQUEST", "Recipe inputs must be lists")
            for key in p.get(field, []):
                item = self._entity(key, kind, actor)
                require(item["campaign_id"] == p["campaign_id"], "FORBIDDEN", "Cross-campaign input")
        require(isinstance(p.get("parameters", {}), dict), "INVALID_REQUEST", "Parameters must be an object")
        item = self.store.create("recipe", {"campaign_id": p["campaign_id"], "owner": actor["id"],
            "title": p["title"], "hypothesis": p["hypothesis"], "method": p["method"],
            "datasets": p.get("datasets", []), "parents": p.get("parents", []),
            "parameters": redact(p.get("parameters", {})), "source": "agent_report", "state": "planned",
            "history": [{"state": "planned", "time": self.clock(), "observation": "", "author": actor["id"]}]})
        self._event("recipe.created", item, actor)
        return item

    def op_recipe_update(self, p, actor):
        item = self._entity(p["id"], "recipe", actor)
        require(item["owner"] == actor["id"], "FORBIDDEN", "Only recipe author can report progress")
        require(p.get("state") in {"planned", "trying", "completed", "abandoned"},
                "INVALID_REQUEST", "Invalid recipe state")
        require(isinstance(p.get("observation", ""), str) and len(p.get("observation", "")) <= 16000,
                "INVALID_REQUEST", "Invalid observation")
        item["state"] = p["state"]
        item["history"].append({"state": p["state"], "time": self.clock(),
                                "observation": p.get("observation", ""), "author": actor["id"]})
        self.store.save("recipe", item)
        self._event("recipe.updated", item, actor)
        return item

    def op_recipe_show(self, p, actor):
        item = self._entity(p["id"], "recipe", actor)
        jobs = [j for j in self.store.list("job") if j["spec"].get("recipe_id") == item["id"]]
        return dict(item, jobs=[{"id": j["id"], "state": j["state"], "owner": j["owner"]} for j in jobs])

    def op_recipe_list(self, p, actor):
        self._campaign(p["campaign_id"], actor)
        return {"items": [self.op_recipe_show({"id": item["id"]}, actor)
                          for item in self.store.list("recipe") if item["campaign_id"] == p["campaign_id"]]}

    def op_resource_show(self, p, actor):
        self._operator(actor)
        telemetry = self.telemetry.sample() if self.telemetry else {
            "status": "unavailable", "source": None, "scope": None, "sampled_at": None, "gpus": []}
        return {"telemetry": telemetry, "note": "GPU requests are not measured allocation or utilization"}

    def op_job_submit(self, p, actor):
        campaign = self._campaign(p["campaign_id"], actor)
        require(campaign["state"] == "open", "CAMPAIGN_CLOSED", "Research window is closed")
        request_digest = digest(redact(p))
        for existing in self.store.list("job"):
            if existing["campaign_id"] == campaign["id"] and existing["key"] == p["idempotency_key"]:
                require(existing["request_digest"] == request_digest, "IDEMPOTENCY_CONFLICT", "Key was used for another request")
                return existing
        require(isinstance(p.get("entrypoint"), list) and p["entrypoint"]
                and all(isinstance(arg, str) for arg in p["entrypoint"]), "INVALID_REQUEST", "Entrypoint must be argv")
        resources = p["resources"]
        gpus, seconds = resources["gpus"], resources["walltime_seconds"]
        require(isinstance(gpus, int) and not isinstance(gpus, bool) and gpus >= 0
                and isinstance(seconds, (int, float)) and math.isfinite(seconds) and seconds > 0,
                "INVALID_REQUEST", "Invalid resources")
        if gpus:
            require("@sha256:" in p.get("image", ""), "INVALID_REQUEST", "Pinned image required for GPU jobs")
        for key in p.get("datasets", []):
            dataset = self._entity(key, "data", actor)
            if campaign["require_decontamination"]:
                policy = digest(sorted(prot["digest"] for prot in self.store.list("protocol")))
                require(dataset["decontamination"].get("status") == "checked"
                        and dataset["decontamination"].get("policy_digest") == policy,
                        "DATA_NOT_CLEARED", "Dataset not checked against current protected policy")
            require(dataset["campaign_id"] == campaign["id"], "FORBIDDEN", "Dataset belongs to another campaign")
        for key in p.get("parents", []):
            model = self._entity(key, "artifact", actor)
            require(model["campaign_id"] == campaign["id"], "FORBIDDEN", "Model belongs to another campaign")
        for key in p.get("depends_on", []):
            dependency = self._entity(key, "job", actor)
            require(dependency["campaign_id"] == campaign["id"], "FORBIDDEN", "Dependency belongs to another campaign")
        if p.get("recipe_id"):
            recipe = self._entity(p["recipe_id"], "recipe", actor)
            require(recipe["campaign_id"] == campaign["id"] and recipe["owner"] == actor["id"],
                    "FORBIDDEN", "Recipe must belong to submitting peer and campaign")
            require(set(recipe["datasets"]) == set(p.get("datasets", []))
                    and set(recipe["parents"]) == set(p.get("parents", [])),
                    "RECIPE_INPUT_MISMATCH", "Create another recipe for changed inputs")
        allocated = sum(j["gpu_seconds"] if j["state"] in TERMINAL else max(j["gpu_seconds"], j["reservation"])
                        for j in self.store.list("job") if j["campaign_id"] == campaign["id"])
        reservation = gpus * seconds
        require(allocated + reservation <= campaign["gpu_hours_budget"] * 3600,
                "BUDGET_EXCEEDED", "Campaign GPU time budget exhausted")
        # Refuse to persist secret literals. Normal environment values remain reproducible.
        spec = redact(p)
        spec["dropped_secret_env_keys"] = [key for key in p.get("env", {}) if SECRET_KEY.search(key)]
        spec["env"] = {key: value for key, value in spec.get("env", {}).items() if value != "[REDACTED]"}
        code = p["code"]
        parsed = urlparse(code["uri"])
        require(parsed.scheme == "file", "INVALID_REQUEST", "Upload code to a local service-visible file URI")
        content = Path(unquote(parsed.path)).read_bytes()
        key = self.store.blob(content)
        require(code["digest"] == "sha256:" + key, "CHECKSUM_MISMATCH", "Code snapshot checksum mismatch")
        job = self.store.create("job", {"campaign_id": campaign["id"], "owner": actor["id"], "spec": spec,
            "key": p["idempotency_key"], "request_digest": request_digest, "code_blob": key,
            "experiment_id": "experiment_" + uuid.uuid4().hex, "state": "accepted", "reason": None,
            "scheduler_id": None, "reservation": reservation, "gpu_seconds": 0, "attempt_count": 0,
            "submission_attempted": False})
        self._event("job.accepted", job, actor)
        return job

    def op_job_show(self, p, actor):
        return self._entity(p["id"], "job", actor)

    def op_job_list(self, p, actor):
        self._campaign(p["campaign_id"], actor)
        return {"items": [j for j in self.store.list("job") if j["campaign_id"] == p["campaign_id"]]}

    def op_job_cancel(self, p, actor):
        job = self._entity(p["id"], "job", actor)
        if job["state"] in TERMINAL:
            return job
        if job["scheduler_id"] or job["submission_attempted"]:
            job["cancel_requested"] = True
        else:
            job.update(state="cancelled", reason="user_cancelled")
        self.store.save("job", job)
        self._event("job.cancel_requested", job, actor)
        if job["state"] == "cancelled":
            self._event("job.cancelled", job, actor)
        return job

    def op_job_logs(self, p, actor):
        job = self._entity(p["id"], "job", actor)
        return {"items": self.scheduler.logs(job["scheduler_id"], offset=p.get("offset", 0),
                                            limit=min(p.get("limit", 100), 1000)) if job["scheduler_id"] else []}

    def op_eval_submit(self, p, actor):
        self._campaign(p["campaign_id"], actor)
        model = self._entity(p["model_id"], "artifact", actor)
        require(model["campaign_id"] == p["campaign_id"], "FORBIDDEN", "Model belongs to another campaign")
        protocol = self._protocol(p["protocol_id"], actor)
        self._audit_eval_budget(p["campaign_id"], protocol["id"])
        evaluation = self.store.create("eval", {"campaign_id": p["campaign_id"], "model_id": model["id"],
            "protocol_id": protocol["id"], "model_digest": model["digest"], "protocol_digest": protocol["digest"],
            "state": "accepted", "visibility": protocol["spec"]["visibility"], "reason": None,
            "eval_seed": protocol["spec"]["eval_seed"],
            "repeat_index": sum(e["model_id"] == model["id"] and e["protocol_id"] == protocol["id"]
                                for e in self.store.list("eval"))})
        self._event("eval.accepted", evaluation, actor)
        return evaluation

    def _eval(self, item_id, actor):
        item = self.store.get(item_id, "eval")
        self._audit_access(item['campaign_id'], item['protocol_id'], actor)
        if item["visibility"] == "held_out":
            self._operator(actor)
        return item

    def op_eval_show(self, p, actor):
        item = self._eval(p["id"], actor)
        return evaluation_summary(item)

    def op_eval_samples(self, p, actor):
        item = self._eval(p["id"], actor)
        require(actor["role"] == "operator", "EVALUATION_DETAILS_RESTRICTED", "Raw evaluation details are operator-only")
        rows = item.get("items", [])
        if p.get("filter") == "truncated":
            rows = [row for row in rows if row["finish_reason"] == "length"]
        offset, limit = p.get("offset", 0), min(p.get("limit", 100), 1000)
        require(offset >= 0 and limit > 0, "INVALID_ARGUMENT", "Invalid pagination")
        return {"items": rows[offset:offset + limit], "total": len(rows)}

    def op_eval_compare(self, p, actor):
        a, b = self._eval(p["left"], actor), self._eval(p["right"], actor)
        require(a["state"] == b["state"] == "succeeded", "EVALUATION_NOT_READY", "Both evaluations must succeed")
        return paired_comparison(a, b)

    def op_events_list(self, p, actor):
        self._campaign(p["campaign_id"], actor)
        events = self.store.events(p["campaign_id"], p.get("after"), max(1, min(p.get("limit", 100), 1000)))
        if actor["role"] != "operator":
            # Hidden evaluation events must not become an oracle or leak IDs.
            events = [event for event in events if not event["type"].startswith("eval.")
                      or self.store.get(event["entity_id"], "eval")["visibility"] != "held_out"]
        return {"items": events}

    def op_note_add(self, p, actor):
        self._campaign(p["campaign_id"], actor)
        for key in p.get("evidence_ids", []):
            evidence = self.store.get(key)
            require(evidence.get("campaign_id") == p["campaign_id"], "FORBIDDEN", "Invalid evidence scope")
            if evidence.get("visibility") == "held_out":
                self._operator(actor)
        note = self.store.create("note", {"campaign_id": p["campaign_id"], "author": actor["id"],
            "text": p["text"], "evidence_ids": p.get("evidence_ids", [])})
        self._event("note.added", note, actor)
        return note

    def op_note_show(self, p, actor):
        return self._entity(p["id"], "note", actor)

    def _scheduler_fault(self, job, error, code=None):
        previous = job.get("scheduler_health", {})
        since = previous.get("since", self.clock()) if previous.get("status") != "healthy" else self.clock()
        status = "stalled" if getattr(error, "code", None) == "RAY_JOB_LOST" or self.clock() - since >= self.scheduler_stall_seconds else "degraded"
        health = {"status": status, "code": code or getattr(error, "code", "SCHEDULER_UNAVAILABLE"),
                  "since": since, "last_checked": self.clock(), "failures": previous.get("failures", 0) + 1,
                  "needs_operator": status == "stalled"}
        with self.store.transaction():
            job["scheduler_health"] = health
            self.store.save("job", job)
            if previous.get("status") != status or previous.get("code") != health["code"]:
                self._event("job.scheduler_" + status, job, "service")
                logging.warning("scheduler %s job=%s code=%s", status, job["id"], health["code"])
        # Keep reservation: timeout is not proof that an external GPU job has stopped.

    def _scheduler_recovered(self, job):
        previous = job.get("scheduler_health", {})
        if previous and previous.get("status") != "healthy":
            job["scheduler_health"] = {"status": "healthy", "last_checked": self.clock()}
            self._event("job.scheduler_recovered", job, "service")

    def reconcile_jobs(self):
        # Single controller. Durable markers are committed before all external effects.
        with self.store.lock:
            jobs = self.store.list("job")
            for snapshot in jobs:
                job = self.store.get(snapshot["id"], "job")
                if job["state"] in TERMINAL:
                    continue
                if not job["scheduler_id"]:
                    dependencies = [self.store.get(key, "job") for key in job["spec"].get("depends_on", [])]
                    if any(d["state"] in TERMINAL - {"succeeded"} for d in dependencies):
                        with self.store.transaction():
                            job.update(state="failed", reason="dependency_failed")
                            self.store.save("job", job)
                            self._event("job.failed", job, "service")
                        continue
                    if any(d["state"] != "succeeded" for d in dependencies):
                        continue
                    try:
                        sid = self.scheduler.find(job["id"])
                        if sid is None:
                            if job.get("cancel_requested"):
                                with self.store.transaction():
                                    job.update(state="cancelled", reason="user_cancelled")
                                    self.store.save("job", job)
                                continue
                            # A prior ambiguous submit must stay unresolved until scheduler confirms it;
                            # never blindly resubmit after a timeout.
                            if job["submission_attempted"]:
                                self._scheduler_fault(job, None, "SUBMISSION_UNRESOLVED")
                                continue
                            with self.store.transaction():
                                job["submission_attempted"] = True
                                job["attempt_count"] += 1
                                self.store.save("job", job)
                            request = self._execution_request(job)
                            sid = self.scheduler.submit(request, submission_key=job["id"])
                        with self.store.transaction():
                            job.update(scheduler_id=sid, state="queued")
                            self._scheduler_recovered(job)
                            self.store.save("job", job)
                            self._event("job.queued", job, "service")
                    except TimeoutError as error:
                        self._scheduler_fault(job, error)
                        continue
                    except (OSError, RuntimeError, ValueError, ResearchError) as error:
                        with self.store.transaction():
                            job.update(state="failed", reason="submission_error", diagnostic=type(error).__name__)
                            self.store.save("job", job)
                            self._event("job.failed", job, "service")
                        continue
                try:
                    if job.get("cancel_requested"):
                        self.scheduler.cancel(job["scheduler_id"])
                    status = self.scheduler.status(job["scheduler_id"])
                    require(status["state"] in TERMINAL | {"queued", "running"}, "INVALID_STATE", "Invalid scheduler state")
                    with self.store.transaction():
                        changed = status["state"] != job["state"]
                        self._scheduler_recovered(job)
                        for key in ("exit_code", "diagnostic", "scheduler_error_type", "accounting_estimate",
                                    "accounting_scope", "environment_verification"):
                            if key in status:
                                job[key] = status[key]
                        job.update(state=status["state"], reason=status.get("reason"),
                                   gpu_seconds=max(job["gpu_seconds"], status.get("gpu_seconds", 0)))
                        self.store.save("job", job)
                        if changed:
                            self._event("job." + job["state"], job, "service")
                except (TimeoutError, OSError) as error:
                    self._scheduler_fault(job, error)
                    continue
    def _execution_request(self, job):
        request = deepcopy(job["spec"])
        folder = self.store.root / "execution" / job["id"]
        folder.mkdir(parents=True, exist_ok=True)
        content = self.store.read_blob(job["code_blob"])
        original = Path(unquote(urlparse(request["code"]["uri"]).path))
        if original.name.endswith((".tar", ".tar.gz", ".tgz")):
            with tarfile.open(fileobj=io.BytesIO(content)) as archive:
                for member in archive.getmembers():
                    path = (folder / member.name).resolve()
                    require(path.is_relative_to(folder) and (member.isfile() or member.isdir()),
                            "INVALID_PATH", "Unsafe code archive")
                archive.extractall(folder, filter="data")
        else:
            snapshot = folder / original.name
            snapshot.write_bytes(content)
            request["entrypoint"] = [str(snapshot) if arg in {str(original), original.name} else arg
                                     for arg in request["entrypoint"]]
        request["workdir"] = str(folder)
        request["log_path"] = str(folder / "training.log")
        return request

    def reconcile_evaluations(self):
        # Only one evaluator loop per controller; crucially no DB/request lock during inference.
        if not self.evaluation_lock.acquire(blocking=False):
            return
        try:
            with self.store.lock:
                pending = [e for e in self.store.list("eval") if e["state"] in {"accepted", "running"}]
            for evaluation in pending:
                with self.store.transaction():
                    evaluation["state"] = "running"
                    self.store.save("eval", evaluation)
                    model = self.store.get(evaluation["model_id"], "artifact")
                    protocol = self.store.get(evaluation["protocol_id"], "protocol")
                try:
                    result = self.evaluator.evaluate(model, protocol)
                    values = summarize(result["items"], protocol)
                    evaluation.update(values, items=result["items"], state="succeeded",
                                      simulation=bool(result.get("simulation", False)))
                except Exception as error:
                    evaluation.update(state="failed", reason=error.code if isinstance(error, ResearchError)
                                      else "evaluator_error")
                with self.store.transaction():
                    self.store.save("eval", evaluation)
                    self._event("eval." + evaluation["state"], evaluation, "service")
        finally:
            self.evaluation_lock.release()

    def reconcile(self):
        self.reconcile_jobs()
        self.reconcile_evaluations()
        self.reconcile_audits()

    def op_eval_aggregate(self, p, actor):
        evaluations = [self._eval(key, actor) for key in p["ids"]]
        require(evaluations and len({e["id"] for e in evaluations}) == len(evaluations),
                "INVALID_ARGUMENT", "Distinct evaluation IDs required")
        require(all(e["state"] == "succeeded" for e in evaluations), "EVALUATION_NOT_READY", "Incomplete repeats")
        require(len({(e["model_digest"], e["protocol_digest"]) for e in evaluations}) == 1,
                "PROTOCOL_MISMATCH", "Same model and protocol required")
        values = [e["score"] for e in evaluations]
        return {"count": len(values), "mean": statistics.mean(values),
                "standard_error_over_eval_repeats": statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else None,
                "independent_training_runs": False}

    def op_transcript_append(self, p, actor):
        self._campaign(p["campaign_id"], actor)
        require(isinstance(p.get("text"), str) and len(p["text"].encode()) <= 1024 * 1024,
                "INVALID_REQUEST", "Transcript chunk too large or invalid")
        require(isinstance(p.get("sequence"), int) and p["sequence"] >= 0,
                "INVALID_REQUEST", "Nonnegative chunk sequence required")
        session = next((item for item in self.store.list("transcript") if item["campaign_id"] == p["campaign_id"]
                        and item["session_id"] == p["session_id"]), None)
        if session is None:
            require(p["sequence"] == 0, "INVALID_ARGUMENT", "A new session starts with chunk zero")
            session = self.store.create("transcript", {"campaign_id": p["campaign_id"], "session_id": p["session_id"],
                "author": actor["id"], "chunks": []})
        require(session["author"] == actor["id"], "FORBIDDEN", "Only session owner can append")
        if p["sequence"] < len(session["chunks"]):
            require(session["chunks"][p["sequence"]]["text"] == p["text"],
                    "IDEMPOTENCY_CONFLICT", "Chunk already contains different text")
            return session
        require(p["sequence"] == len(session["chunks"]), "INVALID_ARGUMENT", "Non-contiguous chunk sequence")
        session["chunks"].append({"sequence": p["sequence"], "text": p["text"], "time": self.clock()})
        self.store.save("transcript", session)
        self._event("transcript.appended", session, actor)
        return session

    def op_transcript_show(self, p, actor):
        self._campaign(p["campaign_id"], actor)
        for session in self.store.list("transcript"):
            if session["campaign_id"] == p["campaign_id"] and session["session_id"] == p["session_id"]:
                return session
        raise ResearchError("NOT_FOUND", "Session not found")
