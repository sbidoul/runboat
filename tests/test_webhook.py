import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from runboat.app import app
from runboat.controller import controller
from runboat.github import CommitInfo

client = TestClient(app)


def test_webhook_github_push(mocker: MockerFixture) -> None:
    mock = mocker.patch("fastapi.BackgroundTasks.add_task")
    response = client.post(
        "/webhooks/github",
        headers={
            "X-GitHub-Event": "push",
        },
        json={
            "repository": {"full_name": "oca/mis-builder"},
            "ref": "refs/heads/15.0",
            "after": "abcde",
        },
    )
    response.raise_for_status()
    mock.assert_called_with(
        controller.deploy_commit,
        CommitInfo(
            repo="oca/mis-builder",
            target_branch="15.0",
            pr=None,
            git_commit="abcde",
        ),
    )


def test_webhook_github_push_unsupported_repo(mocker: MockerFixture) -> None:
    mock = mocker.patch("fastapi.BackgroundTasks.add_task")
    response = client.post(
        "/webhooks/github",
        headers={
            "X-GitHub-Event": "push",
        },
        json={
            "repository": {"full_name": "org/not-a-repo"},  # repo not in .env.test
            "ref": "refs/heads/15.0",
            "after": "abcde",
        },
    )
    response.raise_for_status()
    mock.assert_not_called()


@pytest.mark.parametrize("action", ["opened", "synchronize"])
def test_webhook_github_pr(action: str, mocker: MockerFixture) -> None:
    mock = mocker.patch("fastapi.BackgroundTasks.add_task")
    response = client.post(
        "/webhooks/github",
        headers={
            "X-GitHub-Event": "pull_request",
        },
        json={
            "action": action,
            "repository": {"full_name": "oca/mis-builder"},
            "pull_request": {
                "base": {
                    "ref": "15.0",
                },
                "number": 381,
                "head": {
                    "sha": "abcde",
                },
            },
        },
    )
    response.raise_for_status()
    mock.assert_called_with(
        controller.deploy_commit,
        CommitInfo(
            repo="oca/mis-builder",
            target_branch="15.0",
            pr=381,
            git_commit="abcde",
        ),
    )


@pytest.mark.parametrize("action", ["opened", "synchronize", "closed"])
def test_webhook_github_pr_unsupported_branch(
    action: str, mocker: MockerFixture
) -> None:
    mock = mocker.patch("fastapi.BackgroundTasks.add_task")
    response = client.post(
        "/webhooks/github",
        headers={
            "X-GitHub-Event": "pull_request",
        },
        json={
            "action": action,
            "repository": {"full_name": "oca/mis-builder"},
            "pull_request": {
                "base": {
                    "ref": "14.0",  # branch 14.0 not declared in .env.test
                },
                "number": 381,
                "head": {
                    "sha": "abcde",
                },
            },
        },
    )
    response.raise_for_status()
    mock.assert_not_called()


def test_webhook_github_pr_close(mocker: MockerFixture) -> None:
    mock = mocker.patch("fastapi.BackgroundTasks.add_task")
    response = client.post(
        "/webhooks/github",
        headers={
            "X-GitHub-Event": "pull_request",
        },
        json={
            "action": "closed",
            "repository": {"full_name": "oca/mis-builder"},
            "pull_request": {
                "base": {
                    "ref": "15.0",
                },
                "number": 381,
            },
        },
    )
    response.raise_for_status()
    mock.assert_called_with(
        controller.undeploy_builds,
        repo="oca/mis-builder",
        pr=381,
    )
