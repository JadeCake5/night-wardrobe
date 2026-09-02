from __future__ import annotations

from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
RESIZE_STRATEGIES = ("pad", "stretch", "crop")
RESIZE_LABELS = {"pad": "居中留白", "stretch": "拉伸", "crop": "居中裁剪"}
DEFAULT_DURATION_MS = 500
DEFAULT_COVER_DURATION_MS = 2000
DEFAULT_LOOP = 0
MAX_APNG_FRAMES = 500


class MangaComposeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def list_image_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    files = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
    return sorted(files, key=lambda p: p.name)


def compose_pdf(image_paths: list[Path], output_path: Path) -> Path:
    if not image_paths:
        raise MangaComposeError("empty_frames", "没有可用于合成的图片")
    try:
        import img2pdf
    except ImportError as exc:
        raise MangaComposeError("missing_dependency", "缺少 img2pdf 依赖，请先 pip install img2pdf") from exc
    try:
        data = img2pdf.convert([str(p) for p in image_paths])
    except Exception as exc:
        raise MangaComposeError("pdf_compose_failed", f"PDF 合成失败：{exc}") from exc
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as f:
        f.write(data)
    return output_path


def _normalize_frame(img, size, strategy: str):
    from PIL import Image

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    if img.size == size:
        return img
    if strategy == "stretch":
        return img.resize(size, Image.LANCZOS)
    if strategy == "crop":
        src_ratio = img.width / img.height
        dst_ratio = size[0] / size[1]
        if src_ratio > dst_ratio:
            new_width = int(img.height * dst_ratio)
            left = (img.width - new_width) // 2
            img = img.crop((left, 0, left + new_width, img.height))
        else:
            new_height = int(img.width / dst_ratio)
            top = (img.height - new_height) // 2
            img = img.crop((0, top, img.width, top + new_height))
        return img.resize(size, Image.LANCZOS)
    # 默认 pad：等比缩放到能放进目标尺寸，黑边居中
    img.thumbnail(size, Image.LANCZOS)
    canvas = Image.new("RGB", size, (0, 0, 0))
    offset = ((size[0] - img.width) // 2, (size[1] - img.height) // 2)
    canvas.paste(img, offset)
    return canvas


def compose_apng(
    first_frame: Path,
    frame_paths: list[Path],
    output_path: Path,
    *,
    duration_ms: int = DEFAULT_DURATION_MS,
    cover_duration_ms: int | None = None,
    loop: int = DEFAULT_LOOP,
    resize: str = "pad",
) -> Path:
    from PIL import Image

    if resize not in RESIZE_STRATEGIES:
        raise MangaComposeError("invalid_resize", f"尺寸归一化策略必须是 {'/'.join(RESIZE_STRATEGIES)}")
    if not first_frame or not Path(first_frame).is_file():
        raise MangaComposeError("cover_missing", "APNG 首帧图片不存在")
    if not frame_paths:
        raise MangaComposeError("empty_frames", "没有可用于合成的帧图片")
    if len(frame_paths) + 1 > MAX_APNG_FRAMES:
        raise MangaComposeError("too_many_frames", f"帧数超过上限 {MAX_APNG_FRAMES}")
    duration_ms = max(10, min(int(duration_ms), 60000))
    durations: int | list[int] = duration_ms
    if cover_duration_ms is not None:
        # 首帧独立停留时长：Pillow 支持 duration 列表逐帧取值
        durations = [max(10, min(int(cover_duration_ms), 60000))] + [duration_ms] * len(frame_paths)
    loop = max(0, int(loop))

    try:
        base = Image.open(first_frame)
        base.load()
        if base.mode not in ("RGB", "RGBA"):
            base = base.convert("RGB")
        size = base.size
        frames = []
        for path in frame_paths:
            with Image.open(path) as img:
                img.load()
                frames.append(_normalize_frame(img, size, resize))
    except MangaComposeError:
        raise
    except Exception as exc:
        raise MangaComposeError("image_decode_failed", f"帧图片解码失败：{exc}") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        base.save(
            output_path,
            format="PNG",
            save_all=True,
            append_images=frames,
            duration=durations,
            loop=loop,
            disposal=0,
            blend=0,
        )
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        raise MangaComposeError("apng_compose_failed", f"APNG 合成失败：{exc}") from exc
    return output_path
