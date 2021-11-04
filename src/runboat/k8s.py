import asyncio
import logging
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from enum import Enum
from importlib import resources
from pathlib import Path
from typing import Any, Generator, Optional

import urllib3
from jinja2 import Template
from kubernetes import client, config, watch
from kubernetes.client.exceptions import ApiException
from kubernetes.client.models.v1_deployment import V1Deployment
from pydantic import BaseModel

from .settings import settings
from .utils import sync_to_async, sync_to_async_iterator

_logger = logging.getLogger(__name__)


def _split_image_name_tag(img: str) -> tuple[str, str]:
    if ":" in img:
        return img.split(":", 2)
    return (img, "latest")


@sync_to_async
def load_kube_config() -> None:
    config.load_kube_config()


@sync_to_async
def read_deployment(name: str) -> Optional[V1Deployment]:
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


@sync_to_async
def patch_deployment(
    deployment_name: str, ops: list[dict["str", Any]], not_found_ok: bool
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


def _watch(list_method, *args, **kwargs):
    while True:
        try:
            # perform a first query
            res = list_method(*args, **kwargs)
            resource_version = res.metadata.resource_version
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
                        if event["type"] == "ERROR":
                            raise RuntimeError("Kubernetes watch error")
                        resource_version = event["object"].metadata.resource_version
                        yield event["type"], event["object"]
                except urllib3.exceptions.TimeoutError:
                    continue
                except TimeoutError:
                    continue
        except Exception as e:
            delay = 5
            _logger.info(
                f"Error {e} watching {list_method.__name__}. Retrying in {delay} sec."
            )
            time.sleep(delay)
            continue


@sync_to_async_iterator
def watch_deployments():
    appsv1 = client.AppsV1Api()
    yield from _watch(
        appsv1.list_namespaced_deployment, namespace=settings.build_namespace
    )


@sync_to_async_iterator
def watch_jobs():
    batchv1 = client.BatchV1Api()
    yield from _watch(batchv1.list_namespaced_job, namespace=settings.build_namespace)


class DeploymentMode(str, Enum):
    deploy = "deploy"
    initialize = "initialize"
    cleanup = "cleanup"


class DeploymentVars(BaseModel):
    namespace: str
    mode: DeploymentMode
    build_name: str
    repo: str
    target_branch: str
    pr: Optional[int]
    git_commit: str
    image_name: str
    image_tag: str
    pghost: str
    pgport: str
    pguser: str
    pgpassword: str
    pgdatabase: str
    admin_passwd: str
    hostname: str


def make_deployment_vars(
    mode: DeploymentMode,
    build_name: str,
    slug: str,
    repo: str,
    target_branch: str,
    pr: int | None,
    git_commit: str,
    image: str,
) -> DeploymentVars:
    image_name, image_tag = _split_image_name_tag(image)
    return DeploymentVars(
        mode=mode,
        namespace=settings.build_namespace,
        build_name=build_name,
        repo=repo,
        target_branch=target_branch,
        pr=pr,
        git_commit=git_commit,
        image_name=image_name,
        image_tag=image_tag,
        pghost=settings.build_pghost,
        pgport=settings.build_pgport,
        pguser=settings.build_pguser,
        pgpassword=settings.build_pgpassword,
        pgdatabase=build_name,
        admin_passwd=settings.build_admin_passwd,
        hostname=f"{slug}.{settings.build_domain}",
    )


@contextmanager
def _render_kubefiles(deployment_vars: DeploymentVars) -> Generator[Path, None, None]:
    with resources.path(
        __package__, "kubefiles"
    ) as kubefiles_path, tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        # TODO async copytree
        shutil.copytree(kubefiles_path, tmp_path, dirs_exist_ok=True)
        template = Template((tmp_path / "kustomization.yaml.jinja").read_text())
        (tmp_path / "kustomization.yaml").write_text(
            template.render(dict(deployment_vars))
        )
        yield tmp_path


async def _kubectl(args: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        "kubectl", *args, stdout=subprocess.DEVNULL
    )
    return_code = await proc.wait()
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, ["kubectl"] + args)


async def deploy(deployment_vars: DeploymentVars) -> None:
    with _render_kubefiles(deployment_vars) as tmp_path:
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
    await _kubectl(
        [
            "-n",
            settings.build_namespace,
            "delete",
            "configmap,deployment,ingress,job,secret,service",
            "-l",
            f"runboat/build={build_name}",
            "--wait=false",
        ]
    )


async def delete_job(build_name: str, job_kind: DeploymentMode) -> None:
    await _kubectl(
        [
            "-n",
            settings.build_namespace,
            "delete",
            "job",
            "-l",
            f"runboat/build={build_name},runboat/job-kind={job_kind}",
            "--wait=false",
        ]
    )
