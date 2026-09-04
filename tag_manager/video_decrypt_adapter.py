from __future__ import annotations

import errno
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import video_crypto


ProgressCallback = Callable[[float, str], None]


@dataclass(frozen=True)
class VideoDecryptRuntimeInfo:
    available: bool
    core_version: str = ""
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


def map_upstream_error(error: Exception) -> VideoDecryptError:
    """把解密核心异常映射为稳定错误码。函数名 map_upstream_error 是对外契约，不得改名。"""

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
    def __init__(self) -> None:
        pass

    def inspect_runtime(self) -> VideoDecryptRuntimeInfo:
        try:
            import av
            import cryptography
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

            _ = (Cipher, algorithms, modes, Scrypt)
            if video_crypto.FILE_EXTENSION != ".evideo":
                return VideoDecryptRuntimeInfo(
                    available=False,
                    message="内置视频解密核心扩展名异常，需要 .evideo",
                )
            return VideoDecryptRuntimeInfo(
                available=True,
                core_version=video_crypto.CORE_VERSION,
                algorithm="AES-256-GCM / Scrypt",
                av_version=str(av.__version__),
                cryptography_version=str(cryptography.__version__),
                file_extension=".evideo",
                message="视频解密运行环境可用",
            )
        except ImportError:
            return VideoDecryptRuntimeInfo(
                available=False,
                message="缺少 PyAV 或 cryptography，请先安装 requirements.txt 中的依赖",
            )

    def decrypt(
        self,
        input_path: Path,
        output_path: Path,
        password: str,
        progress_callback: ProgressCallback | None = None,
    ) -> Path:
        if not password:
            raise VideoDecryptError("empty_password", "请输入加密密码")
        try:
            return Path(
                video_crypto.decrypt_video_file(
                    input_path,
                    output_path,
                    password,
                    progress_callback=progress_callback,
                )
            )
        except Exception as exc:
            raise map_upstream_error(exc) from exc
