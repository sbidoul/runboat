from fastapi import FastAPI

from . import api, controller, k8s, webhooks

app = FastAPI(title="Runboat", description="Runbot on Kubernetes ☸️")
app.include_router(api.router)
app.include_router(webhooks.router)


@app.on_event("startup")
async def startup() -> None:
    await k8s.load_kube_config()
    await controller.controller.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await controller.controller.stop()
