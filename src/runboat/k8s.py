import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from enum import Enum
from importlib import resources
from pathlib import Path
from typing import Any, TypedDict, cast

import urllib3
from jinja2 import Template
from kubernetes import client, config, watch
from kubernetes.client.exceptions import ApiException
from kubernetes.client.models.v1_deployment import V1Deployment
from kubernetes.client.models.v1_job import V1Job
from pydantic import BaseModel
from typing_extensions import NotRequired

from .github import CommitInfo
from .settings import BuildSettings, settings
from .utils import sync_to_async, sync_to_async_iterator

_logger = logging.getLogger(__name__)


def _split_image_name_tag(image: str) -> tuple[str, str]:
    img, _, tag = image.partition(":")
    return (img, tag or "latest")


@sync_to_async
def load_kube_config() -> None:
    if "KUBECONFIG" in os.environ:
        config.load_kube_config()
    else:
        config.load_incluster_config()


@sync_to_async
def read_deployment(name: str) -> V1Deployment | None:
    appsv1 = client.AppsV1Api()
    items = appsv1.list_namespaced_deployment(
        namespace=settings.build_namespace,
        label_selector=f"runboat/build={name}",
    ).items
    return items[0] if items else None


@sync_to_async
def delete_deployment(deployment_name: str) -> None:
    appsv1 = client.AppsV1Api()
    appsv1.delete_namespaced_deployment(
        deployment_name, namespace=settings.build_namespace
    )


class PatchOperation(TypedDict):
    op: str
    path: str
    value: NotRequired[str | int]


@sync_to_async
def patch_deployment(
    deployment_name: str, ops: list[PatchOperation], not_found_ok: bool
) -> None:
    appsv1 = client.AppsV1Api()
    try:
        appsv1.patch_namespaced_deployment(
            name=deployment_name,
            namespace=settings.build_namespace,
            body=ops,
        )
    except ApiException as e:
        if e.status == 404 and not_found_ok:
            return
        raise


class WatchException(Exception):
    pass


def _watch(
    list_method: Callable[..., Any], *args: Any, **kwargs: Any
) -> Generator[tuple[str | None, Any], None, None]:
    while True:
        try:
            # perform a first query
            res = list_method(*args, **kwargs)
            resource_version = res.metadata.resource_version
            assert resource_version
            for item in res.items:
                yield None, item
            # stream until timeout
            while True:
                try:
                    for event in watch.Watch().stream(
                        list_method,
                        *args,
                        **kwargs,
                        resource_version=resource_version,
                        _request_timeout=60,
                    ):
                        event_type = event["type"]
                        event_object = event["object"]
                        if event_type == "ERROR":
                            raise RuntimeError("Kubernetes watch ERROR")
                        elif event_type not in ("ADDED", "MODIFIED", "DELETED"):
                            raise RuntimeError(f"Unexpected event {event_type}")
                        resource_version = event_object.metadata.resource_version
                        assert resource_version
                        yield event_type, event_object
                except (urllib3.exceptions.TimeoutError, TimeoutError):
                    continue
        except Exception as e:
            raise WatchException(f"{e} in {list_method.__name__}") from e


@sync_to_async_iterator
def watch_deployments() -> Generator[V1Deployment, None, None]:
    appsv1 = client.AppsV1Api()
    yield from _watch(
        appsv1.list_namespaced_deployment, namespace=settings.build_namespace
    )


@sync_to_async_iterator
def watch_jobs() -> Generator[V1Job, None, None]:
    batchv1 = client.BatchV1Api()
    yield from _watch(batchv1.list_namespaced_job, namespace=settings.build_namespace)


class DeploymentMode(str, Enum):
    deployment = "deployment"
    initialize = "initialize"
    cleanup = "cleanup"


class DeploymentVars(BaseModel):
    namespace: str
    mode: DeploymentMode
    build_name: str
    build_slug: str
    build_domain: str
    commit_info: CommitInfo
    image_name: str
    image_tag: str
    build_env: dict[str, str]
    build_secret_env: dict[str, str]
    build_template_vars: dict[str, str]


def make_deployment_vars(
    mode: DeploymentMode,
    build_name: str,
    slug: str,
    commit_info: CommitInfo,
    build_settings: BuildSettings,
) -> DeploymentVars:
    image_name, image_tag = _split_image_name_tag(build_settings.image)
    return DeploymentVars(
        mode=mode,
        namespace=settings.build_namespace,
        build_name=build_name,
        build_slug=slug,
        build_domain=settings.build_domain,
        commit_info=commit_info,
        image_name=image_name,
        image_tag=image_tag,
        build_env=settings.build_env | build_settings.env,
        build_secret_env=settings.build_secret_env | build_settings.secret_env,
        build_template_vars=settings.build_template_vars | build_settings.template_vars,
    )


@contextmanager
def _get_kubefiles_path(kubefiles_path: Path | None) -> Generator[Path, None, None]:
    if kubefiles_path:
        yield kubefiles_path
    else:
        with resources.path(__package__, "kubefiles") as default_kubefiles_path:
            yield default_kubefiles_path


@contextmanager
def _render_kubefiles(
    kubefiles_path: Path | None, deployment_vars: DeploymentVars
) -> Generator[Path, None, None]:
    with _get_kubefiles_path(
        kubefiles_path
    ) as kubefiles_path, tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        _logger.debug("kubefiles path: %s", kubefiles_path)
        # TODO async copytree, or make this whole _render_kubefiles run_in_executor
        shutil.copytree(kubefiles_path, tmp_path, dirs_exist_ok=True)
        template = Template((tmp_path / "kustomization.yaml.jinja").read_text())
        (tmp_path / "kustomization.yaml").write_text(
            template.render(dict(deployment_vars))
        )
        yield tmp_path


async def _kubectl(args: list[str]) -> None:
    _logger.debug("kubectl %s", " ".join(args))
    proc = await asyncio.create_subprocess_exec(
        "kubectl", *args, stdout=subprocess.DEVNULL
    )
    return_code = await proc.wait()
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, ["kubectl", *args])


async def deploy(kubefiles_path: Path | None, deployment_vars: DeploymentVars) -> None:
    with _render_kubefiles(kubefiles_path, deployment_vars) as tmp_path:
        # Dry-run first to avoid creating some resources when the creation of the
        # deployment itself fails. In such cases, we would have resource leak as the
        # existence of deployment is how the controller knows it has something to
        # manage.
        await _kubectl(
            [
                "apply",
                "--dry-run=server",
                "-k",
                str(tmp_path),
            ]
        )
        await _kubectl(
            [
                "apply",
                "-k",
                str(tmp_path),
                "--wait=false",
            ]
        )


async def delete_resources(build_name: str) -> None:
    # TODO delete all resources with runboat/build label
    await _kubectl(
        [
            "-n",
            settings.build_namespace,
            "delete",
            "configmap,deployment,ingress,job,secret,service,pvc",
            "-l",
            f"runboat/build={build_name}",
            "--wait=false",
        ]
    )


@sync_to_async
def kill_job(build_name: str, job_kind: DeploymentMode) -> None:
    # TODO delete all resources with runboat/build and runboat/job-kind label
    batchv1 = client.BatchV1Api()
    batchv1.delete_collection_namespaced_job(
        namespace=settings.build_namespace,
        label_selector=f"runboat/build={build_name},runboat/job-kind={job_kind}",
        grace_period_seconds=0,
    )
    corev1 = client.CoreV1Api()
    corev1.delete_collection_namespaced_pod(
        namespace=settings.build_namespace,
        label_selector=f"runboat/build={build_name},runboat/job-kind={job_kind}",
        grace_period_seconds=0,
    )


@sync_to_async
def log(build_name: str, job_kind: DeploymentMode | None) -> str | None:
    """Return the build log.

    The pod for which the log is returned is the first that matches the
    build_name (via its runboat/build label) and job_kind (via its
    runboat/job-kind label).
    """
    corev1 = client.CoreV1Api()
    pods = corev1.list_namespaced_pod(
        namespace=settings.build_namespace, label_selector=f"runboat/build={build_name}"
    ).items
    for pod in pods:
        if pod.metadata.labels.get("runboat/job-kind") == job_kind:
            break
    else:
        # no matching pod found
        return None
    return cast(
        str,
        corev1.read_namespaced_pod_log(
            pod.metadata.name,
            namespace=settings.build_namespace,
            container=pod.metadata.annotations.get(
                "kubectl.kubernetes.io/default-container"
            ),
            tail_lines=None if job_kind else None,
            follow=False,
        ),
    )
