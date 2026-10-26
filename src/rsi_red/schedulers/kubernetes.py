"""BatchV1Api adapter. Production credentials are loaded only when this backend is selected."""
from datetime import datetime, timezone
import hashlib


def as_dict(value):
    return value if isinstance(value, dict) else value.to_dict()


class KubernetesScheduler:
    def __init__(self, *, api, namespace, core_api=None, volumes=None, volume_mounts=None):
        self.api, self.namespace, self.core_api = api, namespace, core_api
        self.volumes, self.volume_mounts = volumes or [], volume_mounts or []

    def submit(self, request, *, submission_key):
        name = "rsi-" + hashlib.sha256(submission_key.encode()).hexdigest()[:40]
        labels = {"rsi-red/submission-key": submission_key}
        container = {"name": "research", "image": request["image"], "command": request["entrypoint"],
                     "resources": {"limits": {"nvidia.com/gpu": request["resources"]["gpus"]}},
                     "env": [{"name": k, "value": str(v)} for k, v in request.get("env", {}).items()],
                     "volumeMounts": self.volume_mounts}
        if request.get("workdir"):
            container["workingDir"] = request["workdir"]
        body = {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": name, "labels": labels},
                "spec": {"backoffLimit": 0, "activeDeadlineSeconds": int(request["resources"]["walltime_seconds"]),
                         "template": {"metadata": {"labels": labels}, "spec": {"restartPolicy": "Never",
                                      "containers": [container], "volumes": self.volumes}}}}
        self.api.create_namespaced_job(namespace=self.namespace, body=body)
        return name

    def find(self, submission_key):
        result = self.api.list_namespaced_job(namespace=self.namespace,
                                            label_selector="rsi-red/submission-key=" + submission_key)
        items = result.get("items", []) if isinstance(result, dict) else result.items
        if len(items) > 1:
            raise RuntimeError("Multiple Kubernetes jobs have the same submission identity")
        if items:
            return as_dict(items[0])["metadata"]["name"]
        return None

    def status(self, job_id):
        job = as_dict(self.api.read_namespaced_job(job_id, self.namespace))
        status = job.get("status", {})
        conditions = status.get("conditions") or []
        state, reason = "queued", None
        if status.get("active"):
            state = "running"
        if status.get("succeeded"):
            state = "succeeded"
        for condition in conditions:
            if str(condition.get("status")).lower() != "true":
                continue
            if condition.get("type") == "Complete":
                state = "succeeded"
            if condition.get("type") == "Failed":
                reason = condition.get("reason", "training_error")
                state = "timed_out" if reason == "DeadlineExceeded" else "failed"
        if self.core_api:
            pods = self.core_api.list_namespaced_pod(namespace=self.namespace, label_selector="job-name=" + job_id)
            for pod in pods.items:
                for container in pod.status.container_statuses or []:
                    terminated = container.state.terminated
                    if terminated and terminated.reason == "OOMKilled":
                        state, reason = "failed", "oom"
        begin = status.get("start_time") or status.get("startTime")
        end = status.get("completion_time") or status.get("completionTime")
        def timestamp(value):
            return value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        seconds = max(0, (timestamp(end) if end else datetime.now(timezone.utc)) .timestamp() - timestamp(begin).timestamp()) if begin else 0
        containers = job["spec"]["template"]["spec"]["containers"]
        gpus = sum(int(c.get("resources", {}).get("limits", {}).get("nvidia.com/gpu", 0)) for c in containers)
        return {"state": state, "reason": reason, "gpu_seconds": seconds * gpus}

    def cancel(self, job_id):
        self.api.delete_namespaced_job(name=job_id, namespace=self.namespace, propagation_policy="Foreground")

    def logs(self, job_id, *, offset=0, limit=100):
        if not self.core_api:
            raise RuntimeError("Kubernetes CoreV1Api log access is not configured")
        pods = self.core_api.list_namespaced_pod(namespace=self.namespace, label_selector="job-name=" + job_id)
        lines = []
        for pod in pods.items:
            lines.extend(self.core_api.read_namespaced_pod_log(pod.metadata.name, self.namespace).splitlines())
        return lines[offset:offset + limit]
