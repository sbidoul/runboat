import asyncio
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Any, AsyncGenerator, Generator, Optional

from jinja2 import Template
from kubernetes_asyncio import client, config, watch
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.models.v1_deployment import V1Deployment
from pydantic import BaseModel

from .settings import settings


def _split_image_name_tag(img: str) -> tuple[str, str]:
    if ":" in img:
        return img.split(":", 2)
    return (img, "latest")


async def load_kube_config() -> None:
    await config.load_kube_config()


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


class DeploymentVars(BaseModel):
    namespace: str
    build_name: str
    repo: str
    target_branch: str
    pr: Optional[int]
    commit: str
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
    build_name: str,
    slug: str,
    repo: str,
    target_branch: str,
    pr: int | None,
    commit: str,
    image: str,
) -> DeploymentVars:
    image_name, image_tag = _split_image_name_tag(image)
    return DeploymentVars(
        namespace=settings.build_namespace,
        build_name=build_name,
        repo=repo,
        target_branch=target_branch,
        pr=pr,
        commit=commit,
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
                "-k",
                str(tmp_path),
            ]
        )


async def dropdb(build_name: str) -> None:
    await _kubectl(
        [
            "-n",
            settings.build_namespace,
            "run",
            f"dropdb-{build_name}",
            "--restart=Never",
            "--rm",
            "-i",
            "--tty",
            "--image",
            "postgres",
            "--env",
            f"PGHOST={settings.build_pghost}",
            "--env",
            f"PGPORT={settings.build_pgport}",
            "--env",
            f"PGUSER={settings.build_pguser}",
            "--env",
            f"PGPASSWORD={settings.build_pgpassword}",
            "--",
            "dropdb",
            "--if-exists",
            "--force",  # pg 13+
            build_name,
        ]
    )


async def undeploy(build_name: str) -> None:
    await _kubectl(
        [
            "-n",
            settings.build_namespace,
            "delete",
            "service,deployment,ingress,secret,configmap",
            "-l",
            f"runboat/build={build_name}",
            "--wait=false",
        ]
    )
