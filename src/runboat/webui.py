import shutil
from importlib import resources
from pathlib import Path

import jinja2
from fastapi import APIRouter, FastAPI, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .controller import controller
from .models import BuildStatus
from .settings import settings

router = APIRouter()


FOOTER_HTML = """\
<p>
    <a href="https://github.com/sbidoul/runboat">Runboat</a> ☸️ -
    created with ❤️ for
    <a href="https://odoo-community.org">
        <img src="https://odoo-community.org/logo.png"
             style="height: 1em; vertical-align: text-bottom;"
        ></a>
    by Stéphane Bidoul with support of
    <a href="https://acsone.eu">
        <img src="https://acsone.eu/logo.png"
             style="height: 1em; vertical-align: text-bottom;"
        ></a>.
    Copyright © Runboat
    <a href="https://github.com/sbidoul/runboat/graphs/contributors">contributors</a>.
</p>
"""


def mount(app: FastAPI) -> None:
    """Render and and mount the webui templates.

    Files and Jinja templates are rendered and copied to a working
    directory, which is then mounted under the /webui route.
    """
    webui_path = Path(__file__).parent / "webui"
    with resources.as_file(
        resources.files(__package__).joinpath("webui-templates")
    ) as webui_template_path:
        for path in webui_template_path.iterdir():
            if path.name.endswith(".jinja"):
                template = jinja2.Template(path.read_text())
                rendered = template.render(
                    {
                        "footer_html": FOOTER_HTML,
                        "additional_footer_html": settings.additional_footer_html,
                    }
                )
                (webui_path / path.name[:-6]).write_text(rendered)
            else:
                shutil.copy(path, webui_path / path.name)
    app.mount("/webui", StaticFiles(directory=webui_path), name="webui")


@router.get("/builds", response_class=RedirectResponse)
async def builds(
    repo: str,
    target_branch: str | None = None,
    branch: str | None = None,
) -> Response:
    url = f"/webui/builds.html?repo={repo}"
    if target_branch:
        url += f"&target_branch={target_branch}"
    if branch:
        url += f"&branch={branch}"
    return RedirectResponse(url=url)


@router.get("/builds/{name}", response_class=RedirectResponse)
async def build(name: str, live: str | None = None) -> Response:
    build = controller.db.get(name)
    if not build:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if live is not None and build.status == BuildStatus.started:
        return RedirectResponse(url=build.deploy_link)
    return RedirectResponse(url=f"/webui/build.html?name={name}")
