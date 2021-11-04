from uvicorn.workers import UvicornWorker

from .settings import settings


class RunboatUvicornWorker(UvicornWorker):
    CONFIG_KWARGS = {"loop": "asyncio"}
    if settings.log_config:
        CONFIG_KWARGS["log_config"] = settings.log_config
