# 夜之主衣柜

Stable Diffusion / ComfyUI 提示词管理工具。从魔导书 Excel 批量导入 tag，按分类浏览、挑选、组合提示词，管理带工作流的图库案例。

当前版本：**v1.24.2**（图库图片 meta 解析修复：ComfyUI 工作流中提示词直接以字符串存放在 Efficient Loader / WeiLin 等节点的 positive/negative 输入里，或经 ControlNetApplyAdvanced 等传递节点间接连到 KSampler，原回溯逻辑只认 text 输入与 conditioning/clip 链接导致 positive/negative 解析为空，现按连线意图沿同名输入继续回溯并读取字符串；JPEG 的 UserComment 常存于 EXIF 子 IFD(0x8769) 而非顶层，原读取只遍历顶层标签导致漏掉，现同时遍历子 IFD 并跳过 IFD 指针标签避免垃圾键。OpenAPI 应用元数据已同步为 **v1.24.2**）。含 v1.24.1（工坊 AI 提示词助手对话框 UI 微调：头部标题栏 56px→44px，设置齿轮与关闭按钮收紧为 28px 紧凑图标按钮（齿轮不再误吃全局紫色渐变按钮样式），composer 输入框压低（min-height 108px→60px、max-height 220px→150px，以更高优先级选择器覆盖 Island 构建产物样式），消息列表区域吃掉释放出的空间；面板高度改为跟随 flex 行自然撑满（sticky + max-height `calc(100vh - 108px)`），任何常用视口高度下页面不出垂直滚动条；CSS 缓存 `?v=85`。OpenAPI 应用元数据已同步为 **v1.24.1**）。含 v1.24.0（工坊 AI 提示词助手 API 配置对齐抽卡界面完善度：服务商预设下拉（硅基流动 / DeepSeek / OpenAI 兼容，选中自动填默认 Base URL 与模型，可手改）、按服务商分别记忆 Base URL / 模型 / API Key（localStorage `copilot_api_*` 前缀）、超时时间与重试次数设置（默认 60000ms / 3 次，服务端持久化到 `llm_settings`，旧客户端不带新字段时保留旧值不报错）、连接状态区分「已连接 / 已配置未测 / 未配置」、测试连接按配置超时与重试；CSS 缓存 `?v=83`。OpenAPI 应用元数据已同步为 **v1.24.0**）。含 v1.23.0（工坊 AI 提示词助手设置对齐抽卡：启用开关、服务地址/模型、默认 system prompt 写入同一份 `llm_settings`；`GET/POST /api/copilot/settings` 不回传明文密钥，空 Key 保留原值；工坊齿轮与助手面板齿轮以 Toast 反馈保存/测试/拉模型，不再整页刷新）。含 v1.22.0（视频解密开箱即用：解密核心已内置 AES-256-GCM / Scrypt，`CORE_VERSION` 2.0.3，兼容加密插件 2.0 生成的 `.evideo`；解密核心由上游作者授权以 MIT 内置，不再依赖外部解密仓库或本地解密配置文件。运行中任务展示 `progress` / `progress_message` 进度条。仓库根 `start.bat` 一键启动：自动选择 ≥3.11 最佳解释器，venv 位于 `tag_manager/.venv`，可用 `WARDROBE_PYTHON` 指定解释器。OpenAPI 应用元数据已同步为 **v1.22.0**）。含 v1.21.0（Workshop Copilot 会话持久化：正式 Session 存 SQLite，支持新建/切换/重命名/删除/搜索，刷新与离开工坊后可恢复 Diagnosis/Diff/Apply 状态；发送给 LLM 的历史经裁剪适配，当前工作区优先于旧快照；Pending 请求按 session_id 隔离。不含云同步、自动 Apply 或自动恢复旧 Prompt。同版后续重组 Session History UI 信息架构：IDE 式扁平 Session 触发条，搜索框收敛进切换 Popover，重命名/删除收敛到独立「会话历史」视图的 ⋯ 菜单，旧上下文改 compact 提示横幅；历史 Diff 在当前 Prompt 已变化时进入 stale 态禁止直接 Apply，必须用当前 Prompt 重新检查后再显式应用）。含 v1.20.1（LLM 设置改为工坊内嵌：移除侧栏「AI 设置」独立选项卡；工坊 header 增加齿轮入口，以既有 folder-dialog 保存 OpenAI 兼容配置并复用 `POST /llm/settings`；`/llm` 仅作兼容设置页，去掉「对话 / 辅助分类」主入口，由工坊 Copilot 承担）。含 v1.20.0（工坊稳定性与 Copilot 工具调用：修复 SPA 二次进入时内联脚本因顶层 `const`/`let` 死亡；工坊工具栏 AI 助手 / 复制全部 / 更多操作以及 Positive/Negative 复制改为 SVG 图标按钮，并移除格式化/排序/清理重复共 6 个死占位；Copilot 建议列表从重背景卡片改为紧凑可勾选列表，checkbox 不再吃全局 input 样式；侧栏新增「AI 设置」入口指向既有 `/llm`；Copilot 落地真 function-calling 工具循环——`llm.py` 新增 `chat_completion_with_tools`，新建 `copilot_tools.py` 提供 7 个只读工具，`copilot_service` 加 `_tool_loop`、服务商不支持 tools 时静态降级，终局仍走 JSON 校验与一次纠正重试，端点支持 `use_tools=false`。AI 仍不自动 Apply）。含 v1.19.0（工坊 Copilot 接入真实服务端 LLM：新增 `POST /api/workshop/copilot`，复用 `llm_settings` 与 `chat_completion_messages`，`llm.py` 增加可选 `response_format` 透传以启用 JSON mode；服务端 `copilot_service.py` 集中维护 system prompt 与 7+1 动作预设、组装 messages、JSON 提取 + Pydantic schema 校验 + 一次纠正重试，畸形输出安全失败、绝不把 raw text 当成功喂给 Diff；前端新增 `realBackend.ts` 以 fetch + 90s AbortController 调本地端点，`CopilotService.backend` 由 mock 切到真实，`App.tsx` 补 error turn；密钥仅存服务端，前端源码与构建产物均无密钥。同版修复生命周期：收起 Copilot 只隐藏 Pane、不再 unmount，会话保留，离开 Workshop 页面 cleanup 才卸载 Island。AI 仍不自动 Apply，须逐条勾选并显式「应用选中项 / 应用全部」才写回 Prompt）。含 v1.18.0（工坊 Copilot 改为隔离 React Island：`frontend/copilot` 以 Vite 构建到 `static/copilot/`，源码接入 Vercel AI Elements 的 Conversation / Suggestion / Task 与精简 PromptInput / Message 外壳；诊断卡、Diff、上下文开关仍为工坊自研；docked 布局与 `applyOperations` 留在原生壳。含 v1.17.0 工坊 AI 助手改为桌面 IDE 式停靠面板：与配方区 / Prompt 工作区同一布局层级，打开后重新分配宽度而不是 overlay 遮罩；宽屏 docked，视口不足 1200px 才降级为 overlay；面板之间可拖拽调宽；空态顶对齐，composer 固定在面板底部；关闭语义为收起面板。含 v1.16.0 工坊「AI 助手」抽屉重构为对话式面板：会话流 + 用户/助手/错误三类消息、执行阶段列表、结构化诊断卡与 diff 卡；composer 自增长、内嵌发送按钮、Enter 发送 / Shift+Enter 换行；`[Positive][Negative][Recipe]` 上下文开关直接决定发送载荷；空态给 4 枚建议 chips 与「更多」展开其余 3 个快捷操作，会话开始即隐藏；AI 建议必须逐条勾选并显式点击「应用选中项 / 应用全部」才写回 Prompt，应用或放弃后该卡转只读；会话不持久化，抽屉关闭即清空。交互规范参考 vercel/ai-elements（Apache-2.0），未引入其代码与依赖，本版仍为前端架构与演示数据，真实 AI 接入待后续版本）。含 v1.15.0 工坊页紧凑 Prompt 工作台（紧凑 Header + 单层配方面板、× 清除内嵌下拉框、自定义补充按需展开、分类过滤 chips 兼作图例、Prompt 编辑器块带 tag/字符统计与「已编辑」徽标、点击文本即可编辑且手工编辑不再被配方变化静默覆盖、「清除全部」二次确认）、v1.14.1 APNG 首帧独立停留时长（封面帧与后续帧可分别设置延迟，默认首帧 2000ms）、v1.14.0 漫画工具页紧凑桌面工具布局（segmented 模式切换、定宽表单、sticky 任务列表、设置抽屉）、v1.13.x 漫画下载页（JM 车牌号后台下载整本漫画合成 PDF/APNG，首帧可上传，单任务队列、阶段进度、代理与镜像域名可配）与搜索框收紧；v1.12.2 图库/工作流扫描刷新图标旋转动效，v1.12.1 Tag 库「Tag修改」开关从工作台移到页面头部；工作流页工具栏与文件夹卡菜单按图库风格纯图标化，上传折叠面板收为图标按钮，气泡开关逻辑共享进 folder-management.js。含 v1.12.0 图库文件夹/图片卡右上角下拉菜单改图标按钮 + 文字提示；视频解密页改 AJAX 局部刷新：上传完成、任务终态、删除均只局部替换任务列表，不再整页跳转重置界面位置。含 v1.11.0 图库工具栏纯图标化与上传/导入定向入库、增量扫描提速，v1.10.2 Tag 编辑/新增的二级分类随一级分类级联与配方库复制按钮修复、v1.10.1 LoRA 预览图顶部对齐、v1.10.0 全库约 6000 条 Tag 重分类（合并重叠一级分类、清掉 Excel 表头垃圾二级分类、角色按作品归组）、v1.9.1 工坊角色下拉框撑宽修复与 v1.9.0 全页面紧凑工具栏化。Tag 开放 API 的接口前缀保持 `/api/v1`。

## 功能

- **Tag 库** — 按一级/二级分类浏览 tag，点击即选；预览模式支持带让位动画的拖动排序
- **Tag 库开放 API** — 为其他 Agent 提供版本化查询、单项/批量管理、分类维护和整库交换接口
- **角色卡** — 管理角色特征、服装和可复用提示词
- **配方库** — 保存常用的正负提示词和生成参数组合
- **提示词工坊** — 组合 Tag、角色和配方，形成可复制的完整提示词；首次进入即可使用全部下拉选项
- **提示词图库** — 应用启动时自动扫描一次本地图片，提取 ComfyUI 工作流和提示词元数据
- **工作流库** — 按文件夹管理 ComfyUI workflow JSON，可下载或拖入 ComfyUI
- **视频解密** — 开箱即用：流式上传插件 2.0 生成的 `.evideo`，由内置核心认证解密并无重编码整理为带完整播放索引的 H.264/AAC MP4
- **LoRA 库** — 上传 .safetensors 只读文件头秒级解析（基础模型/维度/触发词/标签频率），Civitai 元数据与预览图合并成卡片入库，一键复制触发词；文件本体不落盘
- **漫画下载** — 输入 JM 车牌号后台下载整本漫画，合成 PDF 或 APNG 动画（首帧可上传），或直接用本地图片合成 APNG；产物分类保存到可配置输出目录
- **文件夹管理** — 图库与工作流支持新建、移动、删除、递归影响确认和失败恢复
- **LLM 助手** — 接入大模型 API；工坊齿轮与助手面板可开关启用状态、配置服务地址/模型与默认提示词，与抽卡共用服务端设置；Copilot 对话承担辅助分类与提示词建议
- **AI 提示词抽卡** — 共用服务端 LLM 配置，将抽卡数据保存到 SQLite
- **魔导书导入** — 从 `提示词/魔导书.xlsx` 批量导入 tag，自动识别分类和二级分类

## 快速部署（Windows）

在仓库根目录双击 `start.bat`。脚本会自动选择本机 **Python 3.11 或更高** 的最佳解释器，在 `tag_manager/.venv` 创建虚拟环境并安装依赖，然后启动服务。

找不到合格解释器时，脚本会给出安装指引：

```text
winget install -e --id Python.Python.3.12
```

或从官网下载：<https://www.python.org/downloads/windows/>（安装时勾选 Add python.exe to PATH）。

若要指定解释器，设置环境变量 `WARDROBE_PYTHON` 指向 `python.exe` 的完整路径后再运行 `start.bat`。

浏览器打开 `http://127.0.0.1:8765`

## 手动安装

需要 Python 3.11+。在仓库根目录：

```bash
python -m venv tag_manager/.venv
tag_manager\.venv\Scripts\python.exe -m pip install -r tag_manager/requirements.txt
tag_manager\.venv\Scripts\python.exe -m tag_manager.run
```

已有 3.11+ 环境时也可：

```bash
pip install -r tag_manager/requirements.txt
python -m tag_manager.run
```

## 目录结构

```
tag_manager/
├── app.py                 # FastAPI 路由
├── db.py                  # SQLite 数据库定义与操作
├── tag_api.py             # 面向外部 Agent 的 Tag 库 v1 API
├── run.py                 # 启动入口
├── import_magic_book.py   # 魔导书 Excel 导入逻辑
├── tag_taxonomy.py        # Tag 全量分类器（受控一/二级分类）
├── tag_taxonomy_maps.py   # 作品族与角色对照表
├── organize_tag_library.py # 全库重分类入口（默认 dry-run，--apply 写库）
├── gallery.py             # 图库扫描
├── workflows.py           # 工作流扫描、导入与导出
├── folder_ops.py          # 图库/工作流共享文件夹操作
├── video_crypto.py          # 内置解密核心（AES-256-GCM / Scrypt，CORE_VERSION 2.0.3）
├── video_decrypt_adapter.py # 运行环境自检与错误映射（薄适配，调用内置核心）
├── video_decrypt_service.py # 流式上传、任务队列、进度字段与受管文件
├── video_decrypt_routes.py  # 视频解密页面与 HTTP 接口
├── find_python.py           # 探测本机 Python 3.11+（供仓库根 start.bat 调用）
├── llm.py                 # LLM API 调用
├── default_prompts.py     # 默认模板和系统提示词
├── tag_wardrobe.sqlite3   # SQLite 数据库（自动生成）
├── requirements.txt       # 依赖列表
├── static/
│   ├── style.css          # 主界面样式
│   ├── folder-management.js # 文件夹菜单与弹窗交互
│   └── gacha/             # AI 提示词抽卡页面
└── templates/
    ├── base.html          # 布局
    ├── index.html         # 首页
    ├── tags.html          # Tag 库
    ├── characters.html    # 角色卡
    ├── recipes.html       # 配方库
    ├── workshop.html      # 提示词工坊
    ├── gallery.html       # 图库
    ├── workflows.html     # 工作流库
    ├── video_decrypt.html # 视频解密
    ├── _folder_management_dialogs.html # 共用文件夹弹窗
    └── llm.html           # LLM 设置兼容页
```

## 使用流程

### 1. 导入 Tag

将 `魔导书.xlsx` 放在 `提示词/` 目录下，首页点击「从魔导书重新导入」。

Excel 格式要求：
- 每个 sheet 对应一个一级分类（如 `1.镜头`、`2.人物`）
- 每两列为一组：左列英文 tag，右列中文解释
- 行内出现的中文短标题会被识别为二级分类

### 2. 浏览和挑选 Tag

进入 Tag 库页面：
- 点击一级分类 tab 筛选大类
- 点击二级分类 tab 进一步细分
- 点击 tag 卡片加入已选区域
- 点击「复制已选」将提示词复制到剪贴板

### 3. 管理分类

- 一级分类栏末尾点击「+ 新增分类」
- 开启「修改 Tag 模式」后，分类旁出现删除按钮
- 二级分类在编辑 tag 或新增 tag 时通过下拉框管理

### 4. 图库

将图片放入 `tag_manager/gallery/`，应用每次启动时会自动扫描一次并提取可识别的 ComfyUI 或生成参数元数据。运行期间新增素材后，也可以在图库点击「扫描图库」，或直接上传图片、导入 ZIP。

### 5. 工作流库

将 ComfyUI workflow JSON 放入 `tag_manager/workflows/`，进入工作流页面点击「扫描工作流」。工作流卡片可下载，也可直接拖到 ComfyUI 中导入。

### 6. 管理图库和工作流文件夹

- 文件夹卡片右上角的竖排三点菜单提供“移动到……”和“删除文件夹”。
- 进入子目录后，也可在工具栏管理当前文件夹；根目录不能移动或删除。
- 非空文件夹删除前会列出子文件夹、已管理文件和其他文件数量，必须额外勾选确认。
- 移动后数据库记录 ID、标题、分类、备注、评分等人工字段保持不变。
- 同名目标、自身及自身后代会被拒绝，不会自动覆盖或合并。

详细操作见 [文件夹管理使用说明](docs/05-参考资料/文件夹管理使用说明.md)。

### 7. 解密加密视频

开箱即用：解密核心已内置（AES-256-GCM / Scrypt，兼容加密插件 2.0 生成的 `.evideo`）。解密核心由上游作者授权以 MIT 内置。进入侧边栏「视频解密」，选择 `.evideo`、输入密码并提交，完成后下载带普通索引、可显示总时长和拖动进度的 MP4。

- 上传按 1 MiB 分块写入，不会一次性把完整视频读入内存。
- 同一时间只处理一个视频，其他任务依次排队（队列串行）。
- 密码只在当前请求和任务内存中使用，不写入数据库或任务历史（密码不落库）。
- 应用重启时未完成任务会标记为「已中断」，需要重新提交密码。
- `.evideo` 使用 Scrypt 派生密钥与 AES-256-GCM 认证加密，密码错误或密文被篡改都会终止并清理部分输出。
- 解密直接恢复已压缩的 H.264/YUV420P + AAC MP4，不转码、仅重封装播放索引，不损失画质。
- 2.0 不兼容 1.x 的像素置换 MKV；旧文件应使用保留的 1.4.0 工具先恢复。

### 8. LLM 助手

在 LLM 助手页面配置 API 地址、密钥和模型名，即可用大模型辅助整理提示词。

### 9. 外部 Agent 管理 Tag 库

- API 根路径：`http://127.0.0.1:8765/api/v1`
- 交互式接口文档：`http://127.0.0.1:8765/docs`
- OpenAPI 文件：`http://127.0.0.1:8765/openapi.json`
- 支持 Tag 单项增删改查、最多 500 条批量覆盖/删除、分类与二级分类维护、整库导入导出。

完整字段、错误码和调用示例见 [Tag 库开放 API 使用说明](docs/05-参考资料/Tag库开放API使用说明.md)。

## 数据存储

使用 SQLite，数据库文件为 `tag_manager/tag_wardrobe.sqlite3`，首次启动自动创建。

主要表：
| 表 | 用途 |
|---|---|
| categories | 分类定义（名称、排序、用途） |
| tags | 单个 tag（英文、中文、分类、二级分类、来源） |
| tag_groups | 提示词组合（正/负提示词） |
| prompt_templates | 提示词模板 |
| gallery_images | 图库图片及元数据 |
| workflows | 工作流路径、节点信息和人工维护字段 |
| llm_settings | LLM API 配置 |
| characters | 角色卡基础信息 |
| character_outfits | 角色服装与对应提示词 |
| recipes | 配方与生成参数 |
| gacha_store | AI 提示词抽卡的非敏感用户数据 |
| video_decrypt_jobs | 视频解密任务状态、受管相对路径与错误摘要（不保存密码） |

## 本地共同文档

`docs/` 用于不同 agent 共享任务交接、计划、架构、开发记录、测试报告和使用说明。该目录包含本地工作资料并受 `.gitignore` 忽略，入口为 [多 Agent 共同文档索引](docs/README.md)。

## 技术栈

- Python 3.11+
- FastAPI + Uvicorn
- Jinja2 模板
- SQLite（无需额外数据库）
- openpyxl（Excel 读取）
