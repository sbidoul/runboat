import asyncio
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from enum import Enum
from importlib import resources
from pathlib import Path
from typing import Any, AsyncGenerator, Generator, Optional

from jinja2 import Template
from kubernetes_asyncio import client, config, watch
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.models.v1_deployment import V1Deployment
from kubernetes_asyncio.client.models.v1_job import V1Job
from pydantic import BaseModel

from .settings import settings


def _split_image_name_tag(img: str) -> tuple[str, str]:
    if ":" in img:
        return img.split(":", 2)
    return (img, "latest")


async def load_kube_config() -> None:
    await config.load_kube_config()


async def read_deployment(name: str) -> Optional[V1Deployment]:
    async with ApiClient() as api:
        appsv1 = client.AppsV1Api(api)
        ret = await appsv1.list_namespaced_deployment(
            namespace=settings.build_namespace, label_selector=f"runboat/build={name}"
        )
        for item in ret.items:
            return item  # return first
        return None  # None found


async def patch_deployment(deployment_name: str, ops: list[dict["str", Any]]) -> None:
    async with ApiClient() as api:
        appsv1 = client.AppsV1Api(api)
        await appsv1.patch_namespaced_deployment(
            name=deployment_name,
            namespace=settings.build_namespace,
            body=ops,
        )


async def watch_deployments() -> AsyncGenerator[tuple[str, V1Deployment], None]:
    w = watch.Watch()
    # use the context manager to close http sessions automatically
    async with ApiClient() as api:
        appsv1 = client.AppsV1Api(api)
        async for event in w.stream(
            appsv1.list_namespaced_deployment, namespace=settings.build_namespace
        ):
            yield event["type"], event["object"]


async def watch_jobs() -> AsyncGenerator[tuple[str, V1Job], None]:
    w = watch.Watch()
    # use the context manager to close http sessions automatically
    async with ApiClient() as api:
        appsv1 = client.BatchV1Api(api)
        async for event in w.stream(
            appsv1.list_namespaced_job, namespace=settings.build_namespace
        ):
            yield event["type"], event["object"]


class DeploymentMode(str, Enum):
    deploy = "deploy"
    initialize = "initialize"
    cleanup = "cleanup"


class DeploymentVars(BaseModel):
    namespace: str
    mode: str
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
    proc = await asyncio.create_subprocess_exec("kubectl", *args)
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


async def delete_job(build_name: str, job_kind: str) -> None:
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
