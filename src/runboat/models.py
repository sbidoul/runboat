import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from kubernetes_asyncio.client.models.v1_deployment import V1Deployment
from pydantic import BaseModel

from . import k8s
from .build_images import get_build_image
from .settings import settings
from .utils import slugify

_logger = logging.getLogger(__name__)


class BuildStatus(str, Enum):
    stopped = "stopped"
    starting = "starting"
    started = "started"


class BuildTodo(str, Enum):
    start = "start"


class Build(BaseModel):
    name: str
    deployment_name: str
    repo: str
    target_branch: str
    pr: Optional[int]
    commit: str
    image: str
    status: BuildStatus
    todo: Optional[BuildTodo]
    last_scaled: Optional[str]
    created: str

    @classmethod
    def from_deployment(cls, deployment: V1Deployment) -> "Build":
        return Build(
            name=deployment.metadata.labels["runboat/build"],
            deployment_name=deployment.metadata.name,
            repo=deployment.metadata.annotations["runboat/repo"],
            target_branch=deployment.metadata.annotations["runboat/target-branch"],
            pr=deployment.metadata.annotations["runboat/pr"] or None,
            commit=deployment.metadata.annotations["runboat/commit"],
            image=deployment.spec.template.spec.containers[0].image,
            status=cls._status_from_deployment(deployment),
            todo=deployment.metadata.annotations["runboat/todo"] or None,
            last_scaled=deployment.metadata.annotations.get("runboat/last-scaled")
            or None,
            created="TODO",  # deployment.metadata.creationTimestamp,
        )

    @classmethod
    def _status_from_deployment(cls, deployment: V1Deployment) -> BuildStatus:
        replicas = deployment.status.replicas
        if not replicas:
            status = BuildStatus.stopped
        else:
            if deployment.status.ready_replicas == replicas:
                status = BuildStatus.started
            else:
                status = BuildStatus.starting
        # TODO detect stopping, deploying, undeploying ?
        # TODO: failed status
        return status

    @classmethod
    def make_slug(
        cls, repo: str, target_branch: str, pr: int | None, commit: str
    ) -> str:
        slug = f"{slugify(repo)}-{slugify(target_branch)}"
        if pr:
            slug = f"{slug}-pr{slugify(pr)}"
        slug = f"{slug}-{commit[:12]}"
        return slug

    @property
    def slug(self) -> str:
        return self.make_slug(self.repo, self.target_branch, self.pr, self.commit)

    @property
    def link(self) -> str:
        return f"http://{self.slug}.{settings.build_domain}"

    async def delay_start(self) -> None:
        """Mark a build for startup.

        This is done by setting the runboat/todo annotation to 'start'.
        This will in turn let the starter process it when there is
        available capacity.
        """
        await k8s.patch_deployment(
            self.deployment_name,
            [
                {
                    "op": "replace",
                    "path": "/metadata/annotations/runboat~1todo",
                    "value": "start",
                },
            ],
        )

    async def scale(self, replicas: int) -> None:
        """Start a build.

        Set replicas to 1, and reset todo.
        """
        _logger.info(f"Scaling {self.slug} ({self.name}) to {replicas}.")
        await k8s.patch_deployment(
            self.deployment_name,
            [
                {
                    # clear todo
                    "op": "replace",
                    "path": "/metadata/annotations/runboat~1todo",
                    "value": "",
                },
                {
                    # record last scaled time for the stopper and undeployer
                    "op": "replace",
                    "path": "/metadata/annotations/runboat~1last-scaled",
                    "value": datetime.utcnow().isoformat() + "Z",
                },
                {
                    # set replicas
                    "op": "replace",
                    "path": "/spec/replicas",
                    "value": replicas,
                },
            ],
        )

    async def undeploy(self) -> None:
        """Undeploy a build.

        Delete all resources, and drop the database.
        """
        _logger.info(f"Undeploying {self.slug} ({self.name})")
        await k8s.undeploy(self.name)
        await k8s.dropdb(self.name)

    @classmethod
    async def deploy(
        cls, repo: str, target_branch: str, pr: int | None, commit: str
    ) -> None:
        """Deploy a build, without starting it."""
        name = str(uuid.uuid4())
        slug = cls.make_slug(repo, target_branch, pr, commit)
        _logger.info(f"Deploying {slug} ({name})")
        image = get_build_image(target_branch)
        deployment_vars = k8s.make_deployment_vars(
            name,
            slug,
            repo.lower(),
            target_branch,
            pr,
            commit,
            image,
        )
        await k8s.deploy(deployment_vars)


class Repo(BaseModel):
    name: str

    @property
    def link(self) -> str:
        return f"https://github.com/{self.name}"

    class Config:
        read_with_orm_mode = True


class BranchOrPull(BaseModel):
    repo: str
    target_branch: str
    pr: Optional[int]
    builds: list[Build]

    class Config:
        read_with_orm_mode = True

    @property
    def link(self) -> str:
        link = f"https://github.com/{self.repo}"
        if self.pr:
            link = f"{link}/pull/{self.pr}"
        else:
            link = f"{link}/tree/{self.target_branch}"
        return link
