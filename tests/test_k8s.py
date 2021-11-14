import pytest

from runboat.k8s import _split_image_name_tag


@pytest.mark.parametrize(
    ("image", "expected"),
    [
        ("postgres", ("postgres", "latest")),
        ("postgres:12", ("postgres", "12")),
    ],
)
def test_split_image_name_tag(image: str, expected: tuple[str, str]) -> None:
    assert _split_image_name_tag(image) == expected
