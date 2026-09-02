from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .db import BASE_DIR
from .manga_composer import RESIZE_LABELS, RESIZE_STRATEGIES
from .manga_service import MangaServiceError, manga_service

router = APIRouter(tags=["漫画"])
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def error_response(error: MangaServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": error.code, "message": error.message}},
    )


def page_redirect(message: str, message_type: str = "success") -> RedirectResponse:
    return RedirectResponse(f"/manga?{urlencode({'message': message, 'message_type': message_type})}", status_code=303)


@router.get("/manga", response_class=HTMLResponse)
def manga_page(request: Request, message: str = "", message_type: str = ""):
    return templates.TemplateResponse(
        request,
        "manga.html",
        {
            "jobs": manga_service.list_jobs(),
            "config": manga_service.get_config(),
            "resize_strategies": [(key, RESIZE_LABELS[key]) for key in RESIZE_STRATEGIES],
            "message": message,
            "message_type": message_type,
        },
    )


@router.post("/manga/config")
def update_manga_config(
    output_dir: str = Form(""),
    proxy: str = Form(""),
    domains: str = Form(""),
    duration_ms: int = Form(500),
    cover_duration_ms: int = Form(2000),
    loop: int = Form(0),
    resize: str = Form("pad"),
):
    try:
        manga_service.update_config(
            {
                "output_dir": output_dir.strip(),
                "proxy": proxy.strip(),
                "domains": domains,
                "duration_ms": duration_ms,
                "cover_duration_ms": cover_duration_ms,
                "loop": loop,
                "resize": resize,
            }
        )
        manga_service.ensure_storage()
    except (MangaServiceError, OSError) as exc:
        return page_redirect(f"保存配置失败：{exc}", "error")
    return page_redirect("漫画下载配置已保存")


@router.post("/manga/jobs/download")
async def create_download_job(
    jmid: str = Form(...),
    format: str = Form("pdf"),
    duration_ms: str = Form(""),
    cover_duration_ms: str = Form(""),
    loop: str = Form(""),
    resize: str = Form(""),
    cover: UploadFile | None = File(None),
):
    try:
        job = await manga_service.create_download_job(jmid, format, duration_ms, cover_duration_ms, loop, resize, cover)
    except MangaServiceError as exc:
        return error_response(exc)
    return JSONResponse(status_code=202, content=job)


@router.post("/manga/jobs/compose")
async def create_compose_job(
    cover: UploadFile = File(...),
    frames: list[UploadFile] = File(...),
    duration_ms: str = Form(""),
    cover_duration_ms: str = Form(""),
    loop: str = Form(""),
    resize: str = Form(""),
):
    try:
        job = await manga_service.create_compose_job(cover, frames, duration_ms, cover_duration_ms, loop, resize)
    except MangaServiceError as exc:
        return error_response(exc)
    return JSONResponse(status_code=202, content=job)


@router.get("/api/manga/jobs/{job_id}")
def manga_job_status(job_id: int):
    job = manga_service.get_job(job_id)
    if job is None:
        return error_response(MangaServiceError("job_missing", "漫画任务不存在", 404))
    return job


@router.get("/manga/jobs/{job_id}/download")
def download_manga_job(job_id: int):
    try:
        path, filename = manga_service.get_download(job_id)
    except MangaServiceError as exc:
        return error_response(exc)
    media_type = "application/pdf" if path.suffix.lower() == ".pdf" else "image/png"
    return FileResponse(path, media_type=media_type, filename=filename)


@router.post("/manga/jobs/{job_id}/delete")
def delete_manga_job(job_id: int):
    try:
        manga_service.delete_job(job_id)
    except MangaServiceError as exc:
        return page_redirect(exc.message, "error")
    return page_redirect("漫画任务已删除")
