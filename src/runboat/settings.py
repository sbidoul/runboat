from typing import Optional

from pydantic import BaseSettings, validator


class Settings(BaseSettings):
    # A user and password to protect the most sensitive operations of the API.
    api_admin_user: str
    api_admin_passwd: str
    # A JSON list of supported repositories in the form owner/repo.
    supported_repos: set[str]
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
    build_env: Optional[dict[str, str]]
    # A dictionary of secret environment variables to set in the build container and
    # jobs.
    build_secret_env: Optional[dict[str, str]]
    # A mapping of main branch names to container images used to run the builds.
    build_images: dict[str, str] = {
        "15.0": "ghcr.io/oca/oca-ci/py3.8-odoo15.0:latest",
        "14.0": "ghcr.io/oca/oca-ci/py3.6-odoo14.0:latest",
        "13.0": "ghcr.io/oca/oca-ci/py3.6-odoo13.0:latest",
        "12.0": "ghcr.io/oca/oca-ci/py3.6-odoo12.0:latest",
        "11.0": "ghcr.io/oca/oca-ci/py3.5-odoo11.0:latest",
        "10.0": "ghcr.io/oca/oca-ci/py2.7-odoo10.0:latest",
    }
    # The token to use for the GitHub api calls (to query branches and pull requests,
    # and report build statuses).
    github_token: Optional[str]
    # The file with the python logging configuration to use for the runboat controller.
    log_config: Optional[str]
    # The base url where the runboat UI and API is exposed on internet.
    # Used to generate backlinks in GitHub statuses
    base_url: str = "http://localhost:8000"

    class Config:
        env_prefix = "RUNBOAT_"

    @validator("supported_repos")
    @classmethod
    def validate_supported_repos(v) -> set[str]:
        return {item.lower() for item in v}


settings = Settings()
