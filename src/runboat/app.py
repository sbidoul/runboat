from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import __version__, api, controller, k8s, webhooks, webui

app = FastAPI(
    title="Runboat", description="Runbot on Kubernetes ☸️", version=__version__
)
app.include_router(api.router, prefix="/api/v1", tags=["api"])
app.include_router(webhooks.router, tags=["webhooks"])
app.include_router(webui.router, tags=["webui"])
app.mount(
    "/webui", StaticFiles(directory=Path(__file__).parent / "webui"), name="webui"
)


@app.on_event("startup")
async def startup() -> None:
    await k8s.load_kube_config()
    await controller.controller.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await controller.controller.stop()
