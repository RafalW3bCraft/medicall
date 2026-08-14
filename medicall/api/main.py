"""
FastAPI application for MediCall.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from medicall.api.routers import appointments, handoffs

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(
    title="MediCall",
    description="Pre-arrival care coordination powered by CALL-E",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(appointments.router, prefix="/appointments", tags=["appointments"])
app.include_router(handoffs.router, prefix="/handoffs", tags=["handoffs"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "medicall"}
