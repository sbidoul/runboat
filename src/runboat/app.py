from fastapi import FastAPI

from .db import create_tables

app = FastAPI(title="Runboat")


@app.on_event("startup")
async def startup():
    create_tables()
