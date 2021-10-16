import datetime
from enum import Enum
from typing import List

from fastapi import Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import github, models
from .app import app
from .db import get_db


class Repo(BaseModel):
    id: str
    created: datetime.datetime
    display_name: str
    display_url: str = Field(title="Link to view the repo")

    class Config:
        orm_mode = True


@app.get(
    "/repos",
    response_model=List[Repo],
)
def repos(db: Session = Depends(get_db)):
    return db.query(models.Repo).all()


class Branch(BaseModel):
    id: str
    created: datetime.datetime
    display_name: str
    display_url: str = Field(title="Link to view the branch or PR")

    class Config:
        orm_mode = True


@app.get(
    "/repos/{repo_id}/branches",
    response_model=List[Branch],
)
def branches(repo_id: str, db: Session = Depends(get_db)):
    return db.query(models.Branch).filter(models.Branch.repo_id == repo_id).all()


class BuildStatus(str, Enum):
    stopped = "stopped"
    running = "running"
    deploying = "deploying"
    not_deployed = "not_deployed"


class Build(BaseModel):
    id: str
    created: datetime.datetime
    display_name: str
    display_url: str = Field(title="Link to open the build")
    status: BuildStatus

    class Config:
        orm_mode = True


@app.get(
    "/repos/{repo_id}/branches/{branch_id}/builds",
    response_model=List[Build],
)
def builds(repo_id: str, branch_id: str):
    ...


@app.get(
    "/repos/{repo_id}/branches/{branch_id}/builds/{build_id}/init-log",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/plain": {}}}},
)
def init_log(repo_id: str, branch_id: str, build_id: str):
    ...


@app.get(
    "/repos/{repo_id}/branches/{branch_id}/builds/{build_id}/log",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/plain": {}}}},
)
def log(repo_id: str, branch_id: str, build_id: str):
    ...


@app.post(
    "/repos/{repo_id}/branches/{branch_id}/builds/{build_id}/start",
)
def start(repo_id: str, branch_id: str, build_id: str):
    """Start the deployment.

    If already running, drop the db and restart.
    """
    ...


@app.post(
    "/repos/{repo_id}/branches/{branch_id}/builds/{build_id}/stop",
)
def stop(repo_id: str, branch_id: str, build_id: str):
    """Stop the deployment, drop the database."""
    ...


@app.post(
    "/trigger-branch",
    response_model=Build,
)
def trigger_branch(org: str, repo: str, branch: str, db: Session = Depends(get_db)):
    branch_info = github.get_branch_info(org, repo, branch)
    branch = models.Branch.for_github_branch(db, branch_info)
    return models.Build.for_branch(db, branch, branch_info.head_sha)


@app.post(
    "/trigger-pr",
    response_model=Build,
)
def trigger_pr(org: str, repo: str, pr: int, db: Session = Depends(get_db)):
    pr_info = github.get_pr_info(org, repo, pr)
    branch = models.Branch.for_github_pr(db, pr_info)
    return models.Build.for_branch(db, branch, pr_info.head_sha)
