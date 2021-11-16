from typing import Optional

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from .controller import controller
from .models import BuildStatus

router = APIRouter()


@router.get("/builds/{name}", response_class=HTMLResponse)
async def build(name: str, live: Optional[str] = None) -> Response:
    build = controller.db.get(name)
    if not build:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if live is not None and build.status == BuildStatus.started:
        return RedirectResponse(url=build.deploy_link)
    return RedirectResponse(url=f"/webui/build.html?name={name}")
