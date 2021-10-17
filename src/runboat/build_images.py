import re

from .exceptions import BranchNotSupported

images = {
    "15.0": "ghcr.io/oca/oca-ci/py3.8-odoo15.0:latest",
    "14.0": "ghcr.io/oca/oca-ci/py3.6-odoo14.0:latest",
    "13.0": "ghcr.io/oca/oca-ci/py3.6-odoo13.0:latest",
    "12.0": "ghcr.io/oca/oca-ci/py3.6-odoo12.0:latest",
    "11.0": "ghcr.io/oca/oca-ci/py3.5-odoo11.0:latest",
    "10.0": "ghcr.io/oca/oca-ci/py2.7-odoo10.0:latest",
}


TARGET_BRANCH_RE = re.compile(r"^(\d+\.\d+)")


def get_target_branch(branch_name: str) -> str:
    mo = TARGET_BRANCH_RE.match(branch_name)
    if not mo:
        raise BranchNotSupported(
            f"Malformed branch name {branch_name} "
            f"(it should start with an Odoo branch name)."
        )
    if mo:
        key = mo.group(1)
    if key not in images:
        raise BranchNotSupported(
            f"No build image configured for {key} (from {branch_name})."
        )
    return key


check_branch_supported = get_target_branch


def get_build_image(branch_name: str) -> str:
    return images[get_target_branch(branch_name)]
