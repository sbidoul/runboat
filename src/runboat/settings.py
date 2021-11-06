from typing import Optional

from pydantic import BaseSettings, validator


class Settings(BaseSettings):
    api_admin_user: str
    api_admin_passwd: str
    supported_repos: set[str]
    max_initializing: int = 2
    max_started: int = 6
    max_deployed: int = 10
    build_namespace: str
    build_pghost: str
    build_pgport: str
    build_pguser: str
    build_pgpassword: str
    build_domain: str
    build_env: Optional[dict[str, str]]
    build_images: dict[str, str] = {
        "15.0": "ghcr.io/oca/oca-ci/py3.8-odoo15.0:latest",
        "14.0": "ghcr.io/oca/oca-ci/py3.6-odoo14.0:latest",
        "13.0": "ghcr.io/oca/oca-ci/py3.6-odoo13.0:latest",
        "12.0": "ghcr.io/oca/oca-ci/py3.6-odoo12.0:latest",
        "11.0": "ghcr.io/oca/oca-ci/py3.5-odoo11.0:latest",
        "10.0": "ghcr.io/oca/oca-ci/py2.7-odoo10.0:latest",
    }
    github_token: Optional[str]
    log_config: Optional[str]

    class Config:
        env_prefix = "RUNBOAT_"

    @validator("supported_repos")
    @classmethod
    def validate_supported_repos(v) -> set[str]:
        return {item.lower() for item in v}


settings = Settings()
