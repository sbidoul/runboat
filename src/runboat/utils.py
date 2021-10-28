import re


def slugify(s: str | int) -> str:
    return re.sub(r"[^a-z0-9]", "-", str(s).lower())
