import datetime
import logging
import uuid
from enum import Enum
from typing import Optional

from kubernetes.client.models.v1_deployment import V1Deployment
from pydantic import BaseModel, ConfigDict

from . import github, k8s
from .github import CommitInfo, GitHubStatusState
from .settings import settings
from .utils import slugify

_logger = logging.getLogger(__name__)


class BuildEvent(str, Enum):
    modified = "upd"
    removed = "del"


class BuildStatus(str, Enum):
    stopped = "stopped"  # initialization succeeded and 0 replicas
    stopping = "stopping"  # 0 desired replicas but some are still running
    initializing = "initializing"  # to initialize or initializing
    starting = "starting"  # scaling up
    started = "started"  # running
    failed = "failed"  # initialization failed
    undeploying = "undeploying"  # undeploying, will be deleted after cleanup


class BuildInitStatus(str, Enum):
    todo = "todo"  # to initialize and start as soon as there is capacity
    started = "started"  # initialization job running
    succeeded = "succeeded"  # initialization job succeeded
    failed = "failed"  # initialization job failed


class Build(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    deployment_name: str
    commit_info: CommitInfo
    status: BuildStatus
    init_status: BuildInitStatus
    desired_replicas: int
    last_scaled: datetime.datetime
    created: datetime.datetime

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
            commit_info=CommitInfo(
                repo=deployment.metadata.annotations["runboat/repo"],
                target_branch=deployment.metadata.annotations["runboat/target-branch"],
                pr=deployment.metadata.annotations.get("runboat/pr") or None,
                git_commit=deployment.metadata.annotations["runboat/git-commit"],
            ),
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
            return BuildStatus.initializing
        elif init_status == BuildInitStatus.failed:
            return BuildStatus.failed
        elif init_status == BuildInitStatus.succeeded:
            replicas = deployment.spec.replicas
            if not replicas:
                if deployment.status.replicas:
                    return BuildStatus.stopping
                else:
                    return BuildStatus.stopped
            else:
                if deployment.status.available_replicas == replicas:
                    return BuildStatus.started
                else:
                    return BuildStatus.starting
        raise RuntimeError(f"Could not compute status of {deployment.metadata.name}.")

    @classmethod
    def make_slug(
        cls,
        commit_info: CommitInfo,
    ) -> str:
        slug = f"{slugify(commit_info.repo)}-{slugify(commit_info.target_branch)}"
        if commit_info.pr:
            slug = f"{slug}-pr{slugify(commit_info.pr)}"
        slug = f"{slug}-{commit_info.git_commit[:12]}"
        return slug

    @property
    def slug(self) -> str:
        return self.make_slug(self.commit_info)

    @property
    def deploy_link(self) -> str:
        return f"http://{self.slug}.{settings.build_domain}"

    @property
    def deploy_link_mailhog(self) -> str:
        return f"http://{self.slug}.mail.{settings.build_domain}"

    @property
    def repo_target_branch_link(self) -> str:
        return (
            f"https://github.com/{self.commit_info.repo}"
            f"/tree/{self.commit_info.target_branch}"
        )

    @property
    def repo_pr_link(self) -> str | None:
        if not self.commit_info.pr:
            return None
        return f"https://github.com/{self.commit_info.repo}/pull/{self.commit_info.pr}"

    @property
    def repo_commit_link(self) -> str:
        link = f"https://github.com/{self.commit_info.repo}"
        if self.commit_info.pr:
            return (
                f"{link}/pull/{self.commit_info.pr}"
                f"/commits/{self.commit_info.git_commit}"
            )
        else:
            return f"{link}/commit/{self.commit_info.git_commit}"

    @property
    def webui_link(self) -> str:
        return f"{settings.base_url}/builds/{self.name}"

    @property
    def live_link(self) -> str:
        return f"{self.webui_link}?live"

    async def init_log(self) -> str | None:
        return await k8s.log(self.name, job_kind=k8s.DeploymentMode.initialize)

    async def log(self) -> str | None:
        return await k8s.log(self.name, job_kind=None)

    @classmethod
    async def _deploy(
        cls, commit_info: CommitInfo, name: str, slug: str, job_kind: k8s.DeploymentMode
    ) -> None:
        """Internal method to prepare for and handle a k8s.deploy()."""
        build_settings = settings.get_build_settings(
            commit_info.repo, commit_info.target_branch
        )[0]
        kubefiles_path = (
            build_settings.kubefiles_path or settings.build_default_kubefiles_path
        )
        deployment_vars = k8s.make_deployment_vars(
            job_kind,
            name,
            slug,
            commit_info,
            build_settings,
        )
        await k8s.deploy(kubefiles_path, deployment_vars)
        await github.notify_status(
            commit_info.repo,
            commit_info.git_commit,
            GitHubStatusState.pending,
            target_url=None,
        )

    @classmethod
    async def deploy(cls, commit_info: CommitInfo) -> None:
        """Deploy a build, without starting it."""
        name = f"b{uuid.uuid4()}"
        slug = cls.make_slug(commit_info)
        _logger.info(f"Deploying {slug} ({name}).")
        await cls._deploy(
            commit_info, name, slug, job_kind=k8s.DeploymentMode.deployment
        )

    async def start(self) -> None:
        """Start build if init succeeded, or reinitialize if failed."""
        if self.status not in (BuildStatus.stopped, BuildStatus.stopping):
            _logger.info(f"Ignoring start command for {self} that is {self.status}.")
            return
        _logger.info(f"Starting {self} that was last scaled on {self.last_scaled}.")
        await self._patch(desired_replicas=1)

    async def stop(self) -> None:
        if self.status != BuildStatus.started:
            _logger.info(f"Ignoring stop command for {self} that is {self.status}.")
            return
        _logger.info(f"Stopping {self} that was last scaled on {self.last_scaled}.")
        await self._patch(desired_replicas=0)

    async def undeploy(self) -> None:
        # To undeploy, we delete the deployment. Due to the finalizer, the deletion
        # will not be immediate, but the controller will notice the deletionTimestamp
        # and launch the cleanup job. When the cleanup job succeeds, the controller
        # removes all resources, and also removes the finalizer which allows kubernetes
        # to remove the deployment.
        await k8s.delete_deployment(self.deployment_name)

    async def redeploy(self) -> None:
        """Redeploy a build, to reinitialize it."""
        _logger.info(f"Redeploying {self}.")
        await k8s.kill_job(self.name, job_kind=k8s.DeploymentMode.cleanup)
        await k8s.kill_job(self.name, job_kind=k8s.DeploymentMode.initialize)
        await self._deploy(
            self.commit_info,
            self.name,
            self.slug,
            job_kind=k8s.DeploymentMode.deployment,
        )

    async def initialize(self) -> None:
        """Launch the initialization job."""
        # Start initialization job. on_initialize_{started,succeeded,failed} callbacks
        # will follow from job events.
        _logger.info(f"Deploying initialize job for {self}.")
        await self._deploy(
            self.commit_info,
            self.name,
            self.slug,
            job_kind=k8s.DeploymentMode.initialize,
        )

    async def _delete_deployment_resources(self) -> None:
        await k8s.delete_deployment_resources(self.name)
        _logger.debug("Removing finalizer for %s.", self)
        await self._patch(remove_finalizers=True, not_found_ok=True)

    async def cleanup(self) -> None:
        """Launch the cleanup job."""
        if settings.no_cleanup_job:
            await self._delete_deployment_resources()
            return
        # Kill the initialization job to reduce conflict with the cleanup job, such as
        # the database being created by the initialization after the cleanup job has
        # completed.
        await k8s.kill_job(self.name, job_kind=k8s.DeploymentMode.initialize)
        # Be sure the deployment is stopped.
        await self._patch(desired_replicas=0, not_found_ok=True)
        # Start cleanup job. on_cleanup_{started,succeeded,failed} callbacks will follow
        # from job events.
        _logger.info(f"Deploying cleanup job for {self}.")
        await self._deploy(
            self.commit_info, self.name, self.slug, job_kind=k8s.DeploymentMode.cleanup
        )

    async def on_initialize_started(self) -> None:
        if self.init_status == BuildInitStatus.started:
            return
        _logger.info(f"Initialization job started for {self}.")
        if await self._patch(init_status=BuildInitStatus.started, desired_replicas=0):
            await github.notify_status(
                self.commit_info.repo,
                self.commit_info.git_commit,
                GitHubStatusState.pending,
                target_url=self.live_link,
            )

    async def on_initialize_succeeded(self) -> None:
        if self.init_status == BuildInitStatus.succeeded:
            # Already marked as succeeded. We are probably here because the controller
            # is restarting, and is notified of existing initialization jobs.
            return
        _logger.info(f"Initialization job succeded for {self}, ready to start.")
        if await self._patch(init_status=BuildInitStatus.succeeded):
            await github.notify_status(
                self.commit_info.repo,
                self.commit_info.git_commit,
                GitHubStatusState.success,
                target_url=self.live_link,
            )

    async def on_initialize_failed(self) -> None:
        if self.init_status == BuildInitStatus.failed:
            # Already marked as failed. We are probably here because the controller is
            # restarting, and is notified of existing initialization jobs.
            return
        _logger.info(f"Initialization job failed for {self}.")
        if await self._patch(init_status=BuildInitStatus.failed, desired_replicas=0):
            await github.notify_status(
                self.commit_info.repo,
                self.commit_info.git_commit,
                GitHubStatusState.failure,
                target_url=self.live_link,
            )

    async def on_cleanup_started(self) -> None:
        _logger.info(f"Cleanup job started for {self}.")

    async def on_cleanup_succeeded(self) -> None:
        _logger.info(f"Cleanup job succeeded for {self}, deleting resources.")
        await self._delete_deployment_resources()

    async def on_cleanup_failed(self) -> None:
        _logger.error(f"Cleanup job failed for {self}, manual intervention required.")

    async def _patch(
        self,
        init_status: BuildInitStatus | None = None,
        desired_replicas: int | None = None,
        remove_finalizers: bool = False,
        not_found_ok: bool = False,
    ) -> bool:
        ops: list[k8s.PatchOperation] = []
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
        if ops:
            await k8s.patch_deployment(self.deployment_name, ops, not_found_ok)
            return True
        return False


class Repo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str

    @property
    def link(self) -> str:
        return f"https://github.com/{self.name}"
