"""FastAPI application entry point for Evidence Currency Monitor Phase 4A."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .routers import runs, cases, stats, needs, demo, copilot, copilot_agent
from evidence_monitor.db import create_all


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Evidence Currency Monitor",
    description="Phase 4A: Agent orchestration + human decision API",
    version="0.4.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS for frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Consistent error format
@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )


app.include_router(runs.router)
app.include_router(cases.router)
app.include_router(stats.router)
app.include_router(needs.router)
app.include_router(demo.router)
app.include_router(copilot.router)
app.include_router(copilot_agent.router)


@app.get("/health")
def health():
    return {"status": "ok"}
