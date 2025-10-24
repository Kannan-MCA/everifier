# app/main.py

from fastapi import FastAPI, HTTPException
from app.api.routes import router
from app.utils.logger import setup_logging

app = FastAPI(title="Email Validator API")
app.include_router(router)
setup_logging(app)