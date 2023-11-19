from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__, api, controller, k8s, webhooks, webui


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await k8s.load_kube_config()
    await controller.controller.start()
    yield
    await controller.controller.stop()


app = FastAPI(
    title="Runboat",
    description="Runbot on Kubernetes ☸️",
    version=__version__,
    lifespan=lifespan,
)
app.include_router(api.router, prefix="/api/v1", tags=["api"])
app.include_router(webhooks.router, tags=["webhooks"])
app.include_router(webui.router, tags=["webui"])

webui.mount(app)
