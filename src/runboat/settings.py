import re

from pydantic import BaseModel, BaseSettings, validator

from .exceptions import RepoOrBranchNotSupported


class BuildSettings(BaseModel):
    image: str  # container image:tag
    # These extend the respective global settings.
    env: dict[str, str] = {}
    secret_env: dict[str, str] = {}
    template_vars: dict[str, str] = {}


class RepoSettings(BaseModel):
    repo: str  # regex
    branch: str  # regex
    builds: list[BuildSettings]

    @validator("builds")
    def validate_builds(cls, v: list[BuildSettings]) -> list[BuildSettings]:
        if len(v) != 1:
            raise ValueError(
                "One and only one build settings is allowed per repo/branch entry."
            )
        return v


class Settings(BaseSettings):
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
    # The token to use for the GitHub api calls (to query branches and pull requests,
    # and report build statuses).
    github_token: str | None
    # The file with the python logging configuration to use for the runboat controller.
    log_config: str | None
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

    class Config:
        env_prefix = "RUNBOAT_"


settings = Settings()
