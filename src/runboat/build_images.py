from typing import Optional

images = {
    "15.0": "ghcr.io/oca/oca-ci/py3.8-odoo15.0:latest",
    "14.0": "ghcr.io/oca/oca-ci/py3.6-odoo14.0:latest",
    "13.0": "ghcr.io/oca/oca-ci/py3.6-odoo13.0:latest",
    "12.0": "ghcr.io/oca/oca-ci/py3.6-odoo12.0:latest",
    "11.0": "ghcr.io/oca/oca-ci/py3.5-odoo11.0:latest",
    "10.0": "ghcr.io/oca/oca-ci/py2.7-odoo10.0:latest",
}


def get_build_image(target_branch: str) -> Optional[str]:
    return images.get(target_branch)
