from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .db import connect

API_VERSION = "v1"
MAX_BULK_ITEMS = 500
MAX_IMPORT_TAGS = 20000

TagName = Annotated[str, Field(min_length=1, max_length=1000)]
PositiveId = Annotated[int, Field(gt=0)]

router = APIRouter(
    prefix="/api/v1",
    tags=["Tag 库开放 API"],
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ErrorDetail(ApiModel):
    code: str = Field(description="稳定的机器可读错误码")
    message: str = Field(description="简体中文错误说明")


class ErrorResponse(ApiModel):
    detail: ErrorDetail


ERROR_RESPONSES = {
    400: {"model": ErrorResponse, "description": "请求不满足业务约束"},
    404: {"model": ErrorResponse, "description": "资源不存在"},
    409: {"model": ErrorResponse, "description": "唯一键冲突或资源仍被使用"},
}


class TagWrite(ApiModel):
    tag: str = Field(min_length=1, max_length=1000, examples=["1girl"])
    zh: str = Field(default="", max_length=2000, examples=["1名女性"])
    category: str = Field(default="", max_length=500, examples=["2.人物"])
    subcategory: str = Field(default="", max_length=500, examples=["人数"])
    source: str = Field(default="agent-api", max_length=1000, examples=["agent-api"])
    rating: int = Field(default=0, examples=[5])
    notes: str = Field(default="", max_length=10000)


class TagPatch(ApiModel):
    tag: str | None = Field(default=None, min_length=1, max_length=1000)
    zh: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=500)
    subcategory: str | None = Field(default=None, max_length=500)
    source: str | None = Field(default=None, max_length=1000)
    rating: int | None = None
    notes: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def require_change(self) -> "TagPatch":
        changes = self.model_dump(exclude_unset=True, exclude_none=True)
        if not changes:
            raise ValueError("至少提供一个非空更新字段")
        return self


class TagRecord(TagWrite):
    id: int
    created_at: str
    updated_at: str


class TagPage(ApiModel):
    items: list[TagRecord]
    total: int
    offset: int
    limit: int
    next_offset: int | None
    has_more: bool


class TagLookupRequest(ApiModel):
    tags: list[TagName] = Field(min_length=1, max_length=MAX_BULK_ITEMS)


class TagLookupResponse(ApiModel):
    items: list[TagRecord]
    missing: list[str]


class BulkTagUpsertRequest(ApiModel):
    items: list[TagWrite] = Field(min_length=1, max_length=MAX_BULK_ITEMS)


class BulkTagUpsertResponse(ApiModel):
    created: int
    updated: int
    items: list[TagRecord]


class BulkTagDeleteRequest(ApiModel):
    ids: list[PositiveId] = Field(default_factory=list, max_length=MAX_BULK_ITEMS)
    tags: list[TagName] = Field(default_factory=list, max_length=MAX_BULK_ITEMS)

    @model_validator(mode="after")
    def require_selector(self) -> "BulkTagDeleteRequest":
        if not self.ids and not self.tags:
            raise ValueError("ids 和 tags 至少提供一项")
        if len(set(self.ids)) + len(set(self.tags)) > MAX_BULK_ITEMS:
            raise ValueError(f"单次最多删除 {MAX_BULK_ITEMS} 条")
        return self


class DeleteResult(ApiModel):
    deleted: int
    ids: list[int]
    tags: list[str]


class SubcategorySummary(ApiModel):
    category: str
    name: str
    count: int


class CategoryWrite(ApiModel):
    name: str = Field(min_length=1, max_length=500, examples=["2.人物"])
    kind: Literal["tag", "group", "both"] = "tag"
    sort_order: int = 0
    notes: str = Field(default="", max_length=10000)


class CategoryPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=500)
    kind: Literal["tag", "group", "both"] | None = None
    sort_order: int | None = None
    notes: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def require_change(self) -> "CategoryPatch":
        if not self.model_dump(exclude_unset=True, exclude_none=True):
            raise ValueError("至少提供一个非空更新字段")
        return self


class CategoryRecord(CategoryWrite):
    id: int
    tag_count: int
    subcategories: list[SubcategorySummary]
    created_at: str
    updated_at: str


class CategoryList(ApiModel):
    items: list[CategoryRecord]
    total: int


class CategoryDeleteResult(ApiModel):
    deleted: int
    detached_tags: int


class SubcategoryRenameRequest(ApiModel):
    category: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=500)
    new_name: str = Field(min_length=1, max_length=500)


class SubcategoryClearRequest(ApiModel):
    category: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=500)


class SubcategoryMutationResult(ApiModel):
    affected_tags: int
    category: str
    old_name: str
    new_name: str


class TagLibrarySummary(ApiModel):
    api_version: str
    tag_count: int
    category_count: int
    subcategory_count: int
    latest_update: str | None
    max_bulk_items: int
    max_import_tags: int


class TagLibraryExport(ApiModel):
    api_version: str
    exported_at: str
    categories: list[CategoryWrite]
    tags: list[TagWrite]


class TagLibraryImportRequest(ApiModel):
    categories: list[CategoryWrite] = Field(default_factory=list, max_length=MAX_BULK_ITEMS)
    tags: list[TagWrite] = Field(default_factory=list, max_length=MAX_IMPORT_TAGS)

    @model_validator(mode="after")
    def require_data(self) -> "TagLibraryImportRequest":
        if not self.categories and not self.tags:
            raise ValueError("categories 和 tags 至少提供一项")
        return self


class TagLibraryImportResult(ApiModel):
    categories_upserted: int
    tags_created: int
    tags_updated: int


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def row_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def ensure_category(conn: sqlite3.Connection, category: str) -> None:
    if not category:
        return
    conn.execute(
        """
        INSERT INTO categories (name, kind, sort_order, notes)
        VALUES (?, 'tag', 0, '')
        ON CONFLICT(name) DO NOTHING
        """,
        (category,),
    )


def get_tag_or_404(conn: sqlite3.Connection, tag_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tags WHERE id=?", (tag_id,)).fetchone()
    if row is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "tag_not_found", f"Tag ID {tag_id} 不存在")
    return row


def get_category_or_404(conn: sqlite3.Connection, category_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
    if row is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "category_not_found", f"分类 ID {category_id} 不存在")
    return row


def category_record(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    tag_count = conn.execute("SELECT COUNT(*) FROM tags WHERE category=?", (row["name"],)).fetchone()[0]
    subcategories = [
        {"category": row["name"], "name": item["name"], "count": item["count"]}
        for item in conn.execute(
            """
            SELECT subcategory AS name, COUNT(*) AS count
            FROM tags
            WHERE category=? AND subcategory != ''
            GROUP BY subcategory
            ORDER BY subcategory
            """,
            (row["name"],),
        ).fetchall()
    ]
    return {
        **row_dict(row),
        "tag_count": tag_count,
        "subcategories": subcategories,
    }


TAG_COLUMNS = ("tag", "zh", "category", "subcategory", "source", "rating", "notes")


def insert_tag(conn: sqlite3.Connection, payload: TagWrite) -> sqlite3.Row:
    values = payload.model_dump()
    ensure_category(conn, values["category"])
    cursor = conn.execute(
        """
        INSERT INTO tags (tag, zh, category, subcategory, source, rating, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        tuple(values[column] for column in TAG_COLUMNS),
    )
    return get_tag_or_404(conn, int(cursor.lastrowid))


def replace_tag(conn: sqlite3.Connection, tag_id: int, payload: TagWrite) -> sqlite3.Row:
    get_tag_or_404(conn, tag_id)
    values = payload.model_dump()
    ensure_category(conn, values["category"])
    conn.execute(
        """
        UPDATE tags
        SET tag=?, zh=?, category=?, subcategory=?, source=?, rating=?, notes=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (*tuple(values[column] for column in TAG_COLUMNS), tag_id),
    )
    return get_tag_or_404(conn, tag_id)


def bulk_upsert_tags(conn: sqlite3.Connection, items: list[TagWrite]) -> tuple[int, int, list[dict]]:
    created = 0
    updated = 0
    records: list[dict] = []
    for payload in items:
        existing = conn.execute("SELECT id FROM tags WHERE tag=?", (payload.tag,)).fetchone()
        if existing is None:
            row = insert_tag(conn, payload)
            created += 1
        else:
            row = replace_tag(conn, int(existing["id"]), payload)
            updated += 1
        records.append(row_dict(row))
    return created, updated, records


@router.get(
    "/tag-library",
    response_model=TagLibrarySummary,
    summary="读取 Tag 库摘要",
)
def get_tag_library_summary() -> dict:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM tags) AS tag_count,
                (SELECT COUNT(*) FROM categories) AS category_count,
                (SELECT COUNT(DISTINCT category || char(31) || subcategory)
                 FROM tags WHERE subcategory != '') AS subcategory_count,
                (SELECT MAX(updated_at) FROM tags) AS latest_update
            """
        ).fetchone()
    return {
        "api_version": API_VERSION,
        "max_bulk_items": MAX_BULK_ITEMS,
        "max_import_tags": MAX_IMPORT_TAGS,
        **row_dict(row),
    }


@router.get(
    "/tags",
    response_model=TagPage,
    summary="分页查询 Tag",
)
def list_tags(
    q: str = Query(default="", description="模糊搜索英文 Tag、中文含义和备注"),
    tag: str = Query(default="", description="精确匹配英文 Tag"),
    category: str = Query(default=""),
    subcategory: str = Query(default=""),
    source: str = Query(default=""),
    min_rating: int | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    sort_by: Literal["rating", "tag", "updated_at", "created_at"] = Query(default="rating"),
    order: Literal["asc", "desc"] = Query(default="desc"),
) -> dict:
    clauses = ["1=1"]
    params: list[str | int] = []
    if q:
        clauses.append("(tag LIKE ? OR zh LIKE ? OR notes LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    for column, value in (("tag", tag), ("category", category), ("subcategory", subcategory), ("source", source)):
        if value:
            clauses.append(f"{column}=?")
            params.append(value)
    if min_rating is not None:
        clauses.append("rating>=?")
        params.append(min_rating)
    where = " AND ".join(clauses)
    sort_columns = {"rating": "rating", "tag": "tag", "updated_at": "updated_at", "created_at": "created_at"}
    direction = "ASC" if order == "asc" else "DESC"
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM tags WHERE {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM tags WHERE {where} ORDER BY {sort_columns[sort_by]} {direction}, id ASC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    next_offset = offset + len(rows)
    has_more = next_offset < total
    return {
        "items": [row_dict(row) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset if has_more else None,
        "has_more": has_more,
    }


@router.post(
    "/tags/lookup",
    response_model=TagLookupResponse,
    responses=ERROR_RESPONSES,
    summary="按英文名称批量查询 Tag",
)
def lookup_tags(payload: TagLookupRequest) -> dict:
    names = list(dict.fromkeys(payload.tags))
    placeholders = ",".join("?" for _ in names)
    with connect() as conn:
        rows = conn.execute(f"SELECT * FROM tags WHERE tag IN ({placeholders})", names).fetchall()
    by_name = {row["tag"]: row_dict(row) for row in rows}
    return {
        "items": [by_name[name] for name in names if name in by_name],
        "missing": [name for name in names if name not in by_name],
    }


@router.post(
    "/tags/bulk-upsert",
    response_model=BulkTagUpsertResponse,
    responses=ERROR_RESPONSES,
    summary="批量创建或覆盖 Tag",
)
def bulk_upsert(payload: BulkTagUpsertRequest) -> dict:
    names = [item.tag for item in payload.items]
    if len(names) != len(set(names)):
        raise api_error(status.HTTP_400_BAD_REQUEST, "duplicate_tag_in_request", "同一批次不能包含重复 Tag")
    with connect() as conn:
        created, updated, records = bulk_upsert_tags(conn, payload.items)
    return {"created": created, "updated": updated, "items": records}


@router.post(
    "/tags/bulk-delete",
    response_model=DeleteResult,
    responses=ERROR_RESPONSES,
    summary="按 ID 或英文名称批量删除 Tag",
)
def bulk_delete(payload: BulkTagDeleteRequest) -> dict:
    clauses: list[str] = []
    params: list[int | str] = []
    ids = list(dict.fromkeys(payload.ids))
    names = list(dict.fromkeys(payload.tags))
    if ids:
        clauses.append("id IN (" + ",".join("?" for _ in ids) + ")")
        params.extend(ids)
    if names:
        clauses.append("tag IN (" + ",".join("?" for _ in names) + ")")
        params.extend(names)
    with connect() as conn:
        rows = conn.execute(f"SELECT id, tag FROM tags WHERE {' OR '.join(clauses)} ORDER BY id", params).fetchall()
        deleted_ids = [int(row["id"]) for row in rows]
        if deleted_ids:
            conn.execute(
                "DELETE FROM tags WHERE id IN (" + ",".join("?" for _ in deleted_ids) + ")",
                deleted_ids,
            )
    return {"deleted": len(rows), "ids": deleted_ids, "tags": [row["tag"] for row in rows]}


@router.post(
    "/tags",
    response_model=TagRecord,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
    summary="创建 Tag",
)
def create_tag(payload: TagWrite) -> dict:
    try:
        with connect() as conn:
            if conn.execute("SELECT id FROM tags WHERE tag=?", (payload.tag,)).fetchone() is not None:
                raise api_error(status.HTTP_409_CONFLICT, "tag_conflict", f"Tag「{payload.tag}」已存在")
            return row_dict(insert_tag(conn, payload))
    except sqlite3.IntegrityError as exc:
        raise api_error(status.HTTP_409_CONFLICT, "tag_conflict", f"Tag「{payload.tag}」已存在") from exc


@router.get(
    "/tags/{tag_id}",
    response_model=TagRecord,
    responses=ERROR_RESPONSES,
    summary="读取单个 Tag",
)
def get_tag(tag_id: int) -> dict:
    with connect() as conn:
        return row_dict(get_tag_or_404(conn, tag_id))


@router.put(
    "/tags/{tag_id}",
    response_model=TagRecord,
    responses=ERROR_RESPONSES,
    summary="完整替换 Tag",
)
def put_tag(tag_id: int, payload: TagWrite) -> dict:
    try:
        with connect() as conn:
            return row_dict(replace_tag(conn, tag_id, payload))
    except sqlite3.IntegrityError as exc:
        raise api_error(status.HTTP_409_CONFLICT, "tag_conflict", f"Tag「{payload.tag}」已存在") from exc


@router.patch(
    "/tags/{tag_id}",
    response_model=TagRecord,
    responses=ERROR_RESPONSES,
    summary="部分更新 Tag",
)
def patch_tag(tag_id: int, payload: TagPatch) -> dict:
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    try:
        with connect() as conn:
            get_tag_or_404(conn, tag_id)
            if "category" in changes:
                ensure_category(conn, str(changes["category"]))
            assignments = [f"{column}=?" for column in changes]
            conn.execute(
                f"UPDATE tags SET {', '.join(assignments)}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                [*changes.values(), tag_id],
            )
            return row_dict(get_tag_or_404(conn, tag_id))
    except sqlite3.IntegrityError as exc:
        name = changes.get("tag", "")
        raise api_error(status.HTTP_409_CONFLICT, "tag_conflict", f"Tag「{name}」已存在") from exc


@router.delete(
    "/tags/{tag_id}",
    response_model=DeleteResult,
    responses=ERROR_RESPONSES,
    summary="删除 Tag",
)
def delete_tag(tag_id: int) -> dict:
    with connect() as conn:
        row = get_tag_or_404(conn, tag_id)
        conn.execute("DELETE FROM tags WHERE id=?", (tag_id,))
    return {"deleted": 1, "ids": [tag_id], "tags": [row["tag"]]}


@router.get(
    "/categories",
    response_model=CategoryList,
    summary="列出分类与二级分类统计",
)
def list_categories() -> dict:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM categories ORDER BY sort_order, name").fetchall()
        items = [category_record(conn, row) for row in rows]
    return {"items": items, "total": len(items)}


@router.post(
    "/categories",
    response_model=CategoryRecord,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
    summary="创建分类",
)
def create_category(payload: CategoryWrite) -> dict:
    try:
        with connect() as conn:
            cursor = conn.execute(
                "INSERT INTO categories (name, kind, sort_order, notes) VALUES (?, ?, ?, ?)",
                (payload.name, payload.kind, payload.sort_order, payload.notes),
            )
            row = get_category_or_404(conn, int(cursor.lastrowid))
            return category_record(conn, row)
    except sqlite3.IntegrityError as exc:
        raise api_error(status.HTTP_409_CONFLICT, "category_conflict", f"分类「{payload.name}」已存在") from exc


@router.get(
    "/categories/{category_id}",
    response_model=CategoryRecord,
    responses=ERROR_RESPONSES,
    summary="读取分类",
)
def get_category(category_id: int) -> dict:
    with connect() as conn:
        return category_record(conn, get_category_or_404(conn, category_id))


@router.patch(
    "/categories/{category_id}",
    response_model=CategoryRecord,
    responses=ERROR_RESPONSES,
    summary="更新或重命名分类",
)
def patch_category(category_id: int, payload: CategoryPatch) -> dict:
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    try:
        with connect() as conn:
            existing = get_category_or_404(conn, category_id)
            if "name" in changes and changes["name"] != existing["name"]:
                conflict = conn.execute("SELECT id FROM categories WHERE name=?", (changes["name"],)).fetchone()
                if conflict is not None:
                    raise api_error(
                        status.HTTP_409_CONFLICT,
                        "category_conflict",
                        f"分类「{changes['name']}」已存在",
                    )
            assignments = [f"{column}=?" for column in changes]
            conn.execute(
                f"UPDATE categories SET {', '.join(assignments)}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                [*changes.values(), category_id],
            )
            if "name" in changes and changes["name"] != existing["name"]:
                conn.execute(
                    "UPDATE tags SET category=?, updated_at=CURRENT_TIMESTAMP WHERE category=?",
                    (changes["name"], existing["name"]),
                )
            return category_record(conn, get_category_or_404(conn, category_id))
    except sqlite3.IntegrityError as exc:
        raise api_error(status.HTTP_409_CONFLICT, "category_conflict", "分类名称已存在") from exc


@router.delete(
    "/categories/{category_id}",
    response_model=CategoryDeleteResult,
    responses=ERROR_RESPONSES,
    summary="删除分类",
)
def delete_category(category_id: int, detach_tags: bool = Query(default=True)) -> dict:
    with connect() as conn:
        row = get_category_or_404(conn, category_id)
        tag_count = conn.execute("SELECT COUNT(*) FROM tags WHERE category=?", (row["name"],)).fetchone()[0]
        if tag_count and not detach_tags:
            raise api_error(
                status.HTTP_409_CONFLICT,
                "category_not_empty",
                f"分类仍关联 {tag_count} 个 Tag；请设置 detach_tags=true 或先迁移 Tag",
            )
        if tag_count:
            conn.execute(
                "UPDATE tags SET category='', subcategory='', updated_at=CURRENT_TIMESTAMP WHERE category=?",
                (row["name"],),
            )
        conn.execute("DELETE FROM categories WHERE id=?", (category_id,))
    return {"deleted": 1, "detached_tags": tag_count}


@router.get(
    "/subcategories",
    response_model=list[SubcategorySummary],
    summary="列出派生二级分类",
)
def list_subcategories(category: str = Query(default="")) -> list[dict]:
    clauses = ["subcategory != ''"]
    params: list[str] = []
    if category:
        clauses.append("category=?")
        params.append(category)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT category, subcategory AS name, COUNT(*) AS count
            FROM tags
            WHERE {' AND '.join(clauses)}
            GROUP BY category, subcategory
            ORDER BY category, subcategory
            """,
            params,
        ).fetchall()
    return [row_dict(row) for row in rows]


@router.post(
    "/subcategories/rename",
    response_model=SubcategoryMutationResult,
    responses=ERROR_RESPONSES,
    summary="重命名二级分类",
)
def rename_subcategory(payload: SubcategoryRenameRequest) -> dict:
    with connect() as conn:
        category = conn.execute("SELECT id FROM categories WHERE name=?", (payload.category,)).fetchone()
        if category is None:
            raise api_error(status.HTTP_404_NOT_FOUND, "category_not_found", f"分类「{payload.category}」不存在")
        count = conn.execute(
            "SELECT COUNT(*) FROM tags WHERE category=? AND subcategory=?",
            (payload.category, payload.name),
        ).fetchone()[0]
        if not count:
            raise api_error(
                status.HTTP_404_NOT_FOUND,
                "subcategory_not_found",
                f"二级分类「{payload.category} / {payload.name}」不存在",
            )
        conn.execute(
            """
            UPDATE tags SET subcategory=?, updated_at=CURRENT_TIMESTAMP
            WHERE category=? AND subcategory=?
            """,
            (payload.new_name, payload.category, payload.name),
        )
    return {
        "affected_tags": count,
        "category": payload.category,
        "old_name": payload.name,
        "new_name": payload.new_name,
    }


@router.post(
    "/subcategories/clear",
    response_model=SubcategoryMutationResult,
    responses=ERROR_RESPONSES,
    summary="清空二级分类归属",
)
def clear_subcategory(payload: SubcategoryClearRequest) -> dict:
    with connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM tags WHERE category=? AND subcategory=?",
            (payload.category, payload.name),
        ).fetchone()[0]
        if not count:
            raise api_error(
                status.HTTP_404_NOT_FOUND,
                "subcategory_not_found",
                f"二级分类「{payload.category} / {payload.name}」不存在",
            )
        conn.execute(
            """
            UPDATE tags SET subcategory='', updated_at=CURRENT_TIMESTAMP
            WHERE category=? AND subcategory=?
            """,
            (payload.category, payload.name),
        )
    return {
        "affected_tags": count,
        "category": payload.category,
        "old_name": payload.name,
        "new_name": "",
    }


@router.get(
    "/tag-library/export",
    response_model=TagLibraryExport,
    summary="导出完整 Tag 库 JSON",
)
def export_tag_library() -> dict:
    with connect() as conn:
        categories = [
            {key: row[key] for key in ("name", "kind", "sort_order", "notes")}
            for row in conn.execute("SELECT * FROM categories ORDER BY sort_order, name").fetchall()
        ]
        tags = [
            {key: row[key] for key in TAG_COLUMNS}
            for row in conn.execute("SELECT * FROM tags ORDER BY category, subcategory, tag").fetchall()
        ]
    return {
        "api_version": API_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "categories": categories,
        "tags": tags,
    }


@router.post(
    "/tag-library/import",
    response_model=TagLibraryImportResult,
    responses=ERROR_RESPONSES,
    summary="以单事务导入或覆盖 Tag 库",
)
def import_tag_library(payload: TagLibraryImportRequest) -> dict:
    category_names = [item.name for item in payload.categories]
    tag_names = [item.tag for item in payload.tags]
    if len(category_names) != len(set(category_names)):
        raise api_error(status.HTTP_400_BAD_REQUEST, "duplicate_category_in_request", "导入数据包含重复分类")
    if len(tag_names) != len(set(tag_names)):
        raise api_error(status.HTTP_400_BAD_REQUEST, "duplicate_tag_in_request", "导入数据包含重复 Tag")
    with connect() as conn:
        for category in payload.categories:
            conn.execute(
                """
                INSERT INTO categories (name, kind, sort_order, notes)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    kind=excluded.kind,
                    sort_order=excluded.sort_order,
                    notes=excluded.notes,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (category.name, category.kind, category.sort_order, category.notes),
            )
        created, updated, _ = bulk_upsert_tags(conn, payload.tags)
    return {
        "categories_upserted": len(payload.categories),
        "tags_created": created,
        "tags_updated": updated,
    }
