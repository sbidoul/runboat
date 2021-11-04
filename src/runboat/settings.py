from typing import Optional

from pydantic import BaseSettings


class Settings(BaseSettings):
    admin_user: str
    admin_passwd: str
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
    github_token: Optional[str]
    log_config: Optional[str]

    class Config:
        env_prefix = "RUNBOAT_"


settings = Settings()
