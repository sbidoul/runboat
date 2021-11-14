from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .controller import controller
from .models import BuildStatus

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "webui"))


@router.get("/builds/{name}", response_class=HTMLResponse)
async def build(request: Request, name: str, live: Optional[str] = None) -> Response:
    build = controller.db.get(name)
    if not build:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if live is not None and build.status == BuildStatus.started:
        return RedirectResponse(url=build.deploy_link)
    return templates.TemplateResponse(
        "build.html.jinja", {"request": request, "build": build}
    )
