from __future__ import annotations

import io
import json
import re
import threading
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image

from .db import BASE_DIR, PROJECT_DIR, connect, init_db

GALLERY_DIR = BASE_DIR / "gallery"
OLD_GALLERY_DIR = PROJECT_DIR / "提示词图库"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
LORA_RE = re.compile(r"<lora:([^:>]+)(?::([^>]+))?>", re.IGNORECASE)
USER_COMMENT_TAG = 37510
EXIF_IFD_TAG = 34665
EXIF_IFD_POINTER_TAGS = {34665, 34853, 40965}
_SCAN_LOCK = threading.Lock()


def ensure_gallery_dir() -> None:
    GALLERY_DIR.mkdir(exist_ok=True)


def iter_images(root: Path = GALLERY_DIR):
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            yield path


def clean_exif_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        prefixes = [
            (b"UNICODE\x00", "utf-16-be"),
            (b"ASCII\x00\x00\x00", "utf-8"),
            (b"JIS\x00\x00\x00\x00\x00", "shift_jis"),
        ]
        for prefix, encoding in prefixes:
            if value.startswith(prefix):
                value = value[len(prefix):]
                try:
                    return value.decode(encoding, errors="ignore").replace("\x00", "").strip()
                except Exception:
                    return ""
        for encoding in ("utf-8", "utf-16", "utf-16-le", "utf-16-be"):
            try:
                return value.decode(encoding, errors="ignore").replace("\x00", "").strip()
            except Exception:
                continue
        return ""
    return str(value).replace("\x00", "").strip()


def metadata_value_to_text(value: Any) -> str:
    if isinstance(value, bytes):
        text = clean_exif_text(value)
        return text if text else value.hex()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def read_image_metadata(path: Path) -> dict[str, str]:
    try:
        with Image.open(path) as img:
            meta = {str(k): metadata_value_to_text(v) for k, v in img.info.items() if k != "exif"}
            source = "Pillow"
            try:
                exif = img.getexif()
            except Exception:
                exif = None
            if exif:
                entries = list(exif.items())
                try:
                    entries.extend(exif.get_ifd(EXIF_IFD_TAG).items())
                except Exception:
                    pass
                for key, value in entries:
                    if key in EXIF_IFD_POINTER_TAGS:
                        continue
                    label = str(key)
                    text = clean_exif_text(value)
                    if text:
                        meta.setdefault(label, text)
                    if key == USER_COMMENT_TAG and text:
                        meta["parameters"] = text
                        source = "EXIF UserComment"
            if "workflow" in meta or "prompt" in meta:
                source = "ComfyUI"
            elif "parameters" in meta and source != "EXIF UserComment":
                source = "SD WebUI"
            meta["_metadata_source"] = source
            meta["_metadata_json"] = json.dumps({k: v for k, v in meta.items() if not k.startswith("_")}, ensure_ascii=False, indent=2)
            return meta
    except Exception:
        return {}


def parse_json(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return None


def find_ksampler_connections(prompt_data: dict) -> tuple[str, str]:
    if not isinstance(prompt_data, dict):
        return "", ""

    positive_node_id = ""
    negative_node_id = ""

    for node_id, node in prompt_data.items():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type", "")
        if "KSampler" not in class_type:
            continue
        inputs = node.get("inputs", {})
        pos_input = inputs.get("positive")
        neg_input = inputs.get("negative")
        if isinstance(pos_input, list) and len(pos_input) >= 1:
            positive_node_id = str(pos_input[0])
        if isinstance(neg_input, list) and len(neg_input) >= 1:
            negative_node_id = str(neg_input[0])
        if positive_node_id:
            break

    def trace_text(node_id: str, want: str = "", visited: set | None = None) -> str:
        if visited is None:
            visited = set()
        if node_id in visited or node_id not in prompt_data:
            return ""
        visited.add(node_id)
        node = prompt_data[node_id]
        if not isinstance(node, dict):
            return ""
        inputs = node.get("inputs", {})
        class_type = node.get("class_type", "")
        if isinstance(inputs, dict):
            text = inputs.get("text", "")
            if isinstance(text, str) and text.strip() and ("Text" in class_type or "CLIPTextEncode" in class_type or "String" in class_type):
                return text.strip()
            if isinstance(text, list) and len(text) >= 1:
                result = trace_text(str(text[0]), want, visited)
                if result:
                    return result
            if want:
                direct = inputs.get(want)
                if isinstance(direct, str) and direct.strip():
                    return direct.strip()
                if isinstance(direct, list) and len(direct) >= 1:
                    result = trace_text(str(direct[0]), want, visited)
                    if result:
                        return result
            clip_input = inputs.get("conditioning") or inputs.get("clip")
            if isinstance(clip_input, list) and len(clip_input) >= 1:
                result = trace_text(str(clip_input[0]), want, visited)
                if result:
                    return result
        return ""

    positive = trace_text(positive_node_id, "positive") if positive_node_id else ""
    negative = trace_text(negative_node_id, "negative") if negative_node_id else ""
    return positive, negative


def find_text_inputs(data: Any) -> list[str]:
    found: list[str] = []
    if isinstance(data, dict):
        class_type = data.get("class_type", "")
        inputs = data.get("inputs", {})
        if isinstance(inputs, dict) and ("text" in inputs) and ("Text" in class_type or "CLIPTextEncode" in class_type):
            text = inputs.get("text")
            if isinstance(text, str) and text.strip():
                found.append(text.strip())
        for value in data.values():
            found.extend(find_text_inputs(value))
    elif isinstance(data, list):
        for item in data:
            found.extend(find_text_inputs(item))
    return found


def find_checkpoints_and_loras(data: Any) -> tuple[str, list[str]]:
    checkpoint = ""
    loras: list[str] = []
    if isinstance(data, dict):
        inputs = data.get("inputs", {})
        if isinstance(inputs, dict):
            ckpt = inputs.get("ckpt_name")
            if isinstance(ckpt, str) and ckpt and not checkpoint:
                checkpoint = ckpt
            lora = inputs.get("lora_name")
            if isinstance(lora, str) and lora:
                strength = inputs.get("strength_model", "")
                loras.append(f"{lora}:{strength}" if strength != "" else lora)
        for value in data.values():
            child_ckpt, child_loras = find_checkpoints_and_loras(value)
            checkpoint = checkpoint or child_ckpt
            loras.extend(child_loras)
    elif isinstance(data, list):
        for item in data:
            child_ckpt, child_loras = find_checkpoints_and_loras(item)
            checkpoint = checkpoint or child_ckpt
            loras.extend(child_loras)
    return checkpoint, loras


def split_a1111_parameters(parameters: str) -> tuple[str, str, str]:
    text = (parameters or "").strip()
    if not text:
        return "", "", ""
    steps_match = re.search(r"(?:^|\n)Steps:\s*", text)
    prompt_part = text[:steps_match.start()].strip() if steps_match else text
    params_part = text[steps_match.start():].strip() if steps_match else ""
    negative_marker = "Negative prompt:"
    if negative_marker in prompt_part:
        positive, negative = prompt_part.split(negative_marker, 1)
    else:
        positive, negative = prompt_part, ""
    return positive.strip(), negative.strip(), params_part.strip()


def parse_key_value_params(params_part: str) -> dict[str, str]:
    params: dict[str, str] = {}
    text = params_part.strip()
    if text.startswith("Steps:"):
        text = text[len("Steps:"):].strip()
        first, sep, rest = text.partition(",")
        if first.strip():
            params["Steps"] = first.strip()
        text = rest if sep else ""
    for part in re.split(r",\s*", text):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            params[key] = value
    return params


def find_loras_in_text(text: str) -> list[str]:
    loras: list[str] = []
    for name, strength in LORA_RE.findall(text or ""):
        loras.append(f"{name}:{strength}" if strength else name)
    return loras


def unique_join(items: list[str]) -> str:
    return ", ".join(dict.fromkeys(item for item in items if item))


def parse_a1111_parameters(parameters: str) -> dict[str, Any]:
    positive, negative, params_part = split_a1111_parameters(parameters)
    params = parse_key_value_params(params_part)
    loras = find_loras_in_text(positive) + find_loras_in_text(negative)
    checkpoint = params.get("Model", "") or params.get("Model hash", "")
    generation_params = json.dumps(params, ensure_ascii=False, indent=2) if params else params_part
    return {
        "positive": positive,
        "negative": negative,
        "params": params,
        "generation_params": generation_params,
        "checkpoint": checkpoint,
        "loras": loras,
    }


def extract_prompts(meta: dict[str, str]) -> tuple[str, str, str, str, str, str, str, str, str, str]:
    workflow_raw = meta.get("workflow", "")
    prompt_raw = meta.get("prompt", "")
    parameters = meta.get("parameters", "") or meta.get("Comment", "") or meta.get("Description", "")
    metadata_json = meta.get("_metadata_json", "")
    metadata_source = meta.get("_metadata_source", "")

    prompt_data = parse_json(prompt_raw)
    workflow_data = parse_json(workflow_raw)
    data = prompt_data or workflow_data

    positive, negative = "", ""
    generation_params = ""

    if prompt_data and isinstance(prompt_data, dict):
        positive, negative = find_ksampler_connections(prompt_data)

    if not positive and data is not None:
        texts = find_text_inputs(data)
        positive = texts[0] if texts else ""
        negative = texts[1] if len(texts) > 1 else ""

    checkpoint, loras = find_checkpoints_and_loras(data) if data is not None else ("", [])

    if parameters:
        a1111 = parse_a1111_parameters(parameters)
        positive = positive or a1111["positive"]
        negative = negative or a1111["negative"]
        checkpoint = checkpoint or a1111["checkpoint"]
        loras.extend(a1111["loras"])
        generation_params = a1111["generation_params"]
        if not metadata_source:
            metadata_source = "SD WebUI"

    if workflow_raw or prompt_raw:
        metadata_source = "ComfyUI"

    return positive, negative, workflow_raw, prompt_raw, checkpoint, unique_join(loras), parameters, metadata_json, metadata_source, generation_params


_UPSERT_SQL = """
    INSERT INTO gallery_images
        (path, title, category, positive_prompt, negative_prompt, workflow_json, prompt_json, parameters, checkpoint, loras, metadata_json, metadata_source, generation_params, file_mtime, file_size)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(path) DO UPDATE SET
        title=excluded.title,
        category=excluded.category,
        positive_prompt=excluded.positive_prompt,
        negative_prompt=excluded.negative_prompt,
        workflow_json=excluded.workflow_json,
        prompt_json=excluded.prompt_json,
        parameters=excluded.parameters,
        checkpoint=excluded.checkpoint,
        loras=excluded.loras,
        metadata_json=excluded.metadata_json,
        metadata_source=excluded.metadata_source,
        generation_params=excluded.generation_params,
        file_mtime=excluded.file_mtime,
        file_size=excluded.file_size,
        updated_at=CURRENT_TIMESTAMP
"""


def ingest_image(conn, path: Path, root: Path = GALLERY_DIR) -> None:
    """单张图片解析入库（含文件指纹，供增量扫描跳过未变化文件）。"""
    rel = path.relative_to(GALLERY_DIR).as_posix()
    stat = path.stat()
    meta = read_image_metadata(path)
    positive, negative, workflow_raw, prompt_raw, checkpoint, loras, parameters, metadata_json, metadata_source, generation_params = extract_prompts(meta)
    category = path.parent.name if path.parent != root else ""
    conn.execute(
        _UPSERT_SQL,
        (rel, path.stem, category, positive, negative, workflow_raw, prompt_raw, parameters, checkpoint, loras, metadata_json, metadata_source, generation_params, stat.st_mtime, stat.st_size),
    )


def ingest_saved_paths(paths: list[Path], *, initialize_db: bool = True) -> int:
    """定向入库：只处理给定的新增文件，上传/导入后无需全库扫描。"""
    if not paths:
        return 0
    with _SCAN_LOCK:
        ensure_gallery_dir()
        if initialize_db:
            init_db()
        count = 0
        with connect() as conn:
            for path in paths:
                path = Path(path)
                if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                    ingest_image(conn, path)
                    count += 1
        return count


def scan_gallery(root: Path = GALLERY_DIR, *, initialize_db: bool = True) -> int:
    root = Path(root)
    with _SCAN_LOCK:
        ensure_gallery_dir()
        if initialize_db:
            init_db()
        count = 0
        seen_paths: set[str] = set()
        with connect() as conn:
            fingerprints = {
                row["path"]: (row["file_mtime"], row["file_size"])
                for row in conn.execute("SELECT path, file_mtime, file_size FROM gallery_images")
            }
            for path in iter_images(root):
                rel = path.relative_to(GALLERY_DIR).as_posix()
                seen_paths.add(rel)
                stat = path.stat()
                if fingerprints.get(rel) == (stat.st_mtime, stat.st_size):
                    continue
                ingest_image(conn, path, root)
                count += 1

            if root.resolve() == GALLERY_DIR.resolve():
                known_paths = set(fingerprints)
                missing_paths = known_paths - seen_paths
                if missing_paths:
                    conn.executemany(
                        "DELETE FROM gallery_images WHERE path = ?",
                        ((path,) for path in missing_paths),
                    )
        return count


def export_gallery_zip() -> bytes:
    ensure_gallery_dir()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in iter_images(GALLERY_DIR):
            arcname = path.relative_to(GALLERY_DIR).as_posix()
            zf.write(path, arcname)
    return buf.getvalue()


def safe_gallery_name(name: str) -> str:
    suffix = Path(name or "image.png").suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        raise ValueError("图片格式不支持")
    stem = Path(name or "image").stem.strip() or "image"
    stem = re.sub(r'[\\/:*?"<>|]+', "_", stem)
    stem = re.sub(r"\s+", "_", stem).strip("._ ") or "image"
    return f"{stem}{suffix}"


def safe_gallery_relative_path(path: str | Path) -> Path:
    raw = str(path or "image.png").replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ValueError("图片路径不合法")
    parts = [part.strip() for part in raw.split("/") if part.strip()]
    if not parts or any(part in (".", "..") for part in parts):
        raise ValueError("图片路径不合法")
    folders = [re.sub(r'[\\/:*?"<>|]+', "_", part).strip("._ ") for part in parts[:-1]]
    folders = [part for part in folders if part]
    return Path(*folders, safe_gallery_name(parts[-1]))


def unique_gallery_path(filename: str | Path) -> Path:
    ensure_gallery_dir()
    target = GALLERY_DIR / safe_gallery_relative_path(filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    for index in range(2, 10000):
        candidate = target.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("无法生成不重复的图片文件名")


def save_gallery_bytes(data: bytes, filename: str | Path) -> Path:
    target = unique_gallery_path(filename)
    Image.open(io.BytesIO(data)).verify()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def import_gallery_zip(data: bytes, folder: str = "") -> list[Path]:
    ensure_gallery_dir()
    folder = safe_gallery_relative_path(f"{folder}/placeholder.png").parent.as_posix() if folder else ""
    saved: list[Path] = []
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        for info in zf.infolist():
            if info.is_dir() or Path(info.filename).suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            try:
                rel = safe_gallery_relative_path(info.filename)
            except ValueError:
                continue
            filename = Path(folder) / rel if folder else rel
            with zf.open(info) as src:
                payload = src.read()
            saved.append(save_gallery_bytes(payload, filename))
    return saved


if __name__ == "__main__":
    print(scan_gallery())
