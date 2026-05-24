# 夜之主衣柜 (Night Wardrobe)

Stable Diffusion / ComfyUI 提示词管理工具。管理角色卡、画师配方、提示词工坊，以及带工作流的图库案例。

## 功能

- **Tag 库** — 按一级/二级分类浏览 tag，点击即选，一键复制提示词
- **角色卡** — 管理角色（LoRA、触发词、外貌特征、多套服装）
- **配方库** — 可复用提示词片段：画师串、场景预设、负面模板、绘图参数
- **工坊** — 交互式拼装提示词：选角色 → 选服装 → 选画师串 → 选场景 → 预览 → 复制
- **图库** — 成品图橱窗，自动提取 ComfyUI 工作流和提示词，支持拖拽到 ComfyUI 导入工作流
- **数据共享** — Tag 库 JSON 导入导出，图库 ZIP 打包分享

## 快速开始

### 环境要求

- Python 3.11+

### 安装

```bash
git clone https://github.com/Shiratamakeki/night-wardrobe.git
cd night-wardrobe
pip install -r tag_manager/requirements.txt
```

### 启动

```bash
python -m tag_manager.run
```

浏览器打开 `http://127.0.0.1:8765`

### Windows 一键部署

1. 双击 `tag_manager/setup_venv.bat` — 创建虚拟环境并安装依赖（仅首次）
2. 双击 `tag_manager/start.bat` — 启动服务

## 使用指南

### Tag 库

从 JSON 文件导入 tag 数据，或手动添加。支持按分类浏览、搜索、点击选择、一键复制。

### 角色卡

为每个常用角色创建卡片：
- **LoRA** — 文件名和权重
- **触发词** — 必须携带的 tag
- **外貌特征** — 发色、瞳色、耳朵等固定特征
- **服装套组** — 一个角色可以有多套服装，按需切换

### 配方库

保存可复用的提示词片段，分为四种类型：
- **画师串** — 多画师权重混合配方
- **场景预设** — 完整的动作+构图+场景组合
- **负面模板** — 不同强度的负面提示词
- **绘图参数** — sampler、steps、CFG、分辨率等

### 工坊

交互式拼装最终提示词：

1. 选择角色（自动带入 LoRA + 触发词 + 外貌）
2. 选择服装套组
3. 选择画师串
4. 选择场景预设
5. 选择负面模板
6. 添加自定义补充
7. 实时预览 → 一键复制

支持接入 LLM API 辅助优化提示词。

### 图库

将带 ComfyUI 工作流的 PNG 图片放入 `tag_manager/gallery/` 目录：

- 首页点击「扫描图库」自动提取元数据
- 点击图片放大查看，显示正/负提示词、模型、LoRA 信息
- 直接从浏览器拖拽图片到 ComfyUI 窗口即可导入工作流
- 支持 ZIP 导入导出，方便分享图库

### LLM 辅助

工坊内置 AI 优化按钮，接入 OpenAI 兼容 API：

1. 访问 `http://127.0.0.1:8765` 首页
2. 在工坊页面使用「AI 优化提示词」功能前，需先配置 LLM：

```
POST /llm/settings
base_url: API 地址（如 https://api.openai.com/v1）
api_key: 你的 API Key
model: 模型名（如 gpt-4o）
```

## 开发模式

设置环境变量启用开发功能（魔导书导入、图库扫描按钮）：

```bash
# Linux/Mac
WARDROBE_DEV=1 python -m tag_manager.run

# Windows
set WARDROBE_DEV=1
python -m tag_manager.run
```

## 数据存储

- 数据库：`tag_manager/tag_wardrobe.sqlite3`（SQLite，首次启动自动创建）
- 图库目录：`tag_manager/gallery/`
- 导出文件：`tag_manager/tag_library.json`

## 技术栈

- Python 3.11+
- FastAPI + Uvicorn
- Jinja2 模板
- SQLite
- Pillow（图片元数据读取）
- openpyxl（Excel 导入，开发模式）

## 目录结构

```
tag_manager/
├── app.py              # FastAPI 路由
├── db.py               # 数据库定义
├── gallery.py          # 图库扫描与 ZIP 导入导出
├── llm.py              # LLM API 调用
├── import_magic_book.py # 魔导书 Excel 导入（开发模式）
├── default_prompts.py  # 默认模板
├── run.py              # 启动入口
├── requirements.txt    # 依赖
├── gallery/            # 图库图片目录
├── static/
│   └── style.css
└── templates/
    ├── base.html
    ├── index.html
    ├── tags.html
    ├── characters.html
    ├── recipes.html
    ├── workshop.html
    └── gallery.html
```

## License

MIT
