from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .db import BASE_DIR
from .update_service import GithubUpdateError, GithubUpdateService

router = APIRouter(tags=["检查更新"])
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def error_response(error: GithubUpdateError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": error.code, "message": error.message}},
    )


def _current_version() -> str:
    # 延迟导入避免循环依赖：app.py 注册本路由模块
    from .app import app as fastapi_app

    return str(fastapi_app.version)


def _build_service() -> GithubUpdateService:
    return GithubUpdateService(current_version=_current_version())


@router.get("/update", response_class=HTMLResponse)
def update_page(request: Request):
    service = _build_service()
    return templates.TemplateResponse(
        request,
        "update.html",
        {
            "current_version": service.current_version,
        },
    )


_update_cache = {"result": None, "timestamp": 0.0}

@router.get("/api/update/check")
def check_update():
    global _update_cache
    now = time.time()
    if _update_cache["result"] is not None and now - _update_cache["timestamp"] < 60:
        return _update_cache["result"]

    service = _build_service()
    res = service.check()
    _update_cache["result"] = res
    _update_cache["timestamp"] = now
    return res


@router.post("/api/update/apply")
def apply_update():
    service = _build_service()
    try:
        result = service.apply()
    except GithubUpdateError as exc:
        return error_response(exc)
    return result
