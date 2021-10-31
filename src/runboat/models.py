import datetime
import logging
import uuid
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
    stopped = "stopped"  # initialization succeeded and 0 replicas
    starting = "starting"  # to initialize or initializing or scaling up
    started = "started"  # running
    failed = "failed"  # initialization failed
    cleaning = "cleaning"  # cleaning up, will be undeployed soon


class BuildInitStatus(str, Enum):
    todo = "todo"  # to initialize as soon as there is capacity
    started = "started"  # initialization job running
    succeeded = "succeeded"  # initialization job succeeded
    failed = "failed"  # initialization job failed
    cleaning = "cleaning"  # cleanup job running


class Build(BaseModel):
    name: str
    deployment_name: str
    repo: str
    target_branch: str
    pr: Optional[int]
    git_commit: str
    image: str
    status: BuildStatus
    init_status: BuildInitStatus
    last_scaled: datetime.datetime
    created: datetime.datetime

    def __str__(self) -> str:
        return f"{self.slug} ({self.name})"

    @classmethod
    async def from_name(cls, build_name: str) -> Optional["Build"]:
        """Create a Build model by reading the k8s api."""
        deployment = await k8s.read_deployment(build_name)
        if deployment is None:
            return None
        return cls.from_deployment(deployment)

    @classmethod
    def from_deployment(cls, deployment: V1Deployment) -> "Build":
        return Build(
            name=deployment.metadata.labels["runboat/build"],
            deployment_name=deployment.metadata.name,
            repo=deployment.metadata.annotations["runboat/repo"],
            target_branch=deployment.metadata.annotations["runboat/target-branch"],
            pr=deployment.metadata.annotations["runboat/pr"] or None,
            git_commit=deployment.metadata.annotations["runboat/git-commit"],
            image=deployment.spec.template.spec.containers[0].image,
            init_status=deployment.metadata.annotations["runboat/init-status"],
            status=cls._status_from_deployment(deployment),
            last_scaled=deployment.metadata.annotations.get("runboat/last-scaled")
            or datetime.datetime.utcnow(),
            created=deployment.metadata.creation_timestamp,
        )

    @classmethod
    def _status_from_deployment(cls, deployment: V1Deployment) -> BuildStatus:
        init_status = deployment.metadata.annotations["runboat/init-status"]
        if init_status in (BuildInitStatus.todo, BuildInitStatus.started):
            return BuildStatus.starting
        elif init_status == BuildInitStatus.cleaning:
            return BuildStatus.cleaning
        elif init_status == BuildInitStatus.failed:
            return BuildStatus.failed
        elif init_status == BuildInitStatus.succeeded:
            replicas = deployment.status.replicas
            if not replicas:
                return BuildStatus.stopped
            else:
                if deployment.status.ready_replicas == replicas:
                    return BuildStatus.started
                else:
                    return BuildStatus.starting
        raise RuntimeError(f"Could not compute status of {deployment.metadata.name}.")

    @classmethod
    def make_slug(
        cls, repo: str, target_branch: str, pr: int | None, git_commit: str
    ) -> str:
        slug = f"{slugify(repo)}-{slugify(target_branch)}"
        if pr:
            slug = f"{slug}-pr{slugify(pr)}"
        slug = f"{slug}-{git_commit[:12]}"
        return slug

    @property
    def slug(self) -> str:
        return self.make_slug(self.repo, self.target_branch, self.pr, self.git_commit)

    @property
    def link(self) -> str:
        return f"http://{self.slug}.{settings.build_domain}"

    @classmethod
    async def deploy(
        cls, repo: str, target_branch: str, pr: int | None, git_commit: str
    ) -> None:
        """Deploy a build, without starting it."""
        name = f"b{uuid.uuid4()}"
        slug = cls.make_slug(repo, target_branch, pr, git_commit)
        _logger.info(f"Deploying {slug} ({name}).")
        image = get_build_image(target_branch)
        deployment_vars = k8s.make_deployment_vars(
            k8s.DeploymentMode.deploy,
            name,
            slug,
            repo.lower(),
            target_branch,
            pr,
            git_commit,
            image,
        )
        await k8s.deploy(deployment_vars)

    async def start(self) -> None:
        """Start build if init succeeded, or reinitialize if failed."""
        if self.status in (BuildStatus.started, BuildStatus.starting):
            _logger.info(
                f"Ignoring start command for {self} "
                "that is already started or starting."
            )
            return
        elif self.status == BuildStatus.failed:
            _logger.info(f"Marking failed {self} for reinitialization.")
            await k8s.delete_job(self.name, job_kind="initialize")
            await self._patch(
                init_status=BuildInitStatus.todo, replicas=0, update_last_scaled=False
            )
        elif self.status == BuildStatus.stopped:
            _logger.info(f"Starting {self}.")
            await self._patch(replicas=1, update_last_scaled=True)

    async def stop(self) -> None:
        if self.status == BuildStatus.started:
            _logger.info(f"Stopping {self}.")
            await self._patch(replicas=0, update_last_scaled=True)
        else:
            _logger.info("Ignoring stop command for {self} " "that is not started.")

    async def initialize(self) -> None:
        # Start initizalization job. on_init_started/on_init_succeeded/on_init_failed
        # will be callsed back when it starts/succeeds/fails.
        _logger.info(f"Deploying initialize job for {self}.")
        deployment_vars = k8s.make_deployment_vars(
            k8s.DeploymentMode.initialize,
            self.name,
            self.slug,
            self.repo,
            self.target_branch,
            self.pr,
            self.git_commit,
            self.image,
        )
        await k8s.deploy(deployment_vars)

    async def undeploy(self) -> None:
        """Undeploy a build."""
        await self.stop()
        # Start cleanup job. on_cleanup_XXX callbacks will follow.
        _logger.info(f"Deploying cleanup job for {self}.")
        deployment_vars = k8s.make_deployment_vars(
            k8s.DeploymentMode.cleanup,
            self.name,
            self.slug,
            self.repo,
            self.target_branch,
            self.pr,
            self.git_commit,
            self.image,
        )
        await k8s.deploy(deployment_vars)

    async def on_initialize_started(self) -> None:
        if self.init_status == BuildInitStatus.started:
            return
        _logger.info(f"Initialization job started for {self}.")
        await self._patch(
            init_status=BuildInitStatus.started, replicas=0, update_last_scaled=True
        )

    async def on_initialize_succeeded(self) -> None:
        if self.init_status == BuildInitStatus.succeeded:
            # Avoid restarting stopped deployments when the controller is notified of
            # succeeded old initialization jobs after a controller restart.
            return
        _logger.info(f"Initialization job succeded for {self}, starting.")
        await self._patch(
            init_status=BuildInitStatus.succeeded, replicas=1, update_last_scaled=True
        )

    async def on_initialize_failed(self) -> None:
        if self.init_status == BuildInitStatus.failed:
            # Already marked as failed. We are probably here because the controller is
            # restarting, and is notified of existing initialization jobs.
            return
        _logger.info(f"Initialization job failed for {self}.")
        await self._patch(
            init_status=BuildInitStatus.failed, replicas=0, update_last_scaled=True
        )

    async def on_cleanup_started(self) -> None:
        _logger.info(f"Cleanup job started for {self}.")
        await self._patch(
            init_status=BuildInitStatus.cleaning, replicas=0, update_last_scaled=False
        )

    async def on_cleanup_succeeded(self) -> None:
        _logger.info(f"Cleanup job succeeded for {self}, deleting resources.")
        await k8s.delete_resources(self.name)

    async def on_cleanup_failed(self) -> None:
        _logger.error(
            f"Cleanup job failed for {self}, " f"manual intervention required."
        )

    async def _patch(
        self,
        init_status: BuildInitStatus | None = None,
        replicas: int | None = None,
        update_last_scaled: bool = True,
    ) -> None:
        ops = []
        if init_status is not None:
            ops.extend(
                [
                    {
                        "op": "replace",
                        "path": "/metadata/annotations/runboat~1init-status",
                        "value": init_status,
                    },
                ],
            )
        if replicas is not None:
            ops.append(
                {
                    "op": "replace",
                    "path": "/spec/replicas",
                    "value": replicas,
                },
            )
            if update_last_scaled:
                ops.append(
                    {
                        "op": "replace",
                        "path": "/metadata/annotations/runboat~1last-scaled",
                        "value": datetime.datetime.utcnow().isoformat() + "Z",
                    },
                )
        await k8s.patch_deployment(self.deployment_name, ops)


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
