"""FastAPI 应用入口:挂载 API 路由并托管 Vue 前端静态文件。"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, engine
from .routers import (
    agency,
    anomalies,
    auth,
    authorizations,
    checks,
    corrections,
    misc,
    positions,
    results,
)

FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend",
)


def create_app() -> FastAPI:
    Base.metadata.create_all(bind=engine)
    app = FastAPI(title="企业招聘背调授权与结果封存系统", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for r in (auth, positions, authorizations, checks, results, anomalies, corrections, agency, misc):
        app.include_router(r.router)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    if os.path.isdir(FRONTEND_DIR):
        app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    return app


app = create_app()
