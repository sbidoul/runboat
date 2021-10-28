from pydantic import BaseSettings


class Settings(BaseSettings):
    admin_user: str
    admin_passwd: str
    supported_repos: set[str]
    max_starting: int = 2
    max_running: int = 4
    max_deployed: int = 10
    build_namespace: str
    build_pghost: str
    build_pgport: str
    build_pguser: str
    build_pgpassword: str
    build_admin_passwd: str
    build_domain: str

    class Config:
        env_prefix = "RUNBOAT_"


settings = Settings()
