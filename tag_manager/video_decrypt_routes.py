from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .db import BASE_DIR
from .video_decrypt_service import VideoDecryptServiceError, video_decrypt_service

router = APIRouter(tags=["视频解密"])
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def error_response(error: VideoDecryptServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": error.code, "message": error.message}},
    )


@router.get("/video-decrypt", response_class=HTMLResponse)
def video_decrypt_page(
    request: Request,
    message: str = "",
    message_type: str = "",
):
    runtime = video_decrypt_service.inspect_runtime()
    jobs = video_decrypt_service.list_jobs()
    return templates.TemplateResponse(
        request,
        "video_decrypt.html",
        {
            "runtime": runtime,
            "jobs": jobs,
            "message": message,
            "message_type": message_type,
        },
    )


@router.post("/video-decrypt/jobs")
async def create_video_decrypt_job(
    file: UploadFile = File(...),
    password: str = Form(...),
    output_name: str = Form(""),
):
    try:
        job = await video_decrypt_service.create_job(file, password, output_name)
    except VideoDecryptServiceError as exc:
        return error_response(exc)
    return JSONResponse(status_code=202, content=job)


@router.get("/api/video-decrypt/jobs/{job_id}")
def video_decrypt_job_status(job_id: int):
    job = video_decrypt_service.get_job(job_id)
    if job is None:
        return error_response(VideoDecryptServiceError("job_missing", "视频解密任务不存在", 404))
    return job


@router.get("/video-decrypt/jobs/{job_id}/download")
def download_video_decrypt_job(job_id: int):
    try:
        path, filename = video_decrypt_service.get_download(job_id)
    except VideoDecryptServiceError as exc:
        return error_response(exc)
    return FileResponse(path, media_type="video/mp4", filename=filename)


@router.post("/video-decrypt/jobs/{job_id}/delete")
def delete_video_decrypt_job(job_id: int, request: Request):
    # 浏览器表单（Accept: text/html）保持 303 重定向兜底；fetch 等客户端返回 JSON 由前端 toast 反馈
    wants_json = "text/html" not in request.headers.get("accept", "")
    try:
        video_decrypt_service.delete_job(job_id)
    except VideoDecryptServiceError as exc:
        if wants_json:
            return error_response(exc)
        query = urlencode({"message": exc.message, "message_type": "error"})
        return RedirectResponse(f"/video-decrypt?{query}", status_code=303)
    if wants_json:
        return JSONResponse({"ok": True, "message": "视频解密任务已删除"})
    query = urlencode({"message": "视频解密任务已删除", "message_type": "success"})
    return RedirectResponse(f"/video-decrypt?{query}", status_code=303)
