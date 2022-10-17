from pathlib import Path

import pytest

from runboat.exceptions import RepoOrBranchNotSupported
from runboat.settings import BuildSettings, settings


def test_get_build_settings() -> None:
    assert settings.get_build_settings("OCA/mis-builder", "15.0") == [
        BuildSettings(image="ghcr.io/oca/oca-ci/py3.8-odoo15.0:latest")
    ]
    with pytest.raises(RepoOrBranchNotSupported):
        settings.get_build_settings("acsone/mis-builder", "15.0")
    with pytest.raises(RepoOrBranchNotSupported):
        assert not settings.get_build_settings("OCA/mis-builder", "15.0-stuff")
    assert settings.get_build_settings("OCA/mis-builder", "15.0") == [
        BuildSettings(image="ghcr.io/oca/oca-ci/py3.8-odoo15.0:latest")
    ]
    assert settings.get_build_settings("OCA/mis-builder", "16.0") == [
        BuildSettings(
            image="ghcr.io/oca/oca-ci/py3.10-odoo16.0:latest",
            kubefiles_path=Path("/tmp"),
        )
    ]
