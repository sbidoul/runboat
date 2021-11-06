import re

from .exceptions import BranchNotSupported
from .settings import settings

TARGET_BRANCH_RE = re.compile(r"^(\d+\.\d+)")


def get_main_branch(branch_name: str) -> str:
    mo = TARGET_BRANCH_RE.match(branch_name)
    if not mo:
        raise BranchNotSupported(
            f"Malformed branch name {branch_name} "
            f"(it should start with an Odoo branch name)."
        )
    key = mo.group(1)
    if key not in settings.build_images:
        raise BranchNotSupported(
            f"No build image configured for {key} (from {branch_name})."
        )
    return key


def is_branch_supported(branch_name: str) -> bool:
    try:
        return bool(get_main_branch(branch_name))
    except BranchNotSupported:
        return False


def is_main_branch(branch_name: str) -> bool:
    try:
        return branch_name == get_main_branch(branch_name)
    except BranchNotSupported:
        return False


def get_build_image(branch_name: str) -> str:
    return settings.build_images[get_main_branch(branch_name)]
