from typing import Optional

from pydantic import BaseSettings


class Settings(BaseSettings):
    database_url: str
    build_pghost: Optional[str]
    build_pgport: Optional[str]
    build_pguser: Optional[str]
    build_pgpassword: Optional[str]
    build_domain: str


settings = Settings()
