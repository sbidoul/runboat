import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .settings import settings

security = HTTPBasic()


def authenticated(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    correct_username = secrets.compare_digest(
        credentials.username,
        settings.admin_user,
    )
    correct_password = secrets.compare_digest(
        credentials.password,
        settings.admin_passwd,
    )
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect user name or password",
            headers={"WWW-Authenticate": "Basic"},
        )
