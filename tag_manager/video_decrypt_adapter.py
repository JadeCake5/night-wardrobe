from __future__ import annotations

import errno
import importlib.util
import json
import os
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import ModuleType

from .db import BASE_DIR

CONFIG_PATH = BASE_DIR / "video_decrypt_config.json"
UPSTREAM_ENV_NAME = "WARDROBE_VIDEO_DECRYPTOR_ROOT"


@dataclass(frozen=True)
class VideoDecryptRuntimeInfo:
    available: bool
    upstream_root: str = ""
    upstream_version: str = ""
    algorithm: str = ""
    av_version: str = ""
    cryptography_version: str = ""
    file_extension: str = ""
    message: str = ""


class VideoDecryptError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_upstream_root(
    explicit_root: str | os.PathLike[str] | None = None,
    config_path: Path = CONFIG_PATH,
) -> Path:
    if explicit_root:
        candidate = Path(explicit_root)
    elif os.environ.get(UPSTREAM_ENV_NAME, "").strip():
        candidate = Path(os.environ[UPSTREAM_ENV_NAME].strip())
    elif config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VideoDecryptError("runtime_unavailable", f"视频解密配置无法读取：{exc}") from exc
        root_value = str(config.get("upstream_root", "")).strip()
        if not root_value:
            raise VideoDecryptError("runtime_unavailable", "视频解密配置缺少 upstream_root")
        candidate = Path(root_value)
    else:
        raise VideoDecryptError(
            "runtime_unavailable",
            f"未配置视频解密工具；请设置 {UPSTREAM_ENV_NAME} 或创建 {config_path.name}",
        )

    root = candidate.expanduser().resolve()
    if not root.is_dir() or not (root / "video_crypto.py").is_file():
        raise VideoDecryptError("runtime_unavailable", f"视频解密工具目录无效：{root}")
    return root


@lru_cache(maxsize=8)
def _load_upstream_module(module_path: str, modified_ns: int) -> ModuleType:
    del modified_ns
    path = Path(module_path)
    module_name = f"wardrobe_video_crypto_{abs(hash(path.as_posix()))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise VideoDecryptError("runtime_unavailable", "无法创建上游视频解密模块加载器")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise VideoDecryptError("runtime_unavailable", f"无法加载上游视频解密模块：{exc}") from exc
    if not callable(getattr(module, "decrypt_video_file", None)):
        raise VideoDecryptError("runtime_unavailable", "上游模块缺少 decrypt_video_file()")
    return module


def load_upstream_module(root: Path) -> ModuleType:
    module_path = root / "video_crypto.py"
    return _load_upstream_module(str(module_path), module_path.stat().st_mtime_ns)


def read_upstream_version(root: Path) -> str:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return "未知"
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return "未知"
    return str(data.get("project", {}).get("version", "未知"))


def map_upstream_error(error: Exception) -> VideoDecryptError:
    message = str(error).strip() or "视频解密失败"
    lowered = message.lower()
    if isinstance(error, OSError) and getattr(error, "errno", None) == errno.ENOSPC:
        return VideoDecryptError("disk_full", "磁盘空间不足，未生成输出文件")
    if "密码错误" in message or "invalidtag" in lowered:
        return VideoDecryptError(
            "authentication_failed",
            "密码错误或密文文件已损坏，未生成输出文件",
        )
    if "不是本插件" in message or "必须使用 .evideo" in message:
        return VideoDecryptError("unsupported_protocol", "文件不是受支持的 .evideo 密文")
    if "协议版本" in message or "协议版本不受支持" in message:
        return VideoDecryptError("unsupported_version", "密文协议版本不受支持")
    if any(marker in message for marker in ("密文文件头", "密文视频负载", "输入文件过短")):
        return VideoDecryptError("corrupted_file", "密文文件不完整或已经损坏")
    if "找不到待解密视频" in message:
        return VideoDecryptError("input_missing", "待解密视频文件不存在")
    if "密码不能为空" in message:
        return VideoDecryptError("empty_password", "请输入加密密码")
    if "MP4 播放索引整理失败" in message or "不包含可用视频数据" in message:
        return VideoDecryptError("remux_failed", "视频已解密，但 MP4 播放索引整理失败")
    return VideoDecryptError("decrypt_failed", message)


class VideoDecryptAdapter:
    def __init__(
        self,
        upstream_root: str | os.PathLike[str] | None = None,
        config_path: Path = CONFIG_PATH,
    ) -> None:
        self.upstream_root = upstream_root
        self.config_path = config_path

    def _root(self) -> Path:
        return resolve_upstream_root(self.upstream_root, self.config_path)

    def inspect_runtime(self) -> VideoDecryptRuntimeInfo:
        try:
            root = self._root()
            module = load_upstream_module(root)
            import av
            import cryptography
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

            if getattr(module, "FILE_EXTENSION", "") != ".evideo":
                raise VideoDecryptError(
                    "runtime_unavailable",
                    "上游视频解密工具版本过旧，需要支持 .evideo 的 2.0 或更高版本",
                )
            del Cipher, algorithms, modes, Scrypt
            return VideoDecryptRuntimeInfo(
                available=True,
                upstream_root=str(root),
                upstream_version=read_upstream_version(root),
                algorithm="AES-256-GCM / Scrypt",
                av_version=str(av.__version__),
                cryptography_version=str(cryptography.__version__),
                file_extension=str(module.FILE_EXTENSION),
                message="视频解密运行环境可用",
            )
        except (ImportError, VideoDecryptError) as exc:
            message = str(exc)
            if isinstance(exc, ImportError):
                message = "缺少 PyAV 或 cryptography，请先安装 requirements.txt 中的依赖"
            return VideoDecryptRuntimeInfo(available=False, message=message)

    def decrypt(self, input_path: Path, output_path: Path, password: str) -> Path:
        if not password:
            raise VideoDecryptError("empty_password", "请输入加密密码")
        root = self._root()
        module = load_upstream_module(root)
        try:
            return Path(module.decrypt_video_file(input_path, output_path, password))
        except Exception as exc:
            raise map_upstream_error(exc) from exc
