# app/utils/logger.py
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

def setup_logging(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )