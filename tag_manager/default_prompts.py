DEFAULT_SYSTEM_PROMPT = """你是"夜之主衣柜"的提示词整理助手。你的任务是帮助用户整理 Stable Diffusion / ComfyUI 的 tag、提示词组合和图库案例。回答时优先使用逗号分隔的英文 tag，并保留必要的中文解释。不要擅自引入未成年人、强迫、血腥或违法内容。分类时尽量使用：镜头、人物、服饰、表情、动作、场景道具、风格、质量词、负面词、NSFW。"""

DEFAULT_POSITIVE_TEMPLATE = """masterpiece, best quality, high quality, detailed, absurdres,
{subject}, {character}, {lora},
{appearance}, {clothing}, {pose}, {expression},
{scene}, {lighting}, {style}"""

DEFAULT_NEGATIVE_TEMPLATE = """low quality, worst quality, bad quality, bad anatomy, bad hands,
extra fingers, missing fingers, fused fingers, deformed body,
text, watermark, username, censored, mosaic censoring"""
