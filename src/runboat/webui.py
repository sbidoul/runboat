from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .controller import controller
from .models import BuildStatus

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "webui")


@router.get("/builds/{name}", response_class=HTMLResponse)
async def build(request: Request, name: str, live: Optional[str] = None):
    build = controller.db.get(name)
    if not build:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if live is not None and build.status == BuildStatus.started:
        return RedirectResponse(url=build.link)
    return templates.TemplateResponse(
        "build.html", {"request": request, "build": build}
    )
