from __future__ import annotations

import re
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

from .db import BASE_DIR
from .llm import BROWSER_USER_AGENT
from .manga_service import load_config

README_RAW_URL = "https://raw.githubusercontent.com/JadeCake5/night-wardrobe/master/README.md"
ZIP_DOWNLOAD_URL = "https://codeload.github.com/JadeCake5/night-wardrobe/zip/refs/heads/master"
CHECK_TIMEOUT_SECONDS = 15
DOWNLOAD_TIMEOUT_SECONDS = 30
# 数据黑名单：这些路径绝不从更新包覆盖，用户数据与运行时产物一律保留
PROTECTED_ENTRIES = (
    "tag_wardrobe.sqlite3",
    "gallery",
    "workflows",
    "manga",
    "manga_downloads",
    "manga_config.json",
    "tag_library.json",
    ".venv",
    "__pycache__",
    "video_decrypt",
)

FetchText = Callable[[str, int], str]
DownloadZip = Callable[[str, Path, int], Path]

VERSION_PATTERN = re.compile(r"当前版本：\*\*\s*v?(\d+)\.(\d+)\.(\d+)\s*\*\*")


class GithubUpdateError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def parse_remote_version(readme_text: str) -> str:
    """从公开仓 README 文本解析「当前版本：**vX.Y.Z**」，找不到时抛出错误。"""
    match = VERSION_PATTERN.search(str(readme_text or ""))
    if not match:
        raise GithubUpdateError("version_not_found", "远程 README 中未找到当前版本号，无法确认更新内容")
    return f"{match.group(1)}.{match.group(2)}.{match.group(3)}"


def compare_versions(current: str, remote: str) -> int:
    """比较两个版本号，当前落后返回 -1、相等返回 0、领先返回 1。格式非法视为相等。"""
    try:
        current_parts = tuple(int(p) for p in str(current).strip().lstrip("vV").split("."))
        remote_parts = tuple(int(p) for p in str(remote).strip().lstrip("vV").split("."))
    except ValueError:
        return 0
    length = max(len(current_parts), len(remote_parts))
    current_parts += (0,) * (length - len(current_parts))
    remote_parts += (0,) * (length - len(remote_parts))
    if current_parts < remote_parts:
        return -1
    if current_parts > remote_parts:
        return 1
    return 0


def _load_proxy() -> str:
    try:
        return str(load_config().get("proxy") or "").strip()
    except OSError:
        return ""


def _build_opener(proxy: str) -> urllib.request.OpenerDirector:
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    return urllib.request.build_opener()


def fetch_url_text(url: str, timeout: int) -> str:
    """拉取远程文本内容；GitHub raw 虽不设防，仍沿用浏览器 UA 惯例。"""
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_USER_AGENT})
    opener = _build_opener(_load_proxy())
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise GithubUpdateError(
            "remote_http_error",
            f"访问远程仓库失败：HTTP {exc.code}",
            502,
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GithubUpdateError(
            "network_error",
            f"访问远程仓库失败，请检查网络或代理设置：{exc}",
            502,
        ) from exc


def download_zip_file(url: str, dest_path: Path, timeout: int) -> Path:
    """把远程 zip 下载到 dest_path，返回落盘路径。"""
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_USER_AGENT})
    opener = _build_opener(_load_proxy())
    try:
        with opener.open(req, timeout=timeout) as resp, dest_path.open("wb") as target:
            shutil.copyfileobj(resp, target, 1024 * 256)
    except urllib.error.HTTPError as exc:
        dest_path.unlink(missing_ok=True)
        raise GithubUpdateError(
            "remote_http_error",
            f"下载更新包失败：HTTP {exc.code}",
            502,
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        dest_path.unlink(missing_ok=True)
        raise GithubUpdateError(
            "network_error",
            f"下载更新包失败，请检查网络或代理设置：{exc}",
            502,
        ) from exc
    if not dest_path.is_file() or dest_path.stat().st_size <= 0:
        dest_path.unlink(missing_ok=True)
        raise GithubUpdateError("download_empty", "下载的更新包为空，请稍后重试", 502)
    return dest_path


def _is_protected(relative: Path) -> bool:
    parts = relative.parts
    if not parts:
        return True
    return parts[0] in PROTECTED_ENTRIES


def _safe_target(root: Path, relative: Path) -> Path | None:
    """zip-slip 防护：规范化后必须仍落在 root 之内，否则返回 None 丢弃该条目。"""
    try:
        target = (root / relative).resolve()
        root_resolved = root.resolve()
    except OSError:
        return None
    if target == root_resolved or root_resolved not in target.parents:
        return None
    return target


def _resolve_zip_root(extract_dir: Path) -> Path | None:
    """codeload zip 解压后顶层是仓库目录（如 night-wardrobe-master），定位其中的 tag_manager 子树。"""
    roots = [p for p in extract_dir.iterdir() if p.is_dir()]
    if len(roots) != 1:
        return None
    subtree = roots[0] / "tag_manager"
    return subtree if subtree.is_dir() else None


def _write_file(path: Path, content: bytes) -> None:
    # zip 内的字节本身就是发布时的原始内容，直接字节拷贝；
    # 不经过文本编解码往返，二进制文件（.evideo 固件等）天然无损
    path.write_bytes(content)


class GithubUpdateService:
    def __init__(
        self,
        *,
        base_dir: Path = BASE_DIR,
        current_version: str = "",
        fetch_text: FetchText = fetch_url_text,
        download_zip: DownloadZip = download_zip_file,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.current_version = str(current_version or "").strip()
        self.fetch_text = fetch_text
        self.download_zip = download_zip

    def check(self) -> dict[str, Any]:
        """检查远程版本，返回当前版本、远程版本与更新状态。"""
        try:
            readme_text = self.fetch_text(README_RAW_URL, CHECK_TIMEOUT_SECONDS)
            remote_version = parse_remote_version(readme_text)
        except GithubUpdateError as exc:
            return {
                "current_version": self.current_version,
                "remote_version": "",
                "status": "unknown",
                "status_label": "检查失败",
                "message": exc.message,
            }
        comparison = compare_versions(self.current_version, remote_version)
        if comparison < 0:
            status, label, message = "behind", "发现新版本", f"发现新版本 v{remote_version}，建议立即更新"
        elif comparison > 0:
            status, label, message = "ahead", "本地版本更新", f"本地版本 v{self.current_version} 高于远程 v{remote_version}"
        else:
            status, label, message = "latest", "已是最新版本", "当前已是最新版本"
        return {
            "current_version": self.current_version,
            "remote_version": remote_version,
            "status": status,
            "status_label": label,
            "message": message,
        }

    def apply(self) -> dict[str, Any]:
        """下载更新包并白名单覆盖本地代码文件；任一环节失败即回滚已改动文件。"""
        with tempfile.TemporaryDirectory(prefix="wardrobe_update_") as temp_dir:
            temp_root = Path(temp_dir)
            zip_path = temp_root / "update.zip"
            extract_dir = temp_root / "extracted"
            extract_dir.mkdir()
            self.download_zip(ZIP_DOWNLOAD_URL, zip_path, DOWNLOAD_TIMEOUT_SECONDS)
            try:
                with zipfile.ZipFile(zip_path) as archive:
                    archive.extractall(extract_dir)
            except zipfile.BadZipFile as exc:
                raise GithubUpdateError("bad_zip", "更新包已损坏，不是有效的 zip 文件", 502) from exc

            subtree = _resolve_zip_root(extract_dir)
            if subtree is None:
                raise GithubUpdateError("bad_zip", "更新包结构异常，未找到 tag_manager 代码目录", 502)

            plan = self._build_plan(subtree)
            if not plan:
                raise GithubUpdateError("nothing_to_update", "更新包中没有可覆盖的代码文件", 502)

            backup_dir = temp_root / "backup"
            backed_up = self._backup(plan, backup_dir)
            written: list[str] = []
            try:
                for relative, source in plan:
                    target = self.base_dir / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    _write_file(target, source.read_bytes())
                    written.append(relative.as_posix())
            except Exception as exc:
                # 捕获 Exception 而非仅 OSError：UnicodeEncodeError 等非 IO 异常
                # 同样可能发生在写入途中，必须回滚避免半成品安装
                self._rollback(plan, backed_up, backup_dir)
                if isinstance(exc, OSError):
                    message = f"写入更新文件失败，已自动回滚：{exc}"
                else:
                    message = f"写入更新文件失败，已自动回滚：{type(exc).__name__}: {exc}"
                raise GithubUpdateError("write_failed", message, 500) from exc

        return {
            "current_version": self.current_version,
            "updated_count": len(written),
            "updated_files": written,
            "message": f"已更新 {len(written)} 个文件，请手动重启应用后生效",
        }

    def _build_plan(self, subtree: Path) -> list[tuple[Path, Path]]:
        """生成覆盖计划：仅 zip 内 tag_manager 子树中存在的代码文件，本地多余文件不动。"""
        plan: list[tuple[Path, Path]] = []
        for source in sorted(p for p in subtree.rglob("*") if p.is_file()):
            relative = source.relative_to(subtree)
            if _is_protected(relative):
                continue
            if _safe_target(self.base_dir, relative) is None:
                continue
            plan.append((relative, source))
        return plan

    def _backup(self, plan: list[tuple[Path, Path]], backup_dir: Path) -> set[Path]:
        """把将被覆盖的本地文件复制到备份目录，返回有备份的相对路径集合。"""
        backed_up: set[Path] = set()
        for relative, _source in plan:
            target = self.base_dir / relative
            if not target.is_file():
                continue
            backup_target = backup_dir / relative
            backup_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup_target)
            backed_up.add(relative)
        return backed_up

    def _rollback(self, plan: list[tuple[Path, Path]], backed_up: set[Path], backup_dir: Path) -> None:
        """回滚：恢复备份文件；原本不存在的文件删除，避免留下半成品。"""
        for relative, _source in plan:
            target = self.base_dir / relative
            if relative in backed_up:
                continue
            target.unlink(missing_ok=True)
        for relative in backed_up:
            backup_source = backup_dir / relative
            target = self.base_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_source, target)
