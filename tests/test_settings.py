import pytest

from runboat.exceptions import RepoOrBranchNotSupported
from runboat.settings import BuildSettings, get_build_settings


def test_get_build_settings() -> None:
    assert get_build_settings("OCA/mis-builder", "15.0") == [
        BuildSettings(image="ghcr.io/oca/oca-ci/py3.8-odoo15.0:latest")
    ]
    with pytest.raises(RepoOrBranchNotSupported):
        get_build_settings("acsone/mis-builder", "15.0")
    with pytest.raises(RepoOrBranchNotSupported):
        assert not get_build_settings("OCA/mis-builder", "15.0-stuff")
