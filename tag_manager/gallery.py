from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image

from .db import BASE_DIR, PROJECT_DIR, connect, init_db

GALLERY_DIR = BASE_DIR / "gallery"
OLD_GALLERY_DIR = PROJECT_DIR / "提示词图库"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def ensure_gallery_dir() -> None:
    GALLERY_DIR.mkdir(exist_ok=True)


def iter_images(root: Path = GALLERY_DIR):
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            yield path


def read_image_metadata(path: Path) -> dict[str, str]:
    try:
        with Image.open(path) as img:
            return {str(k): str(v) for k, v in img.info.items()}
    except Exception:
        return {}


def parse_json(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return None


def find_ksampler_connections(prompt_data: dict) -> tuple[str, str]:
    """通过 KSampler 节点的 positive/negative 输入连接，精确定位正/负提示词。"""
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

    def trace_text(node_id: str, visited: set | None = None) -> str:
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
                return trace_text(str(text[0]), visited)
            clip_input = inputs.get("conditioning") or inputs.get("clip")
            if isinstance(clip_input, list) and len(clip_input) >= 1:
                result = trace_text(str(clip_input[0]), visited)
                if result:
                    return result
        return ""

    positive = trace_text(positive_node_id) if positive_node_id else ""
    negative = trace_text(negative_node_id) if negative_node_id else ""
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


def extract_prompts(meta: dict[str, str]) -> tuple[str, str, str, str, str, str]:
    workflow_raw = meta.get("workflow", "")
    prompt_raw = meta.get("prompt", "")
    parameters = meta.get("parameters", "") or meta.get("Comment", "")

    prompt_data = parse_json(prompt_raw)
    workflow_data = parse_json(workflow_raw)
    data = prompt_data or workflow_data

    positive, negative = "", ""

    # 优先通过 KSampler 连接精确匹配
    if prompt_data and isinstance(prompt_data, dict):
        positive, negative = find_ksampler_connections(prompt_data)

    # 回退到遍历所有文本节点
    if not positive and data is not None:
        texts = find_text_inputs(data)
        positive = texts[0] if texts else ""
        negative = texts[1] if len(texts) > 1 else ""

    checkpoint, loras = find_checkpoints_and_loras(data) if data is not None else ("", [])
    return positive, negative, workflow_raw, prompt_raw, checkpoint, ", ".join(dict.fromkeys(loras))


def scan_gallery(root: Path = GALLERY_DIR) -> int:
    ensure_gallery_dir()
    init_db()
    count = 0
    with connect() as conn:
        for path in iter_images(root):
            rel = path.relative_to(GALLERY_DIR).as_posix()
            meta = read_image_metadata(path)
            positive, negative, workflow_raw, prompt_raw, checkpoint, loras = extract_prompts(meta)
            category = path.parent.name if path.parent != root else ""
            conn.execute(
                """
                INSERT INTO gallery_images
                    (path, title, category, positive_prompt, negative_prompt, workflow_json, prompt_json, parameters, checkpoint, loras)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    updated_at=CURRENT_TIMESTAMP
                """,
                (rel, path.stem, category, positive, negative, workflow_raw, prompt_raw, meta.get("parameters", ""), checkpoint, loras),
            )
            count += 1
    return count


def export_gallery_zip() -> bytes:
    """将 gallery 目录打包为 ZIP 返回字节。"""
    ensure_gallery_dir()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in iter_images(GALLERY_DIR):
            arcname = path.relative_to(GALLERY_DIR).as_posix()
            zf.write(path, arcname)
    return buf.getvalue()


def import_gallery_zip(data: bytes) -> int:
    """从 ZIP 字节解压到 gallery 目录，返回文件数。"""
    ensure_gallery_dir()
    count = 0
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            ext = Path(info.filename).suffix.lower()
            if ext not in IMAGE_EXTENSIONS:
                continue
            target = GALLERY_DIR / info.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
            count += 1
    return count


if __name__ == "__main__":
    print(scan_gallery())
