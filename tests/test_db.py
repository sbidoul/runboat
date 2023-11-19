import datetime
from unittest.mock import MagicMock

from runboat.db import BuildsDb, SortOrder
from runboat.github import CommitInfo
from runboat.models import Build, BuildInitStatus, BuildStatus, Repo


def _make_build(
    name: str | None = None,
    *,
    status: BuildStatus | None = None,
    init_status: BuildInitStatus | None = None,
    repo: str | None = None,
    target_branch: str | None = None,
    pr: int | None = None,
    last_scaled: datetime.datetime | None = None,
    created: datetime.datetime | None = None,
) -> Build:
    name = name or "build-a"
    return Build(
        name=name,
        deployment_name=name + "-odoo",
        commit_info=CommitInfo(
            repo=repo or "oca/mis-builder",
            target_branch=target_branch or "15.0",
            pr=pr or None,
            git_commit="0d35a10f161b410f2baa3d416a338d191b6dabc0",
        ),
        status=status or BuildStatus.starting,
        init_status=init_status or BuildInitStatus.todo,
        desired_replicas=0,
        last_scaled=last_scaled or datetime.datetime(2021, 10, 1, 12, 0, 0),
        created=created or datetime.datetime(2021, 10, 1, 11, 0, 0),
    )


def test_add() -> None:
    db = BuildsDb()
    listener = MagicMock()
    db.register_listener(listener)
    db.add(_make_build())  # new
    listener.on_build_event.assert_called()
    listener.reset_mock()
    db.add(_make_build())  # no change
    listener.on_build_event.assert_not_called()
    db.add(_make_build(status=BuildStatus.failed))
    listener.on_build_event.assert_called()


def test_remove() -> None:
    db = BuildsDb()
    listener = MagicMock()
    db.register_listener(listener)
    db.remove("not-a-build")
    listener.on_build_event.assert_not_called()
    build = _make_build()
    db.add(build)
    db.remove(build.name)
    listener.on_build_event.assert_called()


def test_get_for_commit() -> None:
    db = BuildsDb()
    build = _make_build()
    db.add(build)
    assert (
        db.get_for_commit(
            build.commit_info.repo,
            build.commit_info.target_branch,
            build.commit_info.pr,
            git_commit=build.commit_info.git_commit,
        )
        == build
    )
    assert (
        db.get_for_commit(
            "not-a-repo",
            build.commit_info.target_branch,
            build.commit_info.pr,
            git_commit=build.commit_info.git_commit,
        )
        is None
    )


def test_search() -> None:
    db = BuildsDb()
    db.add(build1 := _make_build(name="b1", repo="oca/repo1"))
    db.add(_make_build(name="b2", repo="oca/repo2"))
    assert len(list(db.search())) == 2
    assert list(db.search(repo="oca/repo1")) == [build1]


def test_search_by_branch_and_pr() -> None:
    db = BuildsDb()
    db.add(build1 := _make_build(name="b1", target_branch="15.0", pr=None))
    db.add(build2 := _make_build(name="b2", target_branch="15.0", pr=1))
    # Searching on branch returns build for branch (and not pull requests).
    assert list(db.search(branch="15.0")) == [build1]
    # Searching on target_branch returns builds for branch and pull requests to branch.
    assert list(db.search(target_branch="15.0")) == [build1, build2]
    # Search on pr.
    assert list(db.search(pr=1)) == [build2]


def test_search_by_status() -> None:
    db = BuildsDb()
    db.add(build1 := _make_build(name="b1", status=BuildStatus.failed))
    db.add(build2 := _make_build(name="b2", status=BuildStatus.started))
    assert list(db.search(status=BuildStatus.failed)) == [build1]
    assert list(db.search(status=BuildStatus.started)) == [build2]
    assert list(db.search(status=BuildStatus.stopped)) == []


def test_search_sort() -> None:
    db = BuildsDb()
    db.add(build1 := _make_build(name="b1", target_branch="15.0", pr=None))
    db.add(build2 := _make_build(name="b2", target_branch="15.0", pr=1))
    db.add(build3 := _make_build(name="b3", target_branch="14.0", pr=None))
    db.add(build4 := _make_build(name="b4", target_branch="14.0", pr=2))
    db.add(build5 := _make_build(name="b5", target_branch="10.0", pr=3))
    assert [b.name for b in db.search(sort=SortOrder.asc)] == [
        build2.name,
        build4.name,
        build5.name,
        build3.name,
        build1.name,
    ]
    assert [b.name for b in db.search()] == [
        build1.name,
        build3.name,
        build5.name,
        build4.name,
        build2.name,
    ]


def test_count_by_status() -> None:
    db = BuildsDb()
    db.add(_make_build(name="b1", status=BuildStatus.started))
    db.add(_make_build(name="b2", status=BuildStatus.stopped))
    assert db.count_by_status(BuildStatus.started) == 1
    assert db.count_by_status(BuildStatus.stopped) == 1
    assert db.count_by_status(BuildStatus.failed) == 0


def test_count_by_init_status() -> None:
    db = BuildsDb()
    db.add(_make_build(name="b1", init_status=BuildInitStatus.started))
    db.add(_make_build(name="b2", init_status=BuildInitStatus.todo))
    assert db.count_by_init_status(BuildInitStatus.started) == 1
    assert db.count_by_init_status(BuildInitStatus.todo) == 1
    assert db.count_by_init_status(BuildInitStatus.failed) == 0


def test_count_all() -> None:
    db = BuildsDb()
    assert db.count_all() == 0
    db.add(_make_build(name="b1"))
    assert db.count_all() == 1
    db.add(_make_build(name="b2"))
    assert db.count_all() == 2


def test_repos() -> None:
    db = BuildsDb()
    db.add(_make_build(name="b1", repo="oca/repo1"))
    db.add(_make_build(name="b2", repo="oca/repo2"))
    assert db.repos() == [Repo(name="oca/repo1"), Repo(name="oca/repo2")]


def test_oldest_started() -> None:
    db = BuildsDb()
    db.add(
        _make_build(
            "b1",
            status=BuildStatus.started,
            last_scaled=datetime.datetime(2021, 10, 11, 12, 0, 0),
        )
    )
    db.add(
        _make_build(
            "b2",
            status=BuildStatus.started,
            last_scaled=datetime.datetime(2021, 10, 11, 12, 0, 2),
        )
    )
    db.add(
        _make_build(
            "b3",
            status=BuildStatus.stopped,
            last_scaled=datetime.datetime(2021, 10, 11, 12, 0, 4),
        )
    )
    assert [b.name for b in db.oldest_started(limit=3)] == ["b1", "b2"]


def test_oldest_stopped() -> None:
    db = BuildsDb()
    db.add(
        _make_build(
            name="b1",
            repo="oca/repo1",
            target_branch="15.0",
            status=BuildStatus.stopped,
            last_scaled=datetime.datetime(2021, 10, 11, 12, 0, 0),
            created=datetime.datetime(2021, 10, 11, 12, 0, 0),
        )
    )
    db.add(
        _make_build(
            name="b2",
            repo="oca/repo1",
            target_branch="15.0",
            status=BuildStatus.stopped,
            last_scaled=datetime.datetime(2021, 10, 11, 12, 0, 2),
            created=datetime.datetime(2021, 10, 11, 12, 0, 2),
        )
    )
    # a PR that is most recent than the latest branch build
    db.add(
        _make_build(
            name="pr1",
            repo="oca/repo1",
            target_branch="15.0",
            pr=1,
            status=BuildStatus.stopped,
            last_scaled=datetime.datetime(2021, 10, 11, 12, 0, 4),
            created=datetime.datetime(2021, 10, 11, 12, 0, 4),
        )
    )
    assert [b.name for b in db.oldest_stopped(limit=3)] == ["b1", "pr1"]
