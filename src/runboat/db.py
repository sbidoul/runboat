import sqlite3

from .models import BranchOrPull, Build, BuildStatus, BuildTodo


class BuildsDb:
    """An in-memory database of builds.

    It is maintained up-to-date by the controller that receives events from the cluster.
    We use sqlite3 to facilitate queries and sorting, such as counting by status, or
    finding oldest builds.

    Querying it on each event from k8s is probably not the most efficient, but this
    should do for a start, and there are plenty of ways to optimize.
    """

    _con: sqlite3.Connection

    def __init__(self):
        self.reset()

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
            "    'commit' TEXT NOT NULL, "
            "    image TEXT NOT NULL,"
            "    status TEXT NOT NULL, "
            "    todo TEXT, "
            "    last_scaled TEXT, "
            "    created TEXT NOT NULL"
            ")"
        )
        self._con.execute("CREATE INDEX idx_todo ON builds(todo, last_scaled)")
        self._con.execute("CREATE INDEX idx_status ON builds(status, last_scaled)")
        self._con.execute("CREATE INDEX idx_repo ON builds(repo)")

    def get(self, name: str) -> Build | None:
        row = self._con.execute("SELECT * FROM builds WHERE name=?", (name,)).fetchone()
        if not row:
            return None
        return self._build_from_row(row)

    def remove(self, name: str) -> None:
        with self._con:
            self._con.execute("DELETE FROM builds WHERE name=?", (name,))

    def add(self, build: Build) -> None:
        with self._con:
            self._con.execute(
                "INSERT OR REPLACE INTO builds "
                "("
                "    name,"
                "    deployment_name,"
                "    repo,"
                "    target_branch,"
                "    pr,"
                "    'commit',"
                "    image,"
                "    status,"
                "    todo, "
                "    last_scaled, "
                "    created"
                ") "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    build.name,
                    build.deployment_name,
                    build.repo,
                    build.target_branch,
                    build.pr,
                    build.commit,
                    build.image,
                    build.status,
                    build.todo,
                    build.last_scaled,
                    build.created,
                ),
            )

    def count_by_statuses(self, statuses: tuple[BuildStatus]) -> int:
        q = ",".join(["?"] * len(statuses))
        return self._con.execute(
            f"SELECT COUNT(name) FROM builds WHERE status IN ({q})", statuses
        ).fetchone()[0]

    def count_all(self) -> int:
        return self._con.execute("SELECT COUNT(name) FROM builds").fetchone()[0]

    def to_start(self, limit: int) -> list[Build]:
        """Return the list of builds to start, ordered by todo timestamp."""
        rows = self._con.execute(
            "SELECT * FROM builds WHERE todo=? ORDER BY last_scaled LIMIT ?",
            (BuildTodo.start, limit),
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
            "SELECT * FROM builds WHERE status=? ORDER BY last_scaled LIMIT ?",
            (BuildStatus.stopped, limit),
        ).fetchall()
        return [self._build_from_row(row) for row in rows]

    def branches_and_pulls(self, repo: str) -> list[BranchOrPull]:
        res = []
        branch_or_pull: BranchOrPull = None
        for row in self._con.execute(
            "SELECT * FROM builds WHERE repo=?"
            "ORDER BY target_branch, pr, created DESC",
            (repo,),
        ).fetchall():
            build = self._build_from_row(row)
            if (
                branch_or_pull is None
                or branch_or_pull.repo != build.repo
                or branch_or_pull.target_branch != build.target_branch
                or branch_or_pull.pr != build.pr
            ):
                branch_or_pull = BranchOrPull(
                    repo=build.repo,
                    target_branch=build.target_branch,
                    pr=build.pr,
                    builds=[],
                )
                res.append(branch_or_pull)
            branch_or_pull.builds.append(build)
        return res
