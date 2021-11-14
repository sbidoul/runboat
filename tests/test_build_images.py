import pytest

from runboat.build_images import get_build_image, get_main_branch, is_branch_supported
from runboat.exceptions import BranchNotSupported


def test_get_main_branch() -> None:
    assert get_main_branch("15.0") == "15.0"
    assert get_main_branch("15.0-ocabot-merge") == "15.0"
    with pytest.raises(BranchNotSupported):
        get_main_branch("8.0")


def test_is_branch_supported() -> None:
    assert is_branch_supported("15.0")
    assert is_branch_supported("15.0-ocabot-merge")
    assert not is_branch_supported("8.0")


def test_get_build_image() -> None:
    assert get_build_image("15.0") == "ghcr.io/oca/oca-ci/py3.8-odoo15.0:latest"
    assert get_build_image("15.0-zzz") == "ghcr.io/oca/oca-ci/py3.8-odoo15.0:latest"
    with pytest.raises(BranchNotSupported):
        get_build_image("8.0")
