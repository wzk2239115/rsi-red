def create_scheduler(config):
    config = dict(config)
    backend = config.pop("backend")
    if backend == "local":
        from .local import LocalScheduler
        return LocalScheduler(**config)
    if backend == "ray":
        from .ray import RayScheduler
        return RayScheduler(**config)
    if backend == "slurm":
        from .slurm import SlurmScheduler
        return SlurmScheduler(**config)
    if backend == "kubernetes":
        from kubernetes import client, config as kubeconfig
        from .kubernetes import KubernetesScheduler
        path = config.pop("kubeconfig", None)
        if path:
            kubeconfig.load_kube_config(config_file=path)
        else:
            kubeconfig.load_incluster_config()
        return KubernetesScheduler(api=client.BatchV1Api(), core_api=client.CoreV1Api(), **config)
    raise ValueError(f"unsupported scheduler backend: {backend}")
