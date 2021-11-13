from uvicorn.workers import UvicornWorker  # type: ignore

from .settings import settings


class RunboatUvicornWorker(UvicornWorker):  # type: ignore
    if settings.log_config:
        UvicornWorker.CONFIG_KWARGS["log_config"] = settings.log_config
