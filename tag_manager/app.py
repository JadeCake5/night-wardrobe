from __future__ import annotations

import json
import os
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import BASE_DIR, PROJECT_DIR, connect, init_db, upsert_category, upsert_character, upsert_recipe, upsert_tag, add_outfit
from .gallery import GALLERY_DIR, export_gallery_zip, import_gallery_zip, scan_gallery
from .import_magic_book import import_magic_book
from .llm import chat_completion

DEV_MODE = os.environ.get("WARDROBE_DEV", "").lower() in ("1", "true", "yes")

app = FastAPI(title="夜之主衣柜")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["dev_mode"] = DEV_MODE
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
GALLERY_DIR.mkdir(exist_ok=True)
app.mount("/gallery-files", StaticFiles(directory=str(GALLERY_DIR)), name="gallery_files")


@app.on_event("startup")
def startup() -> None:
    init_db()


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def tag_url(**updates: str) -> str:
    params = {key: value for key, value in updates.items() if value}
    query = urlencode(params)
    return f"/tags?{query}" if query else "/tags"


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    with connect() as conn:
        stats = {
            "tags": conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0],
            "characters": conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0],
            "recipes": conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0],
            "images": conn.execute("SELECT COUNT(*) FROM gallery_images").fetchone()[0],
        }
        recent_images = conn.execute("SELECT * FROM gallery_images ORDER BY updated_at DESC LIMIT 8").fetchall()
    return templates.TemplateResponse("index.html", {"request": request, "stats": stats, "recent_images": recent_images})


@app.post("/import-magic-book")
def import_magic_book_route():
    import_magic_book()
    return redirect("/tags")


@app.get("/tags", response_class=HTMLResponse)
def tags(request: Request, q: str = "", category: str = "", subcategory: str = ""):
    query = "SELECT * FROM tags WHERE 1=1"
    count_query = "SELECT COUNT(*) FROM tags WHERE 1=1"
    params: list[str] = []
    count_params: list[str] = []
    if q:
        query += " AND (tag LIKE ? OR zh LIKE ? OR notes LIKE ?)"
        count_query += " AND (tag LIKE ? OR zh LIKE ? OR notes LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like, like])
        count_params.extend([like, like, like])
    if category:
        query += " AND category = ?"
        count_query += " AND category = ?"
        params.append(category)
        count_params.append(category)
    if subcategory:
        query += " AND subcategory = ?"
        count_query += " AND subcategory = ?"
        params.append(subcategory)
        count_params.append(subcategory)
    query += " ORDER BY rating DESC, category, subcategory, tag LIMIT 500"
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
        shown_count = conn.execute(count_query, count_params).fetchone()[0]
        total_count = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        categories = conn.execute(
            """
            SELECT c.name AS category, COUNT(t.id) AS count
            FROM categories c
            LEFT JOIN tags t ON t.category = c.name
            WHERE c.kind IN ('tag', 'both')
            GROUP BY c.name, c.sort_order
            ORDER BY c.sort_order, c.name
            """
        ).fetchall()
        subcategories = conn.execute(
            """
            SELECT COALESCE(NULLIF(subcategory, ''), '未分类') AS subcategory, COUNT(*) AS count
            FROM tags
            WHERE (? = '' OR category = ?)
              AND (? = '' OR tag LIKE ? OR zh LIKE ? OR notes LIKE ?)
            GROUP BY COALESCE(NULLIF(subcategory, ''), '未分类')
            ORDER BY MIN(id)
            """,
            (category, category, q, f"%{q}%", f"%{q}%", f"%{q}%"),
        ).fetchall()
    return templates.TemplateResponse(
        "tags.html",
        {
            "request": request,
            "rows": rows,
            "q": q,
            "category": category,
            "subcategory": subcategory,
            "categories": categories,
            "subcategories": subcategories,
            "shown_count": shown_count,
            "total_count": total_count,
            "tag_url": tag_url,
        },
    )


@app.post("/categories/add")
def add_category(name: str = Form(...), kind: str = Form("tag"), sort_order: int = Form(100), notes: str = Form("")):
    upsert_category(name=name, kind=kind, sort_order=sort_order, notes=notes)
    return redirect("/tags")


@app.post("/tags/add")
def add_tag(tag: str = Form(...), zh: str = Form(""), category: str = Form(""), subcategory: str = Form(""), notes: str = Form("")):
    upsert_tag(tag=tag, zh=zh, category=category, subcategory=subcategory, source="手工添加", notes=notes)
    return redirect("/tags")


@app.post("/tags/{tag_id}/update")
def update_tag(tag_id: int, tag: str = Form(...), zh: str = Form(""), category: str = Form(""), subcategory: str = Form(""), notes: str = Form("")):
    with connect() as conn:
        conn.execute(
            """
            UPDATE tags SET tag=?, zh=?, category=?, subcategory=?, notes=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (tag, zh, category, subcategory, notes, tag_id),
        )
    if category:
        upsert_category(category)
    return redirect("/tags")


@app.post("/tags/{tag_id}/delete")
def delete_tag(tag_id: int):
    with connect() as conn:
        conn.execute("DELETE FROM tags WHERE id=?", (tag_id,))
    return redirect("/tags")


@app.post("/categories/delete")
def delete_category(name: str = Form(...)):
    with connect() as conn:
        conn.execute("UPDATE tags SET category='' WHERE category=?", (name,))
        conn.execute("DELETE FROM categories WHERE name=?", (name,))
    return redirect("/tags")


@app.post("/subcategories/delete")
def delete_subcategory(category: str = Form(""), subcategory: str = Form("")):
    with connect() as conn:
        if category:
            conn.execute("UPDATE tags SET subcategory='' WHERE category=? AND subcategory=?", (category, subcategory))
        else:
            conn.execute("UPDATE tags SET subcategory='' WHERE subcategory=?", (subcategory,))
    return redirect("/tags")


TAG_LIBRARY_PATH = BASE_DIR / "tag_library.json"


@app.post("/export-tags")
def export_tags():
    with connect() as conn:
        categories = [dict(r) for r in conn.execute("SELECT name, kind, sort_order, notes FROM categories ORDER BY sort_order, name").fetchall()]
        tags = [dict(r) for r in conn.execute("SELECT tag, zh, category, subcategory, source, rating, notes FROM tags ORDER BY category, subcategory, tag").fetchall()]
    data = {"categories": categories, "tags": tags}
    TAG_LIBRARY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return redirect("/")


@app.post("/import-tags")
def import_tags():
    if not TAG_LIBRARY_PATH.exists():
        return redirect("/")
    data = json.loads(TAG_LIBRARY_PATH.read_text(encoding="utf-8"))
    for cat in data.get("categories", []):
        upsert_category(name=cat["name"], kind=cat.get("kind", "tag"), sort_order=cat.get("sort_order", 0), notes=cat.get("notes", ""))
    for t in data.get("tags", []):
        upsert_tag(tag=t["tag"], zh=t.get("zh", ""), category=t.get("category", ""), subcategory=t.get("subcategory", ""), source=t.get("source", ""), notes=t.get("notes", ""))
    return redirect("/tags")


@app.get("/gallery", response_class=HTMLResponse)
def gallery(request: Request, q: str = "", category: str = "", checkpoint: str = ""):
    query = "SELECT * FROM gallery_images WHERE 1=1"
    params: list[str] = []
    if q:
        query += " AND (title LIKE ? OR category LIKE ? OR positive_prompt LIKE ? OR loras LIKE ? OR notes LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like, like, like, like])
    if category:
        query += " AND category = ?"
        params.append(category)
    if checkpoint:
        query += " AND checkpoint LIKE ?"
        params.append(f"%{checkpoint}%")
    query += " ORDER BY updated_at DESC LIMIT 120"
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
        categories = conn.execute("SELECT DISTINCT category FROM gallery_images WHERE category != '' ORDER BY category").fetchall()
        checkpoints = conn.execute("SELECT DISTINCT checkpoint FROM gallery_images WHERE checkpoint != '' ORDER BY checkpoint").fetchall()
    return templates.TemplateResponse(
        "gallery.html",
        {"request": request, "rows": rows, "q": q, "category": category, "checkpoint": checkpoint, "categories": categories, "checkpoints": checkpoints},
    )


@app.post("/scan-gallery")
def scan_gallery_route():
    scan_gallery()
    return redirect("/gallery")


@app.post("/gallery/export")
def gallery_export():
    data = export_gallery_zip()
    return Response(content=data, media_type="application/zip", headers={"Content-Disposition": "attachment; filename=gallery_export.zip"})


@app.post("/gallery/import")
async def gallery_import(file: UploadFile = File(...)):
    data = await file.read()
    import_gallery_zip(data)
    scan_gallery()
    return redirect("/gallery")


@app.get("/llm", response_class=HTMLResponse)
def llm_page(request: Request):
    with connect() as conn:
        settings = conn.execute("SELECT * FROM llm_settings WHERE id=1").fetchone()
    return templates.TemplateResponse("llm.html", {"request": request, "settings": settings, "answer": "", "message": ""})


@app.post("/llm/settings")
def save_llm_settings(base_url: str = Form(""), api_key: str = Form(""), model: str = Form(""), default_system_prompt: str = Form("")):
    with connect() as conn:
        conn.execute(
            "UPDATE llm_settings SET base_url=?, api_key=?, model=?, default_system_prompt=? WHERE id=1",
            (base_url, api_key, model, default_system_prompt),
        )
    return redirect("/llm")


@app.post("/llm/chat", response_class=HTMLResponse)
def llm_chat(request: Request, message: str = Form(...)):
    with connect() as conn:
        settings = conn.execute("SELECT * FROM llm_settings WHERE id=1").fetchone()
    try:
        answer = chat_completion(settings["base_url"], settings["api_key"], settings["model"], settings["default_system_prompt"], message)
    except Exception as exc:
        answer = f"请求失败：{exc}"
    return templates.TemplateResponse("llm.html", {"request": request, "settings": settings, "answer": answer, "message": message})


# ─── 配方库 ───────────────────────────────────────────────────────────────────

RECIPE_TYPES = [
    ("artist_mix", "画师串"),
    ("scene", "场景预设"),
    ("negative", "负面模板"),
    ("params", "绘图参数"),
]


@app.get("/recipes", response_class=HTMLResponse)
def recipes(request: Request, type: str = "", q: str = ""):
    query = "SELECT * FROM recipes WHERE 1=1"
    params: list[str] = []
    if type:
        query += " AND type = ?"
        params.append(type)
    if q:
        query += " AND (name LIKE ? OR positive_prompt LIKE ? OR negative_prompt LIKE ? OR notes LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like, like, like])
    query += " ORDER BY type, updated_at DESC LIMIT 200"
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
        counts = conn.execute(
            "SELECT type, COUNT(*) as count FROM recipes GROUP BY type"
        ).fetchall()
    count_map = {r["type"]: r["count"] for r in counts}
    return templates.TemplateResponse(
        "recipes.html",
        {"request": request, "rows": rows, "type": type, "q": q, "recipe_types": RECIPE_TYPES, "count_map": count_map},
    )


@app.post("/recipes/add")
def add_recipe(
    name: str = Form(...),
    type: str = Form("scene"),
    positive_prompt: str = Form(""),
    negative_prompt: str = Form(""),
    params_json: str = Form(""),
    notes: str = Form(""),
):
    upsert_recipe(name=name, type=type, positive_prompt=positive_prompt, negative_prompt=negative_prompt, params_json=params_json, notes=notes, source="手工添加")
    return redirect("/recipes")


@app.post("/recipes/{recipe_id}/update")
def update_recipe(
    recipe_id: int,
    name: str = Form(...),
    type: str = Form("scene"),
    positive_prompt: str = Form(""),
    negative_prompt: str = Form(""),
    params_json: str = Form(""),
    notes: str = Form(""),
):
    with connect() as conn:
        conn.execute(
            """
            UPDATE recipes SET name=?, type=?, positive_prompt=?, negative_prompt=?, params_json=?, notes=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (name, type, positive_prompt, negative_prompt, params_json, notes, recipe_id),
        )
    return redirect("/recipes")


@app.post("/recipes/{recipe_id}/delete")
def delete_recipe(recipe_id: int):
    with connect() as conn:
        conn.execute("DELETE FROM recipes WHERE id=?", (recipe_id,))
    return redirect("/recipes")


# ─── 角色卡 ───────────────────────────────────────────────────────────────────


@app.get("/characters", response_class=HTMLResponse)
def characters(request: Request):
    with connect() as conn:
        rows = conn.execute("SELECT * FROM characters ORDER BY updated_at DESC").fetchall()
        outfits = conn.execute("SELECT * FROM character_outfits ORDER BY character_id, id").fetchall()
    outfit_map: dict[int, list] = {}
    for o in outfits:
        outfit_map.setdefault(o["character_id"], []).append(o)
    return templates.TemplateResponse("characters.html", {"request": request, "rows": rows, "outfit_map": outfit_map})


@app.post("/characters/add")
def add_character(
    name: str = Form(...),
    lora: str = Form(""),
    lora_weight: float = Form(1.0),
    trigger_words: str = Form(""),
    appearance: str = Form(""),
    notes: str = Form(""),
):
    upsert_character(name=name, lora=lora, lora_weight=lora_weight, trigger_words=trigger_words, appearance=appearance, notes=notes)
    return redirect("/characters")


@app.post("/characters/{char_id}/update")
def update_character(
    char_id: int,
    name: str = Form(...),
    lora: str = Form(""),
    lora_weight: float = Form(1.0),
    trigger_words: str = Form(""),
    appearance: str = Form(""),
    notes: str = Form(""),
):
    with connect() as conn:
        conn.execute(
            """
            UPDATE characters SET name=?, lora=?, lora_weight=?, trigger_words=?, appearance=?, notes=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (name, lora, lora_weight, trigger_words, appearance, notes, char_id),
        )
    return redirect("/characters")


@app.post("/characters/{char_id}/delete")
def delete_character(char_id: int):
    with connect() as conn:
        conn.execute("DELETE FROM characters WHERE id=?", (char_id,))
    return redirect("/characters")


@app.post("/characters/{char_id}/outfits/add")
def add_character_outfit(char_id: int, name: str = Form(...), tags: str = Form(""), notes: str = Form("")):
    add_outfit(char_id, name=name, tags=tags, notes=notes)
    return redirect("/characters")


@app.post("/characters/{char_id}/outfits/{outfit_id}/delete")
def delete_outfit(char_id: int, outfit_id: int):
    with connect() as conn:
        conn.execute("DELETE FROM character_outfits WHERE id=? AND character_id=?", (outfit_id, char_id))
    return redirect("/characters")


# ─── 工坊 ─────────────────────────────────────────────────────────────────────


@app.get("/workshop", response_class=HTMLResponse)
def workshop(request: Request):
    return templates.TemplateResponse("workshop.html", {"request": request})


# ─── 工坊 JSON API ────────────────────────────────────────────────────────────


@app.get("/api/characters")
def api_characters():
    with connect() as conn:
        rows = conn.execute("SELECT * FROM characters ORDER BY updated_at DESC").fetchall()
        outfits = conn.execute("SELECT * FROM character_outfits ORDER BY character_id, id").fetchall()
    outfit_map: dict[int, list] = {}
    for o in outfits:
        outfit_map.setdefault(o["character_id"], []).append({"id": o["id"], "name": o["name"], "tags": o["tags"]})
    result = []
    for r in rows:
        result.append({
            "id": r["id"], "name": r["name"], "lora": r["lora"], "lora_weight": r["lora_weight"],
            "trigger_words": r["trigger_words"], "appearance": r["appearance"],
            "outfits": outfit_map.get(r["id"], []),
        })
    return JSONResponse(result)


@app.get("/api/recipes")
def api_recipes(type: str = ""):
    query = "SELECT * FROM recipes"
    params: list[str] = []
    if type:
        query += " WHERE type = ?"
        params.append(type)
    query += " ORDER BY type, updated_at DESC"
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return JSONResponse([dict(r) for r in rows])


@app.post("/api/llm/optimize")
def api_llm_optimize(request_body: dict):
    prompt_text = request_body.get("prompt", "")
    with connect() as conn:
        settings = conn.execute("SELECT * FROM llm_settings WHERE id=1").fetchone()
    if not settings["base_url"] or not settings["model"]:
        return JSONResponse({"error": "LLM 未配置，请先在设置中配置 API"}, status_code=400)
    system = settings["default_system_prompt"] or "你是提示词优化助手，帮助用户优化 Stable Diffusion 提示词。保持英文 tag 格式，用逗号分隔。"
    user_msg = f"请优化以下提示词，使其更精确、更有表现力，保持相同风格和主题：\n\n{prompt_text}"
    try:
        answer = chat_completion(settings["base_url"], settings["api_key"], settings["model"], system, user_msg)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    return JSONResponse({"result": answer})
