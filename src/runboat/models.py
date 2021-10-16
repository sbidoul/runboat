from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import relationship
from sqlalchemy.sql import expression

from .build_images import get_build_image
from .db import Base, Session
from .exceptions import RepoNotFound
from .github import BranchInfo, PullRequestInfo
from .settings import settings
from .utils import slugify


class utcnow(expression.FunctionElement):
    type = DateTime()


@compiles(utcnow, "postgresql")
def pg_utcnow(element, compiler, **kw):
    return "TIMEZONE('utc', CURRENT_TIMESTAMP)"


class Repo(Base):
    __tablename__ = "repo"

    id = Column(Integer, primary_key=True, index=True)
    created = Column(DateTime, nullable=False, server_default=utcnow())
    org = Column(String, nullable=False)
    name = Column(String, nullable=False)

    branches = relationship("Branch", back_populates="repo")

    @property
    def display_name(self) -> str:
        return f"{self.org}/{self.name}"

    @property
    def display_url(self) -> str:
        return f"https://github.com/{self.org}/{self.name}"

    @property
    def slug(self) -> str:
        return f"{self.org}-{self.name}"

    @classmethod
    def get_repo(cls, db: Session, org: str, name: str) -> "Repo":
        repo = (
            db.query(Repo)
            .filter(
                func.lower(Repo.org) == func.lower(org),
                func.lower(Repo.name) == func.lower(name),
            )
            .one_or_none()
        )
        if repo is None:
            raise RepoNotFound()
        return repo


class Branch(Base):
    __tablename__ = "branch"

    id = Column(Integer, primary_key=True, index=True)
    created = Column(DateTime, nullable=False, server_default=utcnow())
    target_branch = Column(String, nullable=False)
    pr = Column(Integer, nullable=True)

    repo_id = Column(Integer, ForeignKey("repo.id"), nullable=False, index=True)

    repo = relationship("Repo", back_populates="branches")
    builds = relationship("Build", back_populates="branch")

    @property
    def display_name(self) -> str:
        name = f"{self.target_branch}"
        if self.pr:
            name += f" #{self.pr}"
        return name

    @property
    def display_url(self) -> str:
        url = f"https://github.com/{self.repo.org}/{self.repo.name}"
        if self.pr:
            return f"{url}/pull/{self.pr}"
        return f"{url}/tree/{self.target_branch}"

    @property
    def slug(self) -> str:
        slug = f"{self.repo.slug}-{slugify(self.target_branch)}"
        if self.pr:
            return f"{slug}-pr{self.pr}"
        return slug

    @classmethod
    def for_github_branch(cls, db: Session, branch_info: BranchInfo) -> "Branch":
        repo = Repo.get_repo(db, branch_info.org, branch_info.repo)
        branch = (
            db.query(Branch)
            .filter(
                Branch.repo == repo,
                Branch.target_branch == branch_info.name,
                Branch.pr is None,
            )
            .one_or_none()
        )
        if branch is None:
            branch = Branch(
                repo=repo,
                target_branch=branch_info.name,
                pr=None,
            )
            db.add(branch)
            db.flush()
        return branch

    @classmethod
    def for_github_pr(cls, db: Session, pr_info: PullRequestInfo) -> "Branch":
        repo = Repo.get_repo(db, pr_info.org, pr_info.repo)
        branch = (
            db.query(Branch)
            .filter(
                Branch.repo == repo,
                Branch.target_branch == pr_info.target_branch,
                Branch.pr == pr_info.number,
            )
            .one_or_none()
        )
        if branch is None:
            branch = Branch(
                repo=repo,
                target_branch=pr_info.target_branch,
                pr=pr_info.number,
            )
            db.add(branch)
            db.flush()
        return branch


class Build(Base):
    __tablename__ = "build"

    id = Column(Integer, primary_key=True, index=True)
    created = Column(DateTime, nullable=False, server_default=utcnow())

    branch_id = Column(Integer, ForeignKey("branch.id"), nullable=False, index=True)
    branch = relationship("Branch", back_populates="builds")

    build_image = Column(String, nullable=False)
    git_sha = Column(String, nullable=False)
    status = Column(String, nullable=False)
    # ressource_label = Column(String, nullable=False, unique=True, index=True)

    # TODO: add unique constraint on branch_id + git_sha

    @property
    def display_name(self) -> str:
        return f"{self.created} {self.git_sha[:6]}"

    @property
    def display_url(self) -> str:
        return f"http://{self.slug}.{settings.build_domain}"

    @property
    def slug(self) -> str:
        return f"{self.branch.slug}-{self.id}"

    @classmethod
    def for_branch(cls, db: Session, branch: Branch, git_sha: str) -> "Build":
        print("*******", branch)
        build = (
            db.query(Build)
            .filter(
                Build.branch == branch,
                Build.git_sha == git_sha,
            )
            .one_or_none()
        )
        if build is None:
            build_image = get_build_image(branch.target_branch)
            build = Build(
                branch=branch,
                git_sha=git_sha,
                build_image=build_image,
                status="not_deployed",  # TODO use same enum as in API
            )
            db.add(build)
            db.flush()
        return build

    def delete(self) -> None:
        # self.stop
        # delete from db
        ...

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def init_log(self) -> str:
        ...

    def log(self, tail: int = 1000) -> str:
        ...
