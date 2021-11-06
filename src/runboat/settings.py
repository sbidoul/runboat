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
    build_admin_passwd: str
    build_domain: str
    build_env: Optional[dict[str, str]]
    github_token: Optional[str]
    log_config: Optional[str]

    class Config:
        env_prefix = "RUNBOAT_"

    @validator("supported_repos")
    @classmethod
    def validate_supported_repos(v) -> set[str]:
        return {item.lower() for item in v}


settings = Settings()
