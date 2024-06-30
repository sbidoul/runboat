import logging
import sqlite3
from collections.abc import Iterator
from enum import Enum
from typing import Protocol, cast
from weakref import WeakSet

from .github import CommitInfo
from .models import Build, BuildEvent, BuildInitStatus, BuildStatus, Repo

_logger = logging.getLogger(__name__)


class SortOrder(Enum):
    # commits of pr, then commits of branches, oldest first
    asc = 1
    # commit os branches, then commits of prs, newest first
    desc = 2


class BuildListener(Protocol):
    def on_build_event(self, event: BuildEvent, build: Build) -> None: ...


class BuildsDb:
    """An in-memory database of builds.

    It is maintained up-to-date by the controller that receives events
    from the cluster. We use sqlite3 to facilitate queries and sorting,
    such as counting by status, or finding oldest builds.
    """

    _con: sqlite3.Connection

    def __init__(self) -> None:
        self._listeners: WeakSet[BuildListener] = WeakSet()
        self.reset()

    def register_listener(self, listener: BuildListener) -> None:
        self._listeners.add(listener)

    @classmethod
    def _build_from_row(cls, row: "sqlite3.Row") -> Build:
        commit_info_fields = {"repo", "target_branch", "pr", "git_commit"}
        commit_info = CommitInfo(**{k: row[k] for k in commit_info_fields})
        return Build(
            commit_info=commit_info,
            **{k: row[k] for k in row.keys() if k not in commit_info_fields},
        )

    def reset(self) -> None:
        self._con = sqlite3.connect(":memory:")
        self._con.row_factory = sqlite3.Row
        self._con.execute(
            "CREATE TABLE builds ("
            "    name TEXT NOT NULL PRIMARY KEY, "
            "    deployment_name TEXT NOT NULL, "
            "    repo TEXT NOT NULL, "
            "    target_branch TEXT NOT NULL, "
            "    pr INTEGER, "
            "    git_commit TEXT NOT NULL, "
            "    desired_replicas INTEGER NOT NULL,"
            "    status TEXT NOT NULL, "
            "    init_status TEXT NOT NULL, "
            "    last_scaled TEXT NOT NULL, "
            "    created TEXT NOT NULL"
            ")"
        )
        self._con.execute(
            "CREATE INDEX idx_init_status ON builds(init_status, created)"
        )
        self._con.execute("CREATE INDEX idx_status ON builds(status, last_scaled)")
        self._con.execute("CREATE INDEX idx_repo ON builds(repo)")

    def get(self, name: str) -> Build | None:
        row = self._con.execute("SELECT * FROM builds WHERE name=?", (name,)).fetchone()
        if not row:
            return None
        return self._build_from_row(row)

    def get_for_commit(
        self, repo: str, target_branch: str, pr: int | None, git_commit: str
    ) -> Build | None:
        query = "SELECT * FROM builds WHERE repo=? AND target_branch=? AND git_commit=?"
        params: list[str | int] = [repo.lower(), target_branch, git_commit]
        if pr:
            query += " AND pr=?"
            params.append(pr)
        else:
            query += " AND pr IS NULL"
        row = self._con.execute(query, params).fetchone()
        if not row:
            return None
        return self._build_from_row(row)

    def remove(self, name: str) -> None:
        build = self.get(name)
        if build is None:
            return  # already removed
        with self._con:
            self._con.execute("DELETE FROM builds WHERE name=?", (name,))
        _logger.info("Noticed removal of %s", name)
        for listener in self._listeners:
            listener.on_build_event(BuildEvent.removed, build)

    def add(self, build: Build) -> None:
        prev_build = self.get(build.name)
        if prev_build == build:
            return  # no change
        with self._con:
            self._con.execute(
                "INSERT OR REPLACE INTO builds "
                "("
                "    name,"
                "    deployment_name,"
                "    repo,"
                "    target_branch,"
                "    pr,"
                "    git_commit,"
                "    desired_replicas,"
                "    status,"
                "    init_status, "
                "    last_scaled, "
                "    created"
                ") "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    build.name,
                    build.deployment_name,
                    build.commit_info.repo,
                    build.commit_info.target_branch,
                    build.commit_info.pr,
                    build.commit_info.git_commit,
                    build.desired_replicas,
                    build.status,
                    build.init_status,
                    build.last_scaled.isoformat(),
                    build.created.isoformat(),
                ),
            )
        if prev_build is None:
            action = "addition"
        else:
            action = "update"
        _logger.info(
            "Noticed %s of %s (%s/%s/desired_replicas=%s/last_scaled=%s)",
            action,
            build,
            build.status,
            build.init_status,
            build.desired_replicas,
            build.last_scaled,
        )
        for listener in self._listeners:
            listener.on_build_event(BuildEvent.modified, build)

    def count_by_status(self, status: BuildStatus) -> int:
        count = self._con.execute(
            "SELECT COUNT(name) FROM builds WHERE status=?", (status,)
        ).fetchone()[0]
        return cast(int, count)

    def count_by_init_status(self, init_status: BuildInitStatus) -> int:
        count = self._con.execute(
            "SELECT COUNT(name) FROM builds WHERE init_status=?", (init_status,)
        ).fetchone()[0]
        return cast(int, count)

    def count_all(self) -> int:
        count = self._con.execute("SELECT COUNT(name) FROM builds").fetchone()[0]
        return cast(int, count)

    def count_deployed(self) -> int:
        count = self._con.execute(
            "SELECT COUNT(name) FROM builds WHERE status!=?",
            (BuildStatus.undeploying,),
        ).fetchone()[0]
        return cast(int, count)

    def to_cleanup(self) -> list[Build]:
        rows = self._con.execute(
            "SELECT * FROM builds WHERE status=? ORDER BY created",
            (BuildStatus.undeploying,),
        ).fetchall()
        return [self._build_from_row(row) for row in rows]

    def to_initialize(self, limit: int) -> list[Build]:
        """Return the list of builds to initialize, ordered by creation timestamp."""
        rows = self._con.execute(
            "SELECT * FROM builds WHERE init_status=? ORDER BY created LIMIT ?",
            (BuildInitStatus.todo, limit),
        ).fetchall()
        return [self._build_from_row(row) for row in rows]

    def oldest_started(self, limit: int) -> list[Build]:
        """Return a list of oldest started builds."""
        rows = self._con.execute(
            "SELECT * FROM builds WHERE status=? ORDER BY last_scaled LIMIT ?",
            (BuildStatus.started, limit),
        ).fetchall()
        return [self._build_from_row(row) for row in rows]

    def oldest_stopped(self, limit: int) -> list[Build]:
        """Return a list of oldest stopped builds.

        Exclude the most recent build of each branch that we want to
        preserve from eviction.
        """
        rows = self._con.execute(
            """\
                SELECT * FROM (
                    SELECT
                        ROW_NUMBER () OVER (
                            PARTITION BY repo, target_branch, pr
                            ORDER BY created DESC
                        ) AS rownum,
                        *
                    FROM builds
                )
                WHERE status IN (?, ?, ?) AND (rownum != 1 OR pr IS NOT NULL)
                ORDER BY last_scaled
                LIMIT ?
            """,
            (BuildStatus.stopping, BuildStatus.stopped, BuildStatus.failed, limit),
        ).fetchall()
        return [self._build_from_row(row) for row in rows]

    def repos(self) -> list[Repo]:
        rows = self._con.execute("SELECT DISTINCT repo FROM builds ORDER BY repo")
        return [Repo(name=row[0]) for row in rows]

    def search(
        self,
        *,
        repo: str | None = None,
        target_branch: str | None = None,
        branch: str | None = None,
        pr: int | None = None,
        name: str | None = None,
        status: BuildStatus | None = None,
        sort: SortOrder = SortOrder.desc,
    ) -> Iterator[Build]:
        query = "SELECT * FROM builds "
        where = []
        params: list[str | int] = []
        if repo:
            where.append("repo=?")
            params.append(repo.lower())
        if target_branch:
            where.append("target_branch=?")
            params.append(target_branch)
        if branch:
            where.append("target_branch=?")
            params.append(branch)
            where.append("pr IS NULL")
        if pr is not None:
            where.append("pr=?")
            params.append(pr)
        if name:
            where.append("name=?")
            params.append(name)
        if status:
            where.append("status=?")
            params.append(status.value)
        if where:
            query += "WHERE " + " AND ".join(where)
        if sort == SortOrder.desc:
            query += (
                " ORDER BY"
                " repo DESC,"
                " COALESCE(pr, 999999) DESC,"
                " target_branch DESC,"
                " created DESC"
            )
        elif sort == SortOrder.asc:
            query += (
                " ORDER BY"
                " repo ASC,"
                " COALESCE(pr, 999999) ASC,"
                " target_branch ASC,"
                " created ASC"
            )
        rows = self._con.execute(query, params).fetchall()
        for row in rows:
            yield self._build_from_row(row)
