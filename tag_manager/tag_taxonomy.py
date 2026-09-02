# -*- coding: utf-8 -*-
"""夜之主衣柜 Tag 全量分类：受控一级/二级分类与规则分类器。

不删除 tag，不改英文/中文原文。只产出 (一级分类, 二级分类)。
"""
from __future__ import annotations

import re
from typing import Iterable

try:
    from .tag_taxonomy_maps import GENERIC_SUFFIXES, KNOWN_ARTISTS, KNOWN_CHAR_WORK, WORK_MAP, WORK_TEXT_KEYWORDS
except ImportError:  # 允许脚本直接运行
    from tag_taxonomy_maps import GENERIC_SUFFIXES, KNOWN_ARTISTS, KNOWN_CHAR_WORK, WORK_MAP, WORK_TEXT_KEYWORDS

CAT_CAMERA = "1.镜头"
CAT_PERSON = "2.人物"
CAT_CLOTHES = "3.服饰"
CAT_EXPRESSION = "4.表情"
CAT_CHARACTER = "4.角色/作品"
CAT_ACTION = "5.动作"
CAT_SCENE = "6.场景道具"
CAT_STYLE = "8.画风与质量"
CAT_NSFW = "0.可以涩涩"
CAT_MANUAL = "手工添加"

PRIMARY_CATEGORIES = (
    CAT_CAMERA,
    CAT_PERSON,
    CAT_CLOTHES,
    CAT_EXPRESSION,
    CAT_CHARACTER,
    CAT_ACTION,
    CAT_SCENE,
    CAT_STYLE,
    CAT_NSFW,
    CAT_MANUAL,
)

PRIMARY_MERGE = {
    "2.身体特征": CAT_PERSON,
    "5.姿势动作": CAT_ACTION,
    "6.构图镜头": CAT_CAMERA,
    "7.场景环境": CAT_SCENE,
    "NSFW Tags": CAT_NSFW,
}

CATEGORY_SORT = {
    CAT_CAMERA: 10,
    CAT_PERSON: 20,
    CAT_CLOTHES: 30,
    CAT_EXPRESSION: 40,
    CAT_CHARACTER: 42,
    CAT_ACTION: 50,
    CAT_SCENE: 60,
    CAT_STYLE: 66,
    CAT_NSFW: 70,
    CAT_MANUAL: 100,
}

CATEGORY_NOTES = {
    CAT_CAMERA: "景别、角度、光影、焦点与镜头效果",
    CAT_PERSON: "人数性别、身体、头发、眼睛、兽耳兽尾与身份",
    CAT_CLOTHES: "服装、鞋袜、帽子头饰与配饰",
    CAT_EXPRESSION: "面部表情与口眼细节",
    CAT_CHARACTER: "角色名与作品/IP，按作品归组",
    CAT_ACTION: "姿势、手势、腿部、视线与互动",
    CAT_SCENE: "室内外、天气时间、动植物、食物、武器与物品",
    CAT_STYLE: "画质、画风、画师与元信息",
    CAT_NSFW: "明确的暴露、性行为、束缚与马赛克",
    CAT_MANUAL: "LoRA 调用与带权重的画师串，不属于普通 tag",
}

CONTROLLED_SUBS = {
    CAT_CAMERA: ("景别", "角度", "光影", "焦点", "效果", "其他"),
    CAT_PERSON: ("人数性别", "身体", "头发", "发型", "头发颜色", "眼睛", "兽耳兽尾", "身份", "关系", "妆容", "其他"),
    CAT_CLOTHES: ("上衣", "裙子", "裤子", "内衣泳装", "袜子", "鞋类", "帽子头饰", "手套", "发饰", "配饰", "花纹", "制服套装", "眼镜", "披风", "材质", "家居服", "其他服饰"),
    CAT_EXPRESSION: ("笑", "哭", "害羞", "生气", "眼睛", "嘴巴", "其他"),
    CAT_ACTION: ("姿势", "手势", "腿部", "视线", "多人", "动作", "其他"),
    CAT_SCENE: ("室内", "室外", "天气时间", "植物", "动物", "食物", "武器", "物品", "地标", "家具", "背景", "其他"),
    CAT_STYLE: ("质量", "画风", "画师", "元信息", "厂商"),
    CAT_NSFW: ("服装暴露", "身体", "性行为", "束缚", "表情", "马赛克", "受伤", "其他"),
    CAT_MANUAL: ("LoRA调用", "画师权重"),
}

WORK_NAME_NORMALIZE = {
    "To LOVE  ru": "To LOVE ru",
    "奈叶": "魔法少女奈叶",
    "石蒜后坐力": "莉可丽丝",
    "京海战无地平线_1521": "境界线上的地平线",
    "nagi no asukara": "凪的小憩",
    "watashi ni tenshi ga maiorita!": "天使降临到我身边",
}

INVALID_WORK_SUBS = {"带子松开", "腾加", "月的", "未分类", ""}

EXTRA_WORK_MAP = {
    "lycoris_recoil": "莉可丽丝",
    "lycoris": "莉可丽丝",
    "kyoukaisenjou_no_horizon": "境界线上的地平线",
    "nagi_no_asukara": "凪的小憩",
    "watashi_ni_tenshi_ga_maiorita!": "天使降临到我身边",
    "mushoku_tensei": "无职转生",
    "roxy_migurdia": "无职转生",
    "nikke": "NIKKE",
    "goddess_of_victory_nikke": "NIKKE",
    "super_sonico": "超级索尼子",
    "sonico": "超级索尼子",
    "nitroplus": "超级索尼子",
    "code_geass": "反叛的鲁路修",
    "lirical_nanoha": "魔法少女奈叶",
    "lyrical_nanoha": "魔法少女奈叶",
    "shadowverse": "影之诗",
    "gochiusa": "点兔",
    "is_the_order_a_rabbit": "点兔",
    "bluearchive": "碧蓝档案",
    "azurlane": "碧蓝航线",
    "kantai": "舰队收藏",
    "fate_grand_order": "Fate",
    "fgo": "Fate",
    "type-moon": "Fate",
    "hoyoverse": "原神",
    "mihoyo": "原神",
    "star_rail": "崩坏",
    "honkai_star_rail": "崩坏",
    "houkai": "崩坏",
    "genshinimpact": "原神",
    "love_live": "Love Live",
    "love_live_sunshine": "Love Live",
    "the_idolmaster": "偶像大师",
    "idolm@ster": "偶像大师",
    "bang_dream": "BanG Dream!",
    "project_sekai": "世界计划",
    "vocaloid": "VOCALOID",
    "hololive_indonesia": "Hololive",
    "hololive_production": "Hololive",
    "nijisanji_en": "彩虹社",
    "vtuber": "VTuber",
    "indie_virtual_youtuber": "VTuber",
}

EXTRA_CHAR_WORK = {
    "sailor_senshi": "美少女战士",
    "miqo'te": "最终幻想",
    "sonico": "超级索尼子",
    "souryuuasukalangley": "新世纪福音战士",
    "souryuu_asuka_langley": "新世纪福音战士",
    "artoria_pendragon": "Fate",
    "artoria_pendragon_(lancer)": "Fate",
    "saber_extra": "Fate",
    "nero": "Fate",
    "meltlilith": "Fate",
    "minamoto_no_raikou": "Fate",
    "ichinose_asuna": "碧蓝档案",
    "sorasaki_hina": "碧蓝档案",
    "sunaookami_shiroko": "碧蓝档案",
    "kakudate_karin": "少女前线",
    "kafuu_chino": "点兔",
    "kirima_sharo": "点兔",
    "kokkoro": "公主连结",
    "pecorine": "公主连结",
    "sasaki_saren": "公主连结",
    "lelouch_lamperouge": "反叛的鲁路修",
    "sakura_kyouko": "魔法少女小圆",
    "kyubey": "魔法少女小圆",
    "yorha_no.2_type_b": "尼尔：机械纪元",
    "2b": "尼尔：机械纪元",
    "roxy_migurdia": "无职转生",
    "asamura_hiori": "其他角色",
    "zero_two": "DARLING in the FRANXX",
    "zero_two_(darling_in_the_franxx)": "DARLING in the FRANXX",
    "hu_tao": "原神",
    "la+_darknesss": "Hololive",
    "cecilia_(shiro_seijo_to_kuro_bokushi)": "白圣女与黑牧师",
}

EXTRA_ARTISTS = {
    "boris_(noborhys)",
    "haruyama_kazunori",
    "nori_tamago",
    "yano_toshinori",
    "ryu_genshin77",
    "ringouulu",
    "shiratamaco",
    "shiratama_(shiratamaco)",
}

VENDOR_TAGS = {
    "cygames": "厂商",
    "type-moon": "厂商",
    "mihoyo": "厂商",
    "hoyoverse": "厂商",
    "nitroplus": "厂商",
    "kadokawa": "厂商",
    "square_enix": "厂商",
}

WEAPON_WORDS = (
    "weapon", "sword", "blade", "katana", "spear", "lance", "halberd", "axe", "hammer",
    "bow", "arrow", "gun", "rifle", "pistol", "cannon", "staff", "wand", "scythe",
    "dagger", "knife", "shield", "whip", "mace", "trident", "crossbow",
)
CLOTHING_WORDS = (
    "dress", "skirt", "shirt", "jacket", "coat", "hoodie", "sweater", "uniform",
    "armor", "bikini", "swimsuit", "panties", "bra", "pantyhose", "thighhigh",
    "boot", "shoe", "hat", "cap", "kimono", "hakama", "outfit", "costume", "clothes",
)
OBJECT_WORDS = (
    "background", "scenery", "landscape", "interior", "furniture", "chair", "table",
    "book", "phone", "umbrella", "flower", "tree",
)

HAIR_COLORS = (
    "blonde", "black", "white", "red", "blue", "green", "pink", "purple", "silver",
    "grey", "gray", "brown", "orange", "aqua", "platinum", "light_blue", "dark_blue",
    "light_brown", "dark_green", "light_purple", "dark_purple", "light_pink",
)
EYE_COLORS = HAIR_COLORS + ("gold", "yellow", "heterochromia", "amber")

QUALITY_TAGS = {
    "masterpiece", "best_quality", "bestquality", "highres", "absurdres", "incredibly_absurdres",
    "lowres", "newest", "very_aesthetic", "amazing_quality", "high_detail", "high_details",
    "amazingquality", "beast_quality", "normal_quality", "worst_quality", "score_9",
    "score_8_up", "score_7_up", "wallpaper",
}
STYLE_TAGS = {
    "anime_screencap", "anime_screencap_", "chibi", "chibi_only", "pixel_art", "watercolor",
    "watercolor_(medium)", "oil_painting", "realistic", "real", "photo_(medium)", "polaroid",
    "sketch", "monochrome", "greyscale", "grayscale", "comic", "4koma", "official_art",
    "official_style", "game_cg", "artbook", "dakimakura_(medium)", "poster", "tarot",
    "silent_comic", "tachi-e", "tachi_e", "celulloid", "celluloid", "ink", "flat_color", "halftone",
    "high_contrast", "outline", "partially_colored", "silhouette", "spot_color",
    "chromatic_aberration", "acrylic_paint_(medium)", "ballpoint_pen_(medium)_",
    "colored_pencil_(medium)", "graphite_(medium)", "marker_(medium)", "millipen_(medium)",
    "nib_pen_(medium)", "pastel_color", "pencil_sketch_lines", "copics", "faux_traditional_media",
    "contour_deepening", "cyberpunk", "steampunk", "minigirl", "retro_arfstyle",
    "album", "card_(medium)", "cover_page", "magazine_cover", "one-hour_drawing_challenge",
    "cg", "artbook", "fantasy", "science_fiction", "pastel_colors",
}
META_TAGS = {
    "artist_name", "signature", "twitter_username", "english_text", "character_name",
    "dated", "copyright_name", "watermark", "commentary", "commentary_request",
    "outside_border", "meme", "catchphrase", "translated", "translation_request",
    "speech_bubble", "thought_bubble", "music", "musical_note",
}
CAMERA_SHOT = {
    "cowboy_shot", "full_body", "upper_body", "portrait", "close-up", "close_up",
    "lower_body", "wide_shot", "medium_shot", "feet_out_of_frame", "head_out_of_frame",
    "cowboy_shot",
}
CAMERA_ANGLE = {
    "from_behind", "from_side", "from_above", "from_below", "from_back", "back_view",
    "dutch_angle", "lateral_view", "profile", "three_quarter_view", "foreshortening",
    "pov", "first_person_view", "high_angle", "low_angle", "side_view", "front_view",
    "straight-on", "upside-down",
}
LIGHT_TAGS = {
    "lighting", "sunlight", "backlight", "backlighting", "rim_lighting", "moonlight",
    "cinematic_lighting", "dramatic_lighting", "dim_lighting", "overexposure",
    "lens_flare", "bokeh", "depth_of_field", "caustics", "shadow", "drop_shadow",
    "god_rays", "spotlight", "stage_lights", "neon_lights", "light_rays",
}
FOCUS_TAGS = {
    "solo_focus", "male_focus", "female_focus", "ass_focus", "foot_focus", "face_focus",
    "hand_focus", "eye_focus", "navel_focus", "hip_focus", "breast_focus", "between_breasts",
}

COUNT_TAGS = {
    "1girl", "1boy", "1other", "2girls", "3girls", "4girls", "5girls", "6+girls",
    "2boys", "3boys", "multiple_girls", "multiple_boys", "solo", "solo_female",
    "solo_male", "female", "male", "others", "group",
}

MILD_BODY = {
    "breasts", "large_breasts", "medium_breasts", "small_breasts", "huge_breasts",
    "gigantic_breasts", "flat_chest", "cleavage", "thighs", "ass", "midriff", "navel",
    "collarbone", "abs", "ribs", "narrow_waist", "wide_hips", "thick_thighs",
    "curvy", "slender", "petite", "muscular", "toned", "armpits", "shoulders",
    "bare_shoulders", "collarbone", "hips", "butt", "gluteus",
}

WEIGHTED_RE = re.compile(r"^\([^:]+:\s*[0-9.]+\)$")
LORA_RE = re.compile(r"^<(lora|lyco):", re.I)


def _norm_key(tag: str) -> str:
    t = (tag or "").strip().lower()
    t = t.replace("\\(", "(").replace("\\)", ")")
    t = t.replace(" ", "_").replace("-", "_")
    t = t.strip("{},")
    t = t.strip("_")
    return t


def clean_tag(tag: str) -> str:
    t = (tag or "").strip()
    t = t.replace("\\(", "(").replace("\\)", ")")
    t = t.strip("{}")
    t = t.strip(" ,")
    return t


def has_word(n: str, word: str) -> bool:
    if not n or not word:
        return False
    parts = n.split("_")
    variants = {word, word + "s"}
    if word.endswith("ies") and len(word) > 4:
        variants.add(word[:-3] + "y")
    elif word.endswith("s") and len(word) > 3:
        variants.add(word[:-1])
    if any(part in variants for part in parts):
        return True
    if n == word:
        return True
    if n.startswith(word + "_") or n.endswith("_" + word):
        return True
    return f"_{word}_" in n


def has_any(n: str, words: Iterable[str]) -> bool:
    return any(has_word(n, w) for w in words)


def extract_suffix(tag: str) -> str:
    t = clean_tag(tag)
    if "(" in t and t.endswith(")"):
        inner = t[t.rfind("(") + 1 : -1].strip().strip("\\")
        return _norm_key(inner)
    return ""


def _build_work_lookup() -> dict[str, str]:
    lookup = { _norm_key(k): v for k, v in WORK_MAP.items() }
    lookup.update({ _norm_key(k): v for k, v in EXTRA_WORK_MAP.items() })
    return lookup


def _build_char_lookup() -> dict[str, str]:
    lookup = { _norm_key(k): WORK_NAME_NORMALIZE.get(v, v) for k, v in KNOWN_CHAR_WORK.items() }
    lookup.update({ _norm_key(k): WORK_NAME_NORMALIZE.get(v, v) for k, v in EXTRA_CHAR_WORK.items() })
    lookup["golden_darkness"] = "To LOVE ru"
    return lookup


def _build_artist_set() -> set[str]:
    artists = { _norm_key(x) for x in KNOWN_ARTISTS }
    artists.update(_norm_key(x) for x in EXTRA_ARTISTS)
    artists.add("shiratama")
    return artists


WORK_LOOKUP = _build_work_lookup()
CHAR_LOOKUP = _build_char_lookup()
ARTIST_SET = _build_artist_set()
VALID_WORK_NAMES = set(WORK_LOOKUP.values()) | set(CHAR_LOOKUP.values()) | set(WORK_NAME_NORMALIZE.values())
VALID_WORK_NAMES.update(WORK_NAME_NORMALIZE.keys())
VALID_WORK_NAMES.update({"其他角色", "其他作品", "原创", "VTuber"})


def canonicalize_work(raw: str) -> str | None:
    if not raw:
        return None
    key = _norm_key(raw)
    if key in WORK_LOOKUP:
        return WORK_NAME_NORMALIZE.get(WORK_LOOKUP[key], WORK_LOOKUP[key])
    base = key.split("(")[0].rstrip("_")
    if base in WORK_LOOKUP:
        return WORK_NAME_NORMALIZE.get(WORK_LOOKUP[base], WORK_LOOKUP[base])
    prefixes = (
        ("fate", "Fate"),
        ("pokemon", "宝可梦"),
        ("touhou", "东方"),
        ("idolmaster", "偶像大师"),
        ("the_idolm", "偶像大师"),
        ("love_live", "Love Live"),
        ("honkai", "崩坏"),
        ("houkai", "崩坏"),
        ("final_fantasy", "最终幻想"),
        ("gundam", "高达"),
        ("fire_emblem", "火焰纹章"),
        ("hololive", "Hololive"),
        ("genshin", "原神"),
        ("umamusume", "赛马娘"),
        ("princess_connect", "公主连结"),
        ("re:zero", "Re:0"),
        ("re_zero", "Re:0"),
        ("xenoblade", "异度神剑"),
        ("persona", "女神异闻录"),
        ("overwatch", "守望先锋"),
        ("danganronpa", "弹丸论破"),
        ("gochuumon", "点兔"),
        ("atelier", "炼金工房"),
        ("bang_dream", "BanG Dream!"),
        ("mahou_shoujo_lyrical_nanoha", "魔法少女奈叶"),
        ("mahou_shoujo_madoka", "魔法少女小圆"),
        ("nijisanji", "彩虹社"),
        ("kantai", "舰队收藏"),
        ("kancolle", "舰队收藏"),
        ("lycoris", "莉可丽丝"),
        ("mushoku_tensei", "无职转生"),
        ("arknights", "明日方舟"),
        ("azur_lane", "碧蓝航线"),
        ("blue_archive", "碧蓝档案"),
        ("girls_frontline", "少女前线"),
        ("girls'_frontline", "少女前线"),
    )
    for prefix, name in prefixes:
        if key.startswith(prefix) or prefix in key:
            return name
    return None


def work_from_text(*texts: str) -> str | None:
    blob = " ".join(t or "" for t in texts)
    if not blob:
        return None
    for kw, name in WORK_TEXT_KEYWORDS:
        if kw in blob:
            return WORK_NAME_NORMALIZE.get(name, name)
    extras = (
        ("莉可丽丝", "莉可丽丝"),
        ("Lycoris", "莉可丽丝"),
        ("无职转生", "无职转生"),
        ("境界线上的地平线", "境界线上的地平线"),
        ("超级索尼子", "超级索尼子"),
        ("碧蓝档案", "碧蓝档案"),
        ("明日方舟", "明日方舟"),
        ("尼尔", "尼尔：机械纪元"),
        ("公主连结", "公主连结"),
        ("点兔", "点兔"),
        ("香风智乃", "点兔"),
    )
    for kw, name in extras:
        if kw in blob:
            return name
    return None


def parse_weighted(tag: str) -> str | None:
    t = clean_tag(tag).replace("\\(", "(").replace("\\)", ")")
    t = t.replace("\\(", "(").replace("\\)", ")")
    compact = t.replace(" ", "")
    match = re.match(r"^\((.+):([0-9.]+)\)$", compact) or re.match(r"^\((.+):\s*([0-9.]+)\)$", t)
    if not match:
        return None
    inner = match.group(1).strip().strip("()")
    inner = inner.replace("\\(", "(").replace("\\)", ")")
    return inner or None


def is_weighted_artist(tag: str) -> bool:
    return parse_weighted(tag) is not None


def is_lora(tag: str) -> bool:
    return bool(LORA_RE.match((tag or "").strip()))


def is_artist(n: str) -> bool:
    if n in ARTIST_SET:
        return True
    if "shiratama" in n:
        return True
    return False


def looks_like_generic_suffix(suf: str) -> bool:
    if not suf:
        return True
    if suf in GENERIC_SUFFIXES:
        return True
    if suf in {"medium", "object", "action", "weapon", "character", "series", "game", "anime"}:
        return True
    return False


def infer_work(tag: str, zh: str = "") -> str | None:
    n = _norm_key(tag)
    if n in CHAR_LOOKUP:
        return CHAR_LOOKUP[n]
    mapped = canonicalize_work(n)
    suf = extract_suffix(tag)
    if suf and not looks_like_generic_suffix(suf):
        by_suf = canonicalize_work(suf)
        if by_suf:
            return by_suf
    if mapped and "(" not in clean_tag(tag):
        return mapped
    text_work = work_from_text(zh, tag)
    if text_work:
        return text_work
    return mapped


def _base_without_suffix(tag: str) -> str:
    t = clean_tag(tag)
    if "(" in t and t.endswith(")"):
        t = t[: t.rfind("(")].rstrip("_").rstrip()
    return _norm_key(t)


def is_copyright_tag(n: str) -> bool:
    if n in WORK_LOOKUP:
        return True
    if n.endswith("_(series)") or n.endswith("_(game)") or n.endswith("_(anime)"):
        return canonicalize_work(n) is not None
    return False


def is_work_suffix_character(tag: str, n: str, current_category: str, current_subcategory: str) -> str | None:
    """带作品括号的角色名。武器/场景道具即使带作品后缀也不当角色。"""
    suf = extract_suffix(tag)
    if not suf or looks_like_generic_suffix(suf):
        return None
    work = canonicalize_work(suf)
    if not work:
        return None
    if has_word(n, "cosplay"):
        return None
    merged = merge_primary(current_category)
    if has_any(n, WEAPON_WORDS):
        return None
    if merged == CAT_SCENE and current_subcategory in {"武器", "物品", "室外", "室内", "地标"}:
        # 世界观道具/地点，如 originium_(arknights)、human_village_(touhou)
        if merged == CAT_CHARACTER:
            return work
        return None
    return work


def character_bucket(tag: str, n: str, zh: str, current_category: str, current_subcategory: str) -> tuple[str, str] | None:
    if n in {"unleashed", "lunar", "tenga"}:
        return None
    if n in CHAR_LOOKUP:
        return CAT_CHARACTER, normalize_work_name(CHAR_LOOKUP[n])
    if is_copyright_tag(n):
        return CAT_CHARACTER, normalize_work_name(WORK_LOOKUP.get(n) or canonicalize_work(n) or "其他作品")
    work = is_work_suffix_character(tag, n, current_category, current_subcategory)
    if work:
        return CAT_CHARACTER, normalize_work_name(work)
    merged = merge_primary(current_category)
    sub = normalize_work_name(current_subcategory)
    if merged == CAT_CHARACTER and sub not in INVALID_WORK_SUBS:
        inferred = infer_work(tag, zh)
        return CAT_CHARACTER, normalize_work_name(inferred or sub or "其他角色")
    inferred = infer_work(tag, zh)
    if inferred and n in CHAR_LOOKUP:
        return CAT_CHARACTER, normalize_work_name(inferred)
    return None


def normalize_work_name(name: str) -> str:
    name = (name or "").strip()
    return WORK_NAME_NORMALIZE.get(name, name)


def merge_primary(category: str) -> str:
    category = (category or "").strip()
    return PRIMARY_MERGE.get(category, category)


def _style_bucket(n: str) -> tuple[str, str] | None:
    compact = n.replace(" ", "_")
    if compact in QUALITY_TAGS or n in QUALITY_TAGS:
        return CAT_STYLE, "质量"
    if compact in STYLE_TAGS or n in STYLE_TAGS:
        return CAT_STYLE, "画风"
    if compact in META_TAGS or n in META_TAGS:
        return CAT_STYLE, "元信息"
    if n in VENDOR_TAGS:
        return CAT_STYLE, VENDOR_TAGS[n]
    if has_any(n, ("quality", "masterpiece", "highres", "absurdres", "lowres")):
        return CAT_STYLE, "质量"
    if has_any(n, ("screencap", "pixel_art", "watercolor", "monochrome", "greyscale", "realistic", "chibi", "sketch")):
        return CAT_STYLE, "画风"
    if n.endswith("_(medium)"):
        return CAT_STYLE, "画风"
    return None


def _camera_bucket(n: str) -> tuple[str, str] | None:
    if n in CAMERA_SHOT or has_any(n, ("cowboy_shot", "full_body", "upper_body", "close_up", "portrait", "wide_shot", "mid_shot", "full_shot", "bust_shot", "close_shot", "multiple_views")):
        return CAT_CAMERA, "景别"
    if n in CAMERA_ANGLE or has_any(n, ("from_behind", "from_side", "from_above", "from_below", "dutch_angle", "pov", "dynamic_angle", "cinematic_angle", "side_profile", "selfie")):
        return CAT_CAMERA, "角度"
    if n in LIGHT_TAGS or has_any(n, ("lighting", "sunlight", "backlight", "lens_flare", "bokeh", "overexposure", "caustics", "rim_light", "sidelight", "frontlight", "ambient_light")):
        return CAT_CAMERA, "光影"
    if n in FOCUS_TAGS or n.endswith("_focus") or n == "male_focus" or n == "female_focus":
        return CAT_CAMERA, "焦点"
    if has_any(n, ("motion_blur", "motion_lines", "speed_lines", "depth_of_field", "reflection", "sparkle", "glint", "glow", "blurry", "fisheye")):
        return CAT_CAMERA, "效果"
    return None


def _nsfw_bucket(n: str) -> tuple[str, str] | None:
    if has_any(n, ("mosaic", "censored", "bar_censor", "blank_censor", "uncensored")):
        return CAT_NSFW, "马赛克"
    if has_any(n, ("ahegao", "naughty_face", "fucked_silly", "orgasm_face", "rape_face", "endured_face")):
        return CAT_NSFW, "表情"
    if has_any(n, ("wound", "injury", "blood", "scar", "bruise", "amputation")) and has_any(n, ("sex", "nude", "after_sex", "guro")):
        return CAT_NSFW, "受伤"
    if has_any(n, ("bound", "bondage", "gag", "leash", "bdsm", "shibari", "restraint", "cuffs", "ballgag", "bitgag", "cleave_gag")):
        return CAT_NSFW, "束缚"
    if has_any(
        n,
        (
            "sex", "cum", "penis", "pussy", "anal", "oral", "fellatio", "paizuri",
            "penetration", "ejaculat", "vaginal", "futanari", "tentacle", "rape",
            "handjob", "footjob", "cunnilingus", "masturbation", "dildo", "vibrator",
            "condom", "after_sex", "after_anal", "group_sex", "threesome", "gangbang",
            "incest", "bestiality", "creampie", "squirting", "cervix", "urethral",
            "testicles", "clitoris", "anus", "cowgirl_position", "doggystyle",
            "missionary", "girl_on_top", "reverse_cowgirl",
        ),
    ):
        return CAT_NSFW, "性行为"
    if has_any(
        n,
        (
            "nude", "naked", "topless", "bottomless", "nipples", "areola",
            "pussy", "penis", "anus", "spread_pussy",
        ),
    ):
        return CAT_NSFW, "身体"
    if has_any(
        n,
        (
            "panties_aside", "bikini_aside", "clothes_aside", "undressing",
            "clothes_lift", "skirt_lift", "shirt_lift", "flashing", "upskirt",
            "downblouse", "see_through", "transparent", "convenient_censoring",
            "pantyshot", "underboob", "sideboob", "peeking", "peeping",
        ),
    ):
        return CAT_NSFW, "服装暴露"
    if has_any(n, ("guro", "amputee", "public_use", "pregnant", "latex", "exhibitionism", "voyeur", "slave")):
        return CAT_NSFW, "其他"
    return None


def _clothes_bucket(n: str) -> tuple[str, str] | None:
    if has_any(n, ("holding", "hands_on", "hand_on", "drawing")):
        return None
    if has_any(n, ("adjusting", "pull", "lift", "tug")) and has_any(
        n, ("clothes", "shirt", "skirt", "dress", "kimono", "bikini", "swimsuit", "panties", "bra", "leotard", "thighhigh", "mask", "hat", "gloves")
    ):
        return None
    if n.endswith("dress") or n.endswith("skirt") or has_any(n, ("skirt", "dress", "kilt", "hakama", "microdress")):
        return CAT_CLOTHES, "裙子"
    if has_any(n, ("panties", "bra", "lingerie", "underwear", "thong", "briefs", "bikini", "swimsuit", "leotard", "bodysuit", "bodystocking", "buruma", "school_swimsuit", "fundoshi")):
        return CAT_CLOTHES, "内衣泳装"
    if n.endswith("shirt") or n.endswith("jacket") or n.endswith("coat") or n.endswith("hoodie") or has_any(
        n, ("shirt", "jacket", "coat", "hoodie", "sweater", "blouse", "vest", "cardigan", "top", "serafuku", "collar", "sleeves", "sleeve")
    ):
        return CAT_CLOTHES, "上衣"
    if has_any(n, ("uniform", "armor", "armored", "costume", "kimono", "yukata", "cheongsam", "china_dress", "qipao", "suit", "tuxedo", "robe", "cape", "cloak", "dougi", "lolita", "gothic")):
        return CAT_CLOTHES, "制服套装"
    if has_any(n, ("hat", "cap", "beret", "helmet", "crown", "tiara", "headband", "headwear", "headdress", "hood")) and not has_word(n, "neighborhood"):
        return CAT_CLOTHES, "帽子头饰"
    if has_any(n, ("sock", "thighhigh", "pantyhose", "tights", "stocking", "legwear", "zettai_ryouiki")):
        return CAT_CLOTHES, "袜子"
    if n.endswith("shoes") or n.endswith("boots") or has_any(n, ("shoe", "boot", "sandal", "heel", "footwear", "slipper", "loafers")):
        return CAT_CLOTHES, "鞋类"
    if has_any(n, ("glove", "mitten", "gauntlet")):
        return CAT_CLOTHES, "手套"
    if has_any(n, ("hair_ornament", "hairpin", "hairband", "hair_bow", "hair_ribbon", "hairclip", "hair_flower", "scrunchie", "hair_bobbles", "hair_stick", "hair_tubes")):
        return CAT_CLOTHES, "发饰"
    if has_any(n, ("necklace", "choker", "pendant", "earring", "ear_ornament", "bracelet", "ring", "brooch", "bow", "ribbon", "scarf", "muffler", "shawl", "belt", "tie", "necktie", "halo")):
        return CAT_CLOTHES, "配饰"
    if has_any(n, ("glasses", "eyepatch", "mask", "sunglasses", "blindfold")):
        return CAT_CLOTHES, "配饰"
    if has_any(n, ("print", "stripe", "plaid", "checkered", "argyle", "camo", "pattern", "polka_dot", "floral_print")):
        return CAT_CLOTHES, "花纹"
    if has_any(n, ("nail", "nail_polish")):
        return CAT_CLOTHES, "配饰"
    if has_any(n, ("off_shoulder", "sleeveless", "detached_sleeves", "long_sleeves", "short_sleeves")):
        return CAT_CLOTHES, "上衣"
    if has_word(n, "clothing") or has_word(n, "clothes") or has_word(n, "outfit") or has_word(n, "open_clothes"):
        return CAT_CLOTHES, "其他服饰"
    return None


def _person_bucket(n: str) -> tuple[str, str] | None:
    if n in COUNT_TAGS or has_any(n, ("1girl", "1boy", "1other", "multiple_girls", "multiple_boys", "solo")):
        return CAT_PERSON, "人数性别"
    if has_any(n, ("hair_ornament", "hairpin", "hairband", "hair_bow", "hair_ribbon", "hair_flower", "scrunchie", "hairclip")):
        return CAT_CLOTHES, "发饰"
    if n.endswith("_hair") and has_any(n, HAIR_COLORS):
        return CAT_PERSON, "头发颜色"
    if has_any(n, ("ponytail", "twintail", "twintails", "bangs", "braid", "hime_cut", "bob_cut", "ahoge", "sidelocks", "drill_hair", "curly_hair", "wavy_hair", "double_bun", "hair_bun", "one_side_up", "bald")):
        return CAT_PERSON, "发型"
    if n.endswith("_hair") or has_any(n, ("hair", "bangs", "ahoge", "hairstyle")):
        return CAT_PERSON, "头发"
    if n.endswith("_eyes") or n.endswith("_pupils") or has_any(n, ("pupils", "heterochromia", "eyeshadow")):
        return CAT_PERSON, "眼睛"
    if (has_word(n, "ears") or has_word(n, "ear")) and not has_any(n, ("headphones", "earphones", "earring", "ear_ornament", "ear_piercing")):
        return CAT_PERSON, "兽耳兽尾"
    if has_word(n, "tail") and not has_any(n, ("cocktail", "ponytail")):
        return CAT_PERSON, "兽耳兽尾"
    if has_any(n, ("horns", "wings", "fangs", "kemonomimi", "ear_fluff", "animal_ear")):
        return CAT_PERSON, "兽耳兽尾"
    if has_any(n, ("loli", "shota", "child", "adult", "mature", "aged", "elderly", "teen", "petite", "tall")):
        return CAT_PERSON, "身份"
    if n.endswith("_skin") or has_any(n, ("pale_skin", "dark_skin", "tan", "tanlines", "tan_lines", "shiny_skin", "muscle", "pectorals", "forehead", "chest", "baby_fat")):
        return CAT_PERSON, "身体"
    if n in MILD_BODY or has_any(n, ("breasts", "cleavage", "thighs", "navel", "midriff", "collarbone", "abs", "armpits", "curvy", "slender", "muscular", "bare_shoulders", "kneepits")):
        return CAT_PERSON, "身体"
    if n.endswith("_girl") or n.endswith("_boy") or n.endswith("_musume") or has_any(
        n,
        (
            "maid", "nurse", "student", "teacher", "idol", "witch", "vampire", "angel",
            "demon", "elf", "fairy", "princess", "queen", "knight", "samurai", "ninja",
            "officer", "police", "doctor", "chef", "dancer", "bride", "nun", "miko",
            "shrine_maiden", "robot", "cyborg", "android", "mermaid", "centaur", "succubus",
            "valkyrie", "goddess", "devil", "office_lady", "race_queen", "vtuber",
            "virtual_youtuber", "magical_girl", "mecha", "furry", "otoko_no_ko", "trap",
            "cheerleader", "waitress", "priest", "ballerina", "mesugaki", "bishoujo",
        ),
    ):
        return CAT_PERSON, "身份"
    if has_any(n, ("couple", "siblings", "twins", "mother", "father", "daughter", "son", "yuri", "yaoi")):
        if has_any(n, ("yuri", "yaoi")):
            return CAT_NSFW, "性行为"
        return CAT_PERSON, "关系"
    return None


def _expression_bucket(n: str) -> tuple[str, str] | None:
    if has_any(n, ("smile", "grin", "laugh", "smirk", "smug", ":d", "happy", "giggling")):
        return CAT_EXPRESSION, "笑"
    if has_any(n, ("cry", "tear", "sob", "crying", "streaming_tears")):
        return CAT_EXPRESSION, "哭"
    if has_any(n, ("blush", "embarrassed", "shy", "nose_blush")):
        return CAT_EXPRESSION, "害羞"
    if has_any(n, ("angry", "frown", "glare", "scowl", "annoyed")):
        return CAT_EXPRESSION, "生气"
    if has_any(n, ("wink", "one_eye_closed", "closed_eyes", "eyes_closed", "half-closed_eyes", "half_closed_eyes", "tsurime", "tareme")):
        return CAT_EXPRESSION, "眼睛"
    if has_any(n, ("open_mouth", "closed_mouth", "tongue", "lips", "teeth", "fang", "clenched_teeth", "parted_lips")):
        return CAT_EXPRESSION, "嘴巴"
    if has_any(n, ("expression", "face", "ahegao", "naughty", "yandere", "tsundere", "crazy")):
        if has_any(n, ("ahegao", "orgasm")):
            return CAT_NSFW, "表情"
        return CAT_EXPRESSION, "其他"
    return None


def _action_bucket(n: str) -> tuple[str, str] | None:
    if has_any(n, ("looking_at_viewer", "looking_back", "looking_away", "looking_to_the_side", "looking_down", "looking_up", "looking_at", "eye_contact", "stare", "gaze")):
        return CAT_ACTION, "视线"
    if n.startswith("looking_"):
        return CAT_ACTION, "视线"
    if has_any(n, ("adjusting", "pull", "lift")) and has_any(
        n, ("clothes", "shirt", "skirt", "dress", "kimono", "bikini", "swimsuit", "panties", "bra", "leotard", "thighhigh", "mask", "hat", "gloves", "pants")
    ):
        return CAT_ACTION, "手势"
    if has_any(
        n,
        (
            "sitting", "standing", "lying", "kneeling", "crouching", "on_back", "on_side",
            "on_stomach", "wariza", "seiza", "all_fours", "spread_legs", "crossed_legs",
            "hugging_own_legs", "fetal_position", "arched_back", "leaning", "against",
            "bent_over", "upside_down", "open_stance", "curtsy", "the_pose", "indian_style",
            "knees_together_feet_apart", "head_tilt", "head_down", "head_rest",
            "squatting", "stretch", "reclining", "salute", "reaching", "lotus_position",
            "gravure_pose", "paw_pose", "claw_pose", "one_knee",
        ),
    ):
        return CAT_ACTION, "姿势"
    if n in {"v", "v_arms", "double_v"} or has_any(n, ("peace_sign", "thumbs_up")):
        return CAT_ACTION, "手势"
    if has_any(n, ("arm", "hand", "finger", "pointing", "clenched", "outstretched", "arms_up", "arms_behind", "hands_on", "holding", "grabbing", "waving")):
        if has_any(n, ("pantyhose", "handbag", "handbook", "handgun")):
            return None
        return CAT_ACTION, "手势"
    if has_any(n, ("leg", "thigh", "kick", "step", "foot", "barefoot", "walking", "running", "straddling")):
        if has_any(n, ("legwear", "leg_ribbon", "footwear")):
            return None
        return CAT_ACTION, "腿部"
    if has_any(n, ("kiss", "hug", "holding_hands", "back_to_back", "facing", "feeding", "kabedon", "princess_carry", "carrying", "fighting", "dancing")):
        return CAT_ACTION, "多人"
    if has_any(n, ("sleeping", "eating", "drinking", "smoking", "reading", "writing", "playing", "bathing", "swimming", "flying", "jumping", "falling", "aiming", "painting", "singing", "thinking", "giving")):
        return CAT_ACTION, "动作"
    return None


def _scene_bucket(n: str) -> tuple[str, str] | None:
    if has_any(n, ("indoor", "room", "bedroom", "bathroom", "kitchen", "classroom", "library", "office", "hallway", "window", "door", "bed", "pillow", "sofa", "chair", "table", "desk", "ceiling", "floor", "wall", "bathtub", "onsen", "izakaya", "toilet")):
        return CAT_SCENE, "室内"
    if has_any(n, ("outdoor", "city", "street", "forest", "beach", "mountain", "sky", "cloud", "ocean", "sea", "lake", "river", "park", "garden", "rooftop", "alley", "scenery", "landscape", "cityscape", "building", "skyscraper", "bridge")):
        return CAT_SCENE, "室外"
    if n.endswith("_background") or has_word(n, "background"):
        if has_word(n, "indoor"):
            return CAT_SCENE, "室内"
        return CAT_SCENE, "室外"
    if has_any(n, ("night", "day", "sunset", "sunrise", "morning", "evening", "noon", "twilight", "autumn", "summer", "winter", "spring", "rain", "snow", "starry", "moon", "sun", "cloudy", "christmas", "halloween", "valentine")):
        return CAT_SCENE, "天气时间"
    if has_any(n, ("flower", "tree", "leaf", "grass", "plant", "bush", "rose", "cherry_blossoms", "petal", "bamboo", "maple")):
        if has_word(n, "hair_flower"):
            return CAT_CLOTHES, "发饰"
        return CAT_SCENE, "植物"
    if has_any(n, ("cat", "dog", "bird", "horse", "fish", "dragon", "snake", "wolf", "bear", "rabbit", "bunny", "fox", "tiger", "mouse", "insect", "butterfly", "animal")) and not has_any(n, ("ears", "tail", "girl", "boy", "print", "hood", "costume")):
        return CAT_SCENE, "动物"
    if has_any(n, ("food", "cake", "apple", "bread", "meat", "fish", "rice", "noodle", "drink", "tea", "coffee", "wine", "beer", "candy", "chocolate", "fruit", "vegetable", "sushi", "burger")):
        return CAT_SCENE, "食物"
    if has_any(n, WEAPON_WORDS):
        return CAT_SCENE, "武器"
    if has_any(n, ("tokyo_tower", "skytree", "eiffel", "taj_mahal", "great_wall", "fuji", "machu_picchu", "grand_canyon", "santorini", "venice", "real_world_location", "fushimi_inari")):
        return CAT_SCENE, "地标"
    if has_any(n, ("object", "bag", "umbrella", "book", "phone", "microphone", "camera", "cup", "bottle", "box", "ball", "instrument", "guitar", "piano", "vehicle", "car", "train", "ship", "airplane")):
        return CAT_SCENE, "物品"
    return None


def classify_normalized(n: str, tag: str, zh: str, current_category: str, current_subcategory: str) -> tuple[str, str] | None:
    if not n:
        return None
    if n in {"unleashed"}:
        return CAT_ACTION, "动作"
    if n in {"lunar"}:
        return CAT_SCENE, "天气时间"
    if n in {"tenga"}:
        return CAT_NSFW, "其他"
    if n in {"blood"}:
        return CAT_NSFW, "受伤"
    if n in {"crescent_rose"}:
        return CAT_SCENE, "武器"
    if n in {"landscape"}:
        return CAT_SCENE, "室外"
    if n in {"checkered_floor"}:
        return CAT_SCENE, "室内"
    if n in {"shiny"}:
        return CAT_STYLE, "画风"
    if n in {"day"}:
        return CAT_SCENE, "天气时间"
    if n in {"window"}:
        return CAT_SCENE, "室内"
    if n in {"male_focus"}:
        return CAT_CAMERA, "焦点"
    if n in {"cowboy_shot", "cowboy shot"}:
        return CAT_CAMERA, "景别"
    if n in {"clothes_writing"}:
        return CAT_CLOTHES, "花纹"
    if n in {"virtual_youtuber", "vtuber"}:
        return CAT_PERSON, "身份"
    if n in {"original"}:
        return CAT_CHARACTER, "原创"
    if n in {"traditional_media"}:
        return CAT_STYLE, "画风"
    if n in {"parody"}:
        return CAT_STYLE, "元信息"

    char = character_bucket(tag, n, zh, current_category, current_subcategory)
    if char:
        return char

    if is_artist(n):
        return CAT_STYLE, "画师"

    style = _style_bucket(n)
    if style:
        return style

    camera = _camera_bucket(n)
    if n.startswith("looking_") or n in {"eye_contact", "stare", "sideways_glance"}:
        camera = None
    if camera:
        return camera

    nsfw = _nsfw_bucket(n)
    if nsfw:
        return nsfw
    clothes = _clothes_bucket(n)
    if clothes:
        return clothes
    person = _person_bucket(n)
    if person:
        return person
    expression = _expression_bucket(n)
    if expression:
        return expression
    action = _action_bucket(n)
    if action:
        return action
    scene = _scene_bucket(n)
    if scene:
        return scene
    return None


def fallback(n: str, zh: str, current_category: str, current_subcategory: str) -> tuple[str, str]:
    merged = merge_primary(current_category)
    if merged == CAT_CHARACTER:
        sub = normalize_work_name(current_subcategory)
        if sub not in INVALID_WORK_SUBS:
            return CAT_CHARACTER, sub or "其他角色"
        return CAT_CHARACTER, "其他角色"
    if merged in CONTROLLED_SUBS:
        allowed = CONTROLLED_SUBS[merged]
        if current_subcategory in allowed:
            return merged, current_subcategory
        if merged == CAT_NSFW:
            return merged, "其他"
        if merged == CAT_CLOTHES:
            return merged, "其他服饰"
        if merged == CAT_MANUAL:
            return CAT_MANUAL, "LoRA调用" if n.startswith("<") else "画师权重"
        return merged, "其他"
    if merged == CAT_STYLE:
        return CAT_STYLE, "其他"
    # 无法判断时按中文线索
    text = zh or ""
    if any(k in text for k in ("角色", "从者", "舰娘")):
        return CAT_CHARACTER, infer_work(n, zh) or "其他角色"
    return CAT_PERSON, "其他"


def classify(tag: str, zh: str = "", current_category: str = "", current_subcategory: str = "") -> tuple[str, str]:
    """把任意 tag 映射到受控一级/二级分类。"""
    raw = tag or ""
    if is_lora(raw):
        return CAT_MANUAL, "LoRA调用"
    inner = parse_weighted(raw)
    if inner is not None:
        inner_n = _norm_key(inner)
        if is_artist(inner_n):
            return CAT_MANUAL, "画师权重"
        inner_result = classify_normalized(inner_n, inner, zh or "", "", "")
        if inner_result:
            return _finalize(inner_result)
        return CAT_MANUAL, "画师权重"

    cleaned = clean_tag(raw)
    n = _norm_key(cleaned)
    result = classify_normalized(n, cleaned, zh or "", current_category or "", current_subcategory or "")
    if result:
        return _finalize(result)

    if "," in cleaned:
        first = clean_tag(cleaned.split(",")[0])
        if first:
            fn = _norm_key(first)
            if fn != n:
                result = classify_normalized(fn, first, zh or "", current_category or "", current_subcategory or "")
                if result:
                    return _finalize(result)

    return _finalize(fallback(n, zh or "", current_category or "", current_subcategory or ""))


def _finalize(pair: tuple[str, str]) -> tuple[str, str]:
    cat, sub = pair
    cat = merge_primary(cat)
    if cat not in PRIMARY_CATEGORIES:
        cat = CAT_PERSON
    sub = (sub or "").strip() or "其他"
    sub = normalize_work_name(sub)
    if cat == CAT_CHARACTER:
        if sub in INVALID_WORK_SUBS:
            sub = "其他角色"
        return cat, sub
    allowed = CONTROLLED_SUBS.get(cat)
    if allowed and sub not in allowed:
        # 画风里误用「效果」
        if cat == CAT_STYLE and sub == "效果":
            return cat, "画风"
        if cat == CAT_CLOTHES:
            return cat, "其他服饰"
        return cat, "其他"
    return cat, sub
