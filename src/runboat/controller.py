import asyncio
import contextlib
import logging

from . import k8s
from .db import BuildsDb
from .models import Build, BuildInitStatus, BuildStatus
from .settings import settings

_logger = logging.getLogger(__name__)


class Controller:
    """The controller monitors and manages the deployments.

    It runs several background tasks:

    - The 'deployment_watcher' listens to kubernetes events on deployments and maintains
      an in-memory database of existing deployments and their state. It wakes up the
      initializer, stopper and undeployer when the state of deployments change.
    - The 'job_watcher' listens to kubernetes events on jobs, to maintain the
      runboat/init-status annotation on deployments, and act on such events (such as
      starting when an initialization succeeded or undeploying when a cleanup
      succeeded).
    - The 'initializer' starts initialization jobs for deployment that have been marked
      with 'runboat/init-status=todo', while making sure that the maximum number of
      deployments initializing concurrently does not exceed the limit.
    - The 'stopper' stops old running deployments.
    - The 'undeployer' undeploys old stopped deployments.
    """

    db: BuildsDb
    _tasks: list[asyncio.Task]
    _wakeup_event: asyncio.Event

    def __init__(self) -> None:
        self._tasks = []
        self._wakeup_event = asyncio.Event()
        self.reset()

    def reset(self) -> None:
        self.db = BuildsDb()

    @property
    def started(self) -> int:
        return self.db.count_by_status(BuildStatus.started)

    @property
    def max_started(self) -> int:
        return settings.max_started

    @property
    def to_initialize(self) -> int:
        return self.db.count_by_init_status(BuildInitStatus.todo)

    @property
    def initializing(self) -> int:
        return self.db.count_by_init_status(BuildInitStatus.started)

    @property
    def max_initializing(self) -> int:
        return settings.max_initializing

    @property
    def deployed(self) -> int:
        return self.db.count_all()

    @property
    def max_deployed(self) -> int:
        return settings.max_deployed

    async def deploy_or_delay_start(
        self, repo: str, target_branch: str, pr: int | None, git_commit: str
    ) -> None:
        build = self.db.get_for_commit(
            repo=repo,
            target_branch=target_branch,
            pr=pr,
            git_commit=git_commit,
        )
        if build is not None:
            await build.start()
            return
        await Build.deploy(
            repo=repo,
            target_branch=target_branch,
            pr=pr,
            git_commit=git_commit,
        )

    def _wakeup(self) -> None:
        self._wakeup_event.set()
        self._wakeup_event.clear()

    async def _sleep(self) -> None:
        # Wait on the wakeup event, but wakeup after 10 seconds if nothing happens,
        # in case we have missed an event.
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._wakeup_event.wait(), 10)

    async def get_build(self, build_name: str, db_only: bool = True) -> Build | None:
        build = self.db.get(build_name)
        if build is not None:
            return build
        if not db_only:
            _logger.debug(
                "Build %s not in local db, fetching from k8s api.", build_name
            )
            build = await Build.from_name(build_name)
            if build is not None:
                if self.db.add(build):
                    self._wakeup()
                return build
        return None

    async def deployment_watcher(self) -> None:
        self.reset()  # empty the local db each time we start watching
        async for event_type, deployment in k8s.watch_deployments():
            _logger.debug(
                "%s %s %s dr=%s/rr=%s",
                event_type,
                deployment.metadata.name,
                deployment.metadata.resource_version,
                deployment.spec.replicas,
                deployment.status.ready_replicas,
            )
            build_name = deployment.metadata.labels.get("runboat/build")
            if not build_name:
                continue
            should_wakeup = False
            if event_type in (None, "ADDED", "MODIFIED"):
                should_wakeup = self.db.add(Build.from_deployment(deployment))
            elif event_type == "DELETED":
                should_wakeup = self.db.remove(build_name)
            else:
                _logger.error(f"Unexpected k8s event type {event_type}.")
            if should_wakeup:
                self._wakeup()

    async def job_watcher(self) -> None:
        async for event_type, job in k8s.watch_jobs():
            _logger.debug(
                "%s %s %s a=%s/s=%s/f=%s",
                event_type,
                job.metadata.name,
                job.metadata.resource_version,
                job.status.active,
                job.status.succeeded,
                job.status.failed,
            )
            build_name = job.metadata.labels.get("runboat/build")
            if not build_name:
                continue
            job_kind = job.metadata.labels.get("runboat/job-kind")
            if job_kind not in ("initialize", "cleanup"):
                continue
            if event_type in (None, "ADDED", "MODIFIED"):
                # Look for build in local db and also in k8s api.
                # This is necessary because job events may come before build events
                # have arrived.
                build = await self.get_build(build_name, db_only=False)
                if build is None:
                    _logger.warning(
                        f"Received job event for {build_name} "
                        f"but the corresponding deployment is gone. "
                        f"Deleting all build resources."
                    )
                    await k8s.delete_resources(build_name)
                    continue
                if job_kind == "initialize":
                    if job.status.active:
                        await build.on_initialize_started()
                    elif job.status.succeeded:
                        await build.on_initialize_succeeded()
                    elif job.status.failed:
                        await build.on_initialize_failed()
                if job_kind == "cleanup":
                    if job.status.active:
                        await build.on_cleanup_started()
                    elif job.status.succeeded:
                        await build.on_cleanup_succeeded()
                    elif job.status.failed:
                        await build.on_cleanup_failed()
            elif event_type == "DELETED":
                pass
            else:
                _logger.error(f"Unexpected k8s event type {event_type}.")

    async def initializer(self) -> None:
        while True:
            await self._sleep()
            can_initialize = self.max_initializing - self.initializing
            if can_initialize <= 0:
                continue  # no capacity for now, back to sleep
            to_initialize = self.db.to_initialize(limit=can_initialize)
            if not to_initialize:
                continue  # nothing startable, back to sleep
            _logger.info(
                f"{self.initializing} builds of max {self.max_initializing} "
                f"are initializing. Initializing {len(to_initialize)} more."
            )
            for build in to_initialize:
                await build.initialize()

    async def stopper(self) -> None:
        while True:
            await self._sleep()
            can_stop = self.started - self.max_started
            if can_stop <= 0:
                continue  # no need to stop for now, back to sleep
            to_stop = self.db.oldest_started(limit=can_stop)
            if not to_stop:
                continue  # nothing stoppable, back to sleep
            _logger.info(
                f"{self.started} builds of max {self.max_started} are started. "
                f"Stopping {len(to_stop)}."
            )
            for build in to_stop:
                await build.stop()

    async def undeployer(self) -> None:
        while True:
            await self._sleep()
            can_undeploy = self.deployed - self.max_deployed
            if can_undeploy <= 0:
                continue  # no need to undeploy for now, back to sleep
            to_undeploy = self.db.oldest_stopped(limit=can_undeploy)
            if not to_undeploy:
                continue  # nothing undeployable, back to sleep
            _logger.info(
                f"{self.deployed} builds of max {self.max_deployed} are deployed. "
                f"Undeploying {len(to_undeploy)}."
            )
            for build in to_undeploy:
                await build.undeploy()

    async def start(self) -> None:
        _logger.info("Starting controller tasks.")

        async def walking_dead(func):
            while True:
                _logger.info(f"(Re)starting {func.__name__}")
                try:
                    await func()
                except Exception:
                    delay = 5
                    _logger.exception(
                        f"Unhandled exception in {func.__name__}, "
                        f"restarting in {delay} sec."
                    )
                    await asyncio.sleep(delay)

        for f in (
            self.deployment_watcher,
            self.job_watcher,
            self.initializer,
            self.stopper,
            self.undeployer,
        ):
            self._tasks.append(asyncio.create_task(walking_dead(f)))

    async def stop(self) -> None:
        _logger.info("Stopping controller tasks.")
        for task in self._tasks:
            task.cancel()
        # Wait until all tasks are cancelled.
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._task = []


controller = Controller()
