import re
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .exceptions import RepoOrBranchNotSupported


def validate_path(v: str | None) -> Path | None:
    if not v:
        return None
    p = Path(v)
    if not p.is_dir():
        raise ValueError(f"Invalid path: {p}")
    return p


class BuildSettings(BaseModel):
    image: str  # container image:tag
    # These extend the respective global settings.
    env: dict[str, str] = {}
    secret_env: dict[str, str] = {}
    template_vars: dict[str, str] = {}
    kubefiles_path: Annotated[Path | None, BeforeValidator(validate_path)] = None


class RepoSettings(BaseModel):
    repo: str  # regex
    branch: str  # regex
    builds: list[BuildSettings]

    @field_validator("builds")
    def validate_builds(cls, v: list[BuildSettings]) -> list[BuildSettings]:
        if len(v) != 1:
            raise ValueError(
                "One and only one build settings is allowed per repo/branch entry."
            )
        return v


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RUNBOAT_")

    # Configuration for supported repositories and branches.
    repos: list[RepoSettings]
    # A user and password to protect the most sensitive operations of the API.
    api_admin_user: str
    api_admin_passwd: str
    # The maximum number of concurrent initialization jobs.
    max_initializing: int = 2
    # The maximum number of builds that are started.
    max_started: int = 6
    # The maximum number of builds that are deployed.
    max_deployed: int = 10
    # The kubernetes namespace where the builds are deployed.
    build_namespace: str
    # The wildcard domain where the builds will be reacheable.
    build_domain: str
    # A dictionary of environment variables to set in the build container and jobs.
    build_env: dict[str, str] = {}
    # A dictionary of secret environment variables to set in the build container and
    # jobs.
    build_secret_env: dict[str, str] = {}
    # A dictionary of variables to be set in the jinja rendering context for the
    # kubefiles.
    build_template_vars: dict[str, str] = {}
    # The path of the default kubefiles to be used.
    build_default_kubefiles_path: Annotated[
        Path | None, BeforeValidator(validate_path)
    ] = None
    # The token to use for the GitHub api calls (to query branches and pull requests,
    # and report build statuses).
    github_token: str | None = None
    # The secret used to verify GitHub webhook signatures
    github_webhook_secret: bytes | None = None
    # The file with the python logging configuration to use for the runboat controller.
    log_config: str | None = None
    # The base url where the runboat UI and API is exposed on internet.
    # Used to generate backlinks in GitHub statuses
    base_url: str = "http://localhost:8000"
    # HTML fragment for second footer.
    additional_footer_html: str = ""
    # Disable posting of statuses to GitHub commits
    disable_commit_statuses: bool = False

    def get_build_settings(self, repo: str, target_branch: str) -> list[BuildSettings]:
        for repo_settings in self.repos:
            if not re.match(repo_settings.repo, repo, re.IGNORECASE):
                continue
            if not re.match(repo_settings.branch, target_branch):
                continue
            return repo_settings.builds
        raise RepoOrBranchNotSupported(
            f"Branch {target_branch} of {repo} not supported."
        )

    def is_repo_and_branch_supported(self, repo: str, target_branch: str) -> bool:
        try:
            self.get_build_settings(repo, target_branch)
        except RepoOrBranchNotSupported:
            return False
        else:
            return True


settings = Settings()
