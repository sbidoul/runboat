import logging
import sqlite3
from typing import Iterator, Protocol, cast
from weakref import WeakSet

from .models import Build, BuildEvent, BuildInitStatus, BuildStatus

_logger = logging.getLogger(__name__)


class BuildListener(Protocol):
    def on_build_event(self, event: BuildEvent, build: Build) -> None:
        ...


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
    def _build_from_row(cls, row: sqlite3.Row) -> Build:
        return Build(**{k: row[k] for k in row.keys()})

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
            "    image TEXT NOT NULL,"
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
                "    image,"
                "    desired_replicas,"
                "    status,"
                "    init_status, "
                "    last_scaled, "
                "    created"
                ") "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    build.name,
                    build.deployment_name,
                    build.repo,
                    build.target_branch,
                    build.pr,
                    build.git_commit,
                    build.image,
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
        """Return a list of oldest stopped builds."""
        rows = self._con.execute(
            "SELECT * FROM builds WHERE status IN (?, ?, ?) "
            "ORDER BY last_scaled LIMIT ?",
            (BuildStatus.stopping, BuildStatus.stopped, BuildStatus.failed, limit),
        ).fetchall()
        return [self._build_from_row(row) for row in rows]

    def search(
        self,
        repo: str | None = None,
        target_branch: str | None = None,
        name: str | None = None,
    ) -> Iterator[Build]:
        query = "SELECT * FROM builds "
        where = []
        params = []
        if repo:
            where.append("repo=?")
            params.append(repo.lower())
        if target_branch:
            where.append("target_branch=?")
            params.append(target_branch)
        if name:
            where.append("name=?")
            params.append(name)
        if where:
            query += "WHERE " + " AND ".join(where)
        query += "ORDER BY repo, target_branch, pr, created DESC"
        rows = self._con.execute(query, params).fetchall()
        for row in rows:
            yield self._build_from_row(row)
