from uvicorn.workers import UvicornWorker

from .settings import settings


class RunboatUvicornWorker(UvicornWorker):
    if settings.log_config:
        UvicornWorker.CONFIG_KWARGS["log_config"] = settings.log_config
