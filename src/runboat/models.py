import datetime
import logging
import uuid
from enum import Enum
from typing import Optional

from kubernetes.client.models.v1_deployment import V1Deployment
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
    undeploying = "undeploying"  # undeploying, will be deleted after cleanup


class BuildInitStatus(str, Enum):
    todo = "todo"  # to initialize and start as soon as there is capacity
    started = "started"  # initialization job running
    succeeded = "succeeded"  # initialization job succeeded
    failed = "failed"  # initialization job failed


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
    desired_replicas: int
    last_scaled: datetime.datetime
    created: datetime.datetime

    class Config:
        read_with_orm_mode = True

    def __str__(self) -> str:
        return f"{self.slug} ({self.name})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Build):
            return False
        if self.name != other.name:
            return False
        # Ignore fields that are immutable by design.
        return (
            self.status == other.status
            and self.init_status == other.init_status
            and self.desired_replicas == other.desired_replicas
            and self.last_scaled == other.last_scaled
        )

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
            desired_replicas=deployment.spec.replicas or 0,
            last_scaled=deployment.metadata.annotations.get("runboat/last-scaled")
            or deployment.metadata.creation_timestamp,
            created=deployment.metadata.creation_timestamp,
        )

    @classmethod
    def _status_from_deployment(cls, deployment: V1Deployment) -> BuildStatus:
        if deployment.metadata.deletion_timestamp:
            return BuildStatus.undeploying
        init_status = deployment.metadata.annotations["runboat/init-status"]
        if init_status in (BuildInitStatus.todo, BuildInitStatus.started):
            return BuildStatus.starting
        elif init_status == BuildInitStatus.failed:
            return BuildStatus.failed
        elif init_status == BuildInitStatus.succeeded:
            replicas = deployment.spec.replicas
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
        elif self.status == BuildStatus.undeploying:
            _logger.info(f"Ignoring start command for {self} that is undeploying.")
            return
        elif self.status == BuildStatus.failed:
            _logger.info(f"Marking failed {self} for reinitialization.")
            await k8s.delete_job(self.name, job_kind=k8s.DeploymentMode.initialize)
            await self._patch(init_status=BuildInitStatus.todo, desired_replicas=0)
        elif self.status == BuildStatus.stopped:
            _logger.info(f"Starting {self} that was last scaled on {self.last_scaled}.")
            await self._patch(desired_replicas=1)

    async def stop(self) -> None:
        if self.status == BuildStatus.started:
            _logger.info(f"Stopping {self} that was last scaled on {self.last_scaled}.")
            await self._patch(desired_replicas=0)
        else:
            _logger.info(f"Ignoring stop command for {self} that is not started.")

    async def undeploy(self) -> None:
        # To undeploy, we delete the deployment. Due to the finalizer, the deletion
        # will not be immediate, but the controller will notice the deletionTimestamp
        # and launch the cleanup job. When the cleanup job succeeds, the controller
        # removes all resources, and also removes the finalizer which allows kubernetes
        # to remove the deployment.
        await k8s.delete_deployment(self.deployment_name)

    async def initialize(self) -> None:
        """Launch the initialization job."""
        # Start initizalization job. on_initialize_{started,succeeded,failed} callbacks
        # will follow from job events.
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

    async def cleanup(self) -> None:
        """Launch the clenaup job."""
        # Delete the initialization job to reduce conflict with the cleanup job.
        await k8s.delete_job(self.name, job_kind=k8s.DeploymentMode.initialize)
        # Be sure the deployment is stopped.
        await self._patch(desired_replicas=0, not_found_ok=True)
        # Start cleanup job. on_cleanup_{started,succeeded,failed} callbacks will follow
        # from job events.
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
        await self._patch(init_status=BuildInitStatus.started, desired_replicas=0)

    async def on_initialize_succeeded(self) -> None:
        if self.init_status == BuildInitStatus.succeeded:
            # Avoid restarting stopped deployments when the controller is notified of
            # succeeded old initialization jobs after a controller restart.
            return
        _logger.info(f"Initialization job succeded for {self}, starting.")
        await self._patch(init_status=BuildInitStatus.succeeded, desired_replicas=1)

    async def on_initialize_failed(self) -> None:
        if self.init_status == BuildInitStatus.failed:
            # Already marked as failed. We are probably here because the controller is
            # restarting, and is notified of existing initialization jobs.
            return
        _logger.info(f"Initialization job failed for {self}.")
        await self._patch(init_status=BuildInitStatus.failed, desired_replicas=0)

    async def on_cleanup_started(self) -> None:
        _logger.info(f"Cleanup job started for {self}.")

    async def on_cleanup_succeeded(self) -> None:
        _logger.info(f"Cleanup job succeeded for {self}, deleting resources.")
        await k8s.delete_resources(self.name)
        _logger.debug("Removing finalizer for %s.", self)
        await self._patch(remove_finalizers=True, not_found_ok=True)

    async def on_cleanup_failed(self) -> None:
        _logger.error(f"Cleanup job failed for {self}, manual intervention required.")

    async def _patch(
        self,
        init_status: BuildInitStatus | None = None,
        desired_replicas: int | None = None,
        remove_finalizers: bool = False,
        not_found_ok: bool = False,
    ) -> None:
        ops = []
        if init_status is not None and init_status != self.init_status:
            ops.extend(
                [
                    {
                        "op": "replace",
                        "path": "/metadata/annotations/runboat~1init-status",
                        "value": init_status,
                    },
                ],
            )
        if desired_replicas is not None and desired_replicas != self.desired_replicas:
            ops.extend(
                [
                    {
                        "op": "replace",
                        "path": "/spec/replicas",
                        "value": desired_replicas,
                    },
                    {
                        "op": "replace",
                        "path": "/metadata/annotations/runboat~1last-scaled",
                        "value": datetime.datetime.utcnow()
                        .replace(microsecond=0)
                        .isoformat()
                        + "Z",
                    },
                ]
            )
        if remove_finalizers:
            ops.append(
                {
                    "op": "remove",
                    "path": "/metadata/finalizers",
                }
            )
        await k8s.patch_deployment(self.deployment_name, ops, not_found_ok)


class Repo(BaseModel):
    name: str

    @property
    def link(self) -> str:
        return f"https://github.com/{self.name}"

    class Config:
        read_with_orm_mode = True
