"""从 提示词/ 目录的 md 文件批量导入角色卡和配方数据。"""
from __future__ import annotations

from .db import upsert_character, add_outfit, upsert_recipe


def import_all() -> dict[str, int]:
    counts = {"characters": 0, "outfits": 0, "recipes": 0}

    # ─── 角色卡 ───────────────────────────────────────────────────────────────

    chars = [
        {
            "name": "花园 senera3",
            "lora": "IL_花園Senera3_v1",
            "lora_weight": 1.0,
            "trigger_words": "senera3",
            "appearance": "1girl, solo, animal ears, cat ears, cat tail, fox ears, mini wings, blonde hair, blue eyes, hair between eyes, ahoge, hair bell, x hair ornament, maid headdress, very long hair, two side up, low twintails",
            "notes": "花园角色，猫耳女仆风",
        },
        {
            "name": "乃萝",
            "lora": "Ayatsuki Nora0.3_lokr",
            "lora_weight": 0.8,
            "trigger_words": "ayatsuki nora",
            "appearance": "1girl, purple hair, blue eyes, hair bow, hair flower, short eyebrows, thick eyebrows, tail bow, small breasts, virtual youtuber",
            "notes": "紫发蓝瞳 VTuber",
        },
        {
            "name": "铃兰（可爱狐娘）",
            "lora": "linglan-SDXL-lora-2024.10.19-version1",
            "lora_weight": 0.4,
            "trigger_words": "",
            "appearance": "1girl, fox girl, fox ears, fox tail, very long hair, white hair, heterochromia, blue eyes, purple eyes, large tail, large ears, flat chest",
            "notes": "白发异色瞳狐娘，搭配可爱风格插画LoRA使用",
        },
        {
            "name": "糕（浣熊娘）",
            "lora": "",
            "lora_weight": 1.0,
            "trigger_words": "gao",
            "appearance": "1girl, loli, raccoon girl, animal ears, animal ear fluff, tail, long brown hair, bangs, small body, petite frame, short stature",
            "notes": "浣熊娘角色",
        },
        {
            "name": "唯江",
            "lora": "weijiang_v2",
            "lora_weight": 1.0,
            "trigger_words": "weijiang, weijiang blue",
            "appearance": "1girl, cat ears, streaked hair, hair between eyes, hair ornament, blue hair, long hair, blue eyes, ahoge, very long hair, black hair",
            "notes": "蓝发猫耳",
        },
        {
            "name": "桃梓",
            "lora": "weijiang_v2",
            "lora_weight": 1.0,
            "trigger_words": "weijiang, weijiang pink",
            "appearance": "1girl, cat ears, streaked hair, hair between eyes, hair ornament, long hair, pink eyes, ahoge, very long hair, white hair, pink hair",
            "notes": "粉发猫耳，和唯江共用LoRA",
        },
        {
            "name": "莓华",
            "lora": "",
            "lora_weight": 1.0,
            "trigger_words": "Misono Ichika",
            "appearance": "dog ears, dog tail, multiple hair bows, minibow",
            "notes": "犬耳角色，有多套服装",
        },
    ]

    for c in chars:
        cid = upsert_character(**c)
        if cid:
            counts["characters"] += 1

    # ─── 莓华服装套组 ─────────────────────────────────────────────────────────

    meihua_outfits = [
        {
            "name": "女仆装",
            "tags": "crown braid, low twintails, hair flower, white flower, maid headdress, maid, white shirt, white thighhighs, center frills, frilled apron, waist apron, white frills, pink frills, pink bowtie, heart button, puffy long sleeves, sleeve bow, pink dress, light pink apron, frilled dress, short dress, back bow, white sleeve cuffs, frilled sleeve cuffs, collared shirt, bow legwear",
        },
        {
            "name": "常服",
            "tags": "low twintails, crown braid, hair flower, white flower, casual, black choker, pink shirt, long sleeves, frilled camisole, white camisole, layered skirt, brown skirt, white skirt, side cutout, brown pantyhose, front-tie top, center opening",
        },
        {
            "name": "情趣内衣",
            "tags": "crown braid, low twintails, hair flower, white flower, black collar, white babydoll, frilled babydoll, paw gloves, white panties, frilled panties, pink panties, frilled thigh strap, single garter strap, paw shoes",
        },
        {
            "name": "婚纱",
            "tags": "hair flower, white veil, bridal veil, see-through veil, lace-trimmed veil, wedding dress, elbow gloves, white gloves, white dress, strapless dress, pink bow, layered dress, dress bow",
        },
    ]

    from .db import connect
    with connect() as conn:
        meihua = conn.execute("SELECT id FROM characters WHERE name='莓华'").fetchone()
    if meihua:
        for o in meihua_outfits:
            add_outfit(meihua["id"], name=o["name"], tags=o["tags"])
            counts["outfits"] += 1

    # ─── 配方：画师串 ─────────────────────────────────────────────────────────

    artist_mixes = [
        {
            "name": "A套（tsubasa 主导）",
            "positive_prompt": "(shiratamaco:0.3),(chen bin:0.7),(ame usari:0.6),(rurudo:0.6),(kani biimu:0.6),(tsubasa tsubasa:0.8),(momozu komamochi:0.6),(chihiro \\(khorosho\\):0.6),(shiny hair:0.6)",
            "notes": "tsubasa 0.8 主导，chen bin 0.7 精致立绘，多画师融合萌系风格",
        },
        {
            "name": "B套（hoshi 主导）",
            "positive_prompt": "(shiratamaco:0.3),(ame usari:0.7),(kani biimu:0.6),(chihiro \\(khorosho\\):0.6),(hoshi \\(snacherubi\\):0.9),(yuizaki kazuya:0.5),(tyakomes:0.8)",
            "notes": "hoshi 0.9 主导，tyakomes 0.8 次主导，偏精致萌系",
        },
    ]
    for r in artist_mixes:
        upsert_recipe(name=r["name"], type="artist_mix", positive_prompt=r["positive_prompt"], notes=r["notes"], source="提示词目录导入")
        counts["recipes"] += 1

    # ─── 配方：负面模板 ───────────────────────────────────────────────────────

    negatives = [
        {
            "name": "轻量负面",
            "negative_prompt": "bad quality, worst quality, worst detail",
            "notes": "日常出图用，最简负面",
        },
        {
            "name": "标准负面",
            "negative_prompt": "worst quality, worst detail, low quality, lowres, blurry, (bad anatomy:1.2), (bad hands:1.5), (missing fingers:1.5), (extra fingers:1.5), fused fingers, mutated hands, text, username, watermark, (monochrome:1.1), (grayscale:1.1)",
            "notes": "通用推荐，覆盖质量+手部+画面干扰",
        },
        {
            "name": "重型负面",
            "negative_prompt": "worst quality, worst detail, low quality, lowres, blurry, error, (bad anatomy:1.2), (bad hands:1.5), (missing fingers:1.5), (extra fingers:1.5), (three hands:1.5), (three arms:1.5), fused fingers, claw hands, mutated, deformed, extra arms, extra digit, fewer digits, extra limb, cross-eyed, multiple girls, extra character, text, username, watermark, logo, (censorbar:1.2), (mosaic:1.2), (monochrome:1.1), (grayscale:1.1)",
            "notes": "复杂构图用，全面覆盖",
        },
    ]
    for r in negatives:
        upsert_recipe(name=r["name"], type="negative", negative_prompt=r["negative_prompt"], notes=r["notes"], source="提示词目录导入")
        counts["recipes"] += 1

    # ─── 配方：场景预设 ───────────────────────────────────────────────────────

    scenes = [
        {
            "name": "花园常规（女仆站立）",
            "positive_prompt": "senera3, 1girl, :3, animal ears, apron, blue bow, blue eyes, bow, brown hair, cat ears, cat girl, cat tail, closed mouth, cookie, dress, dutch angle, flower, food, frills, gloves, long hair, long sleeves, looking at viewer, maid headdress, ribbon, shirt, shoes, sleeveless, solo, standing, teacup, two side up, upper body, very long hair, virtual youtuber, white footwear, x hair ornament, frilled thigh strap, slim legs, very delicate light",
            "negative_prompt": "bad quality, worst quality, worst detail",
            "notes": "花园角色女仆日常",
        },
        {
            "name": "花园测试（可爱猫娘）",
            "positive_prompt": "senera3, 1girl, solo, toddler girl, (yellow hair:1.2), long hair, blue eyes, blushing, smile, (cat mouth:1.3), cute face, (cat ears, animal ears, ear fluff:1.2), (large cat tail:1.3), (maid headdress:1.2), (blue jacket:1.3), open jacket, long sleeves, (white maid dress, frills, apron:1.2), (white thighhighs:1.3), garter straps, white footwear, standing, tilting head, cute pose, bright lighting, soft colors",
            "negative_prompt": "worst quality, worst detail, low quality, (bad anatomy:1.2), (bad hands, missing fingers, extra fingers, three hands, three arms:1.5), fused fingers, claw hands, mutated, deformed, swimsuit, (censorbar, mosaic:1.2), text, username, watermark, blurry, lowres, error, (monochrome, grayscale:1.1), chibi, multiple girls, multiple views, doll, plush, stuffed toy, figurine, mascot, floating, extra character",
            "notes": "花园角色可爱测试版",
        },
        {
            "name": "可爱狐娘通用",
            "positive_prompt": "1girl, solo, kawaii, loli, fox_girl, fox ears, very long hair, long hair, (ears down:1.5), (large_tail:1.4), young girl, fox tail, (white hair:1.6), (heterochromia:1.4), (blue purple pupil:1.5), a tail, (large_ears:1.2), (flat chest:1.1), (purple eyes:1.1), (fox_ears:1.4), fox girl, fox tail, fox ears, animal ears, aged down, frilled thigh strap, slim legs, wrist cuffs, half-closed_eye, jitome",
            "negative_prompt": "yellow eyes, golden eyes, green eyes, red eyes, outline, text, username, logo, low quality, worst quality, bad anatomy, inaccurate limb, bad composition, inaccurate eyes, extra digit, fewer digits, extra arms, 3girls, watermark, missing fingers, mutated hands, too many fingers, malformed hands, cross-eyed, extra limb, fused fingers, bad hands, too many feet",
            "notes": "铃兰角色通用场景",
        },
        {
            "name": "花园谬思（狐娘幼化）",
            "positive_prompt": "senera3, 1girl, :3, animal ears, apron, blue bow, blue eyes, bow, brown hair, cat ears, cat girl, cat tail, closed mouth, cookie, dress, dutch angle, flower, food, frills, gloves, long hair, long sleeves, looking at viewer, maid headdress, ribbon, shirt, shoes, sleeveless, solo, sitting, teacup, two side up, upper body, very long hair, virtual youtuber, white footwear, x hair ornament, frilled thigh strap, slim legs, very delicate light, 1girl, aged down, low twintails, long hair, slim legs, white pantyhose, two side up, ahoge, fox girl, fox ears, (blonde hair:1.3), hair between eyes, (red streaked hair:1.2), (streaked hair:1.3), (gradient hair:1.3), (red gradient hair:1.3), red eyes, hair bow, mini wings, blush, hair bell",
            "negative_prompt": "bad quality, worst quality, worst detail",
            "notes": "花园+谬思融合，狐娘幼化版",
        },
        {
            "name": "脱袜场景",
            "positive_prompt": "(asymmetrical legwear:1.3), (one leg bare, one leg in white stocking:1.3), (sitting:1.1), (removing stocking:1.2), translucent white stockings, feet facing camera, soles visible, (hand on thigh:1.1), feet focus, toes visible through stockings, detailed feet, realistic fabric texture, soft lighting",
            "negative_prompt": "bad quality, worst quality, worst detail",
            "notes": "脱袜动作场景，足部特写",
        },
        {
            "name": "后背式（趴卧）",
            "positive_prompt": "1girl, loli girl, solo, young raccoon girl, (animal ears, animal ear fluff:1.2), tail, long brown hair, bangs, cute, small body, petite frame, short stature, (nude, uncensored:1.3), no clothes, small breasts, navel, ass, (lying on stomach:1.3), (prone pose:1.2), (from behind:1.4), back view, (foreshortening:1.2), (looking back at viewer:1.2), on bed, white bed sheet, messy bed, pov, depth of field, indoor",
            "negative_prompt": "worst quality, worst detail, low quality, (bad anatomy:1.2), (bad hands, missing fingers, extra fingers, three hands, three arms:1.5), fused fingers, claw hands, mutated, deformed, clothes, panties, bra, swimsuit, (censorbar, mosaic:1.2), text, username, watermark, blurry, lowres, error, (monochrome, grayscale:1.1)",
            "notes": "糕角色后背趴卧场景",
        },
    ]
    for r in scenes:
        upsert_recipe(name=r["name"], type="scene", positive_prompt=r["positive_prompt"], negative_prompt=r.get("negative_prompt", ""), notes=r["notes"], source="提示词目录导入")
        counts["recipes"] += 1

    # ─── 配方：绘图参数 ───────────────────────────────────────────────────────

    import json
    params_recipes = [
        {
            "name": "PVC 人像参数",
            "params_json": json.dumps({"sampler": "Euler", "steps": 30, "cfg": "3.8-6", "resolution": "768x1280 / 920x1536 / 1024x1024 / 1024x1386 / 1152x1536", "clip_skip": 2, "hires_scale": "max 1.5x"}, ensure_ascii=False),
            "notes": "PVC材质推荐参数，适合人像角色",
        },
    ]
    for r in params_recipes:
        upsert_recipe(name=r["name"], type="params", params_json=r["params_json"], notes=r["notes"], source="提示词目录导入")
        counts["recipes"] += 1

    return counts


if __name__ == "__main__":
    result = import_all()
    print(f"导入完成: {result['characters']} 角色, {result['outfits']} 服装套组, {result['recipes']} 配方")
