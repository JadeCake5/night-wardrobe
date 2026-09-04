"""内置视频解密核心。

本文件源自 comfyui-encrypt-video 2.0.3 的解密路径（video_crypto.py）。
上游版权人已授权将解密代码以 MIT 许可证直接内置于 tag_manager。
本文件是 tag_manager 侧解密实现的事实来源；适配层只做运行环境检查与错误映射。
"""

from __future__ import annotations

import base64
import json
import os
import struct
from pathlib import Path
from typing import Any, BinaryIO, Callable, Mapping


CORE_VERSION = "2.0.3"
FILE_MAGIC = b"CEVIDEO\x00"
FILE_VERSION = 1
FILE_EXTENSION = ".evideo"
TAG_SIZE = 16
MAX_HEADER_SIZE = 64 * 1024
IO_CHUNK_SIZE = 1024 * 1024
SCRYPT_N = 1 << 15
SCRYPT_R = 8
SCRYPT_P = 1
_PREAMBLE = struct.Struct(">8sBI")
ProgressCallback = Callable[[float, str], None]


class VideoEncryptionError(RuntimeError):
    """表示视频压缩、加密或解密过程无法完成。"""


def _require_av():
    try:
        import av
    except ImportError as error:
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            "缺少 PyAV。请在 ComfyUI 的 Python 环境中执行：pip install -r requirements.txt"
        ) from error
    return av


def _require_cryptography():
    try:
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    except ImportError as error:
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            "缺少 cryptography。请在 ComfyUI 的 Python 环境中执行：pip install -r requirements.txt"
        ) from error
    return Cipher, algorithms, modes, Scrypt, InvalidTag


def _derive_key(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    if not password:
        raise ValueError("密码不能为空")  # 文案被 map_upstream_error 匹配，改动需同步
    _, _, _, scrypt_class, _ = _require_cryptography()
    try:
        return scrypt_class(salt=salt, length=32, n=n, r=r, p=p).derive(
            password.encode("utf-8")
        )
    except Exception as error:
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            f"无法从密码派生加密密钥：{error}"
        ) from error


def _decode_base64_field(header: Mapping[str, Any], name: str, length: int) -> bytes:
    value = header.get(name)
    if not isinstance(value, str):
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            f"密文文件头缺少有效字段：{name}"
        )
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as error:
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            f"密文文件头字段损坏：{name}"
        ) from error
    if len(decoded) != length:
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            f"密文文件头字段长度错误：{name}"
        )
    return decoded


def _validate_header(header: Mapping[str, Any]) -> tuple[bytes, bytes, int, int, int]:
    if header.get("cipher") != "AES-256-GCM":
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            "不支持该密文文件的加密算法"
        )
    if header.get("kdf") != "scrypt":
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            "不支持该密文文件的密钥派生算法"
        )
    if header.get("content_type") != "video/mp4":
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            "密文负载不是受支持的 MP4 视频"
        )

    try:
        n = int(header["n"])
        r = int(header["r"])
        p = int(header["p"])
    except (KeyError, TypeError, ValueError) as error:
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            "密文文件头的 Scrypt 参数无效"
        ) from error
    if (n, r, p) != (SCRYPT_N, SCRYPT_R, SCRYPT_P):
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            "密文文件使用了不受支持的 Scrypt 参数"
        )

    salt = _decode_base64_field(header, "salt", 16)
    nonce = _decode_base64_field(header, "nonce", 12)
    return salt, nonce, n, r, p


def _read_encrypted_header(
    source: BinaryIO,
) -> tuple[bytes, bytes, bytes, bytes, int, int, int, int]:
    preamble = source.read(_PREAMBLE.size)
    if len(preamble) != _PREAMBLE.size:
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            "输入文件过短，不是完整的加密视频"
        )
    magic, version, header_size = _PREAMBLE.unpack(preamble)
    if magic != FILE_MAGIC:
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            "输入文件不是本插件生成的 .evideo 密文"
        )
    if version != FILE_VERSION:
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            "输入文件的密文协议版本不受支持"
        )
    if header_size <= 0 or header_size > MAX_HEADER_SIZE:
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            "密文文件头长度无效"
        )

    header_bytes = source.read(header_size)
    if len(header_bytes) != header_size:
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            "密文文件头不完整"
        )
    try:
        header = json.loads(header_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            "密文文件头损坏"
        ) from error
    if not isinstance(header, Mapping):
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            "密文文件头结构无效"
        )
    salt, nonce, n, r, p = _validate_header(header)
    return preamble, header_bytes, salt, nonce, n, r, p, source.tell()


def _emit_progress(
    callback: ProgressCallback | None,
    value: float,
    message: str,
) -> None:
    if callback is None:
        return
    try:
        callback(max(0.0, min(1.0, float(value))), message)
    except Exception:
        # 进度显示失败不能破坏已经完成的媒体与密文处理。
        pass


def _remux_standard_mp4(
    source_path: Path,
    output_path: Path,
    progress_callback: ProgressCallback | None,
) -> None:
    """不重新编码媒体包，只重建普通 MP4 的 moov 索引。"""

    av = _require_av()
    source_container = None
    output_container = None
    try:
        source_container = av.open(str(source_path), mode="r")
        if not source_container.streams.video:
            raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
                "解密后的 MP4 不包含视频轨道"
            )

        selected_streams = [
            stream
            for stream in source_container.streams
            if stream.type in {"video", "audio"}
        ]
        output_container = av.open(
            str(output_path),
            mode="w",
            format="mp4",
            options={"movflags": "+faststart"},
        )
        stream_map = {
            stream.index: output_container.add_stream_from_template(stream)
            for stream in selected_streams
        }

        total_duration = (
            float(source_container.duration) / 1_000_000
            if source_container.duration
            else 0.0
        )
        maximum_position = 0.0
        video_packets = 0
        last_percent = -1
        for packet in source_container.demux(selected_streams):
            if packet.dts is None:
                continue
            source_stream = packet.stream
            if source_stream.type == "video":
                video_packets += 1
            if total_duration > 0 and packet.time_base is not None:
                maximum_position = max(
                    maximum_position,
                    float(packet.dts * packet.time_base),
                )
                percent = min(99, int(maximum_position / total_duration * 100))
                if percent != last_percent:
                    _emit_progress(
                        progress_callback,
                        0.90 + percent / 1000,
                        "正在整理 MP4 播放索引",
                    )
                    last_percent = percent
            packet.stream = stream_map[source_stream.index]
            output_container.mux(packet)

        if video_packets <= 0:
            raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
                "解密后的 MP4 不包含可用视频数据"
            )
        output_container.close()
        output_container = None
        source_container.close()
        source_container = None
    except VideoEncryptionError:
        raise
    except Exception as error:
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            f"MP4 播放索引整理失败：{error}"
        ) from error
    finally:
        if output_container is not None:
            try:
                output_container.close()
            except Exception:
                pass
        if source_container is not None:
            source_container.close()


def decrypt_video_file(
    input_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    password: str,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """验证并解密 `.evideo`，再无损整理为带完整索引的标准 MP4。"""

    if not password:
        raise ValueError("密码不能为空")  # 文案被 map_upstream_error 匹配，改动需同步
    source_path = Path(input_path)
    final_path = Path(output_path)
    if not source_path.is_file():
        raise FileNotFoundError(  # 文案被 map_upstream_error 匹配，改动需同步
            f"找不到待解密视频：{source_path}"
        )
    if source_path.suffix.lower() != FILE_EXTENSION:
        raise ValueError(  # 文案被 map_upstream_error 匹配，改动需同步
            f"待解密文件必须使用 {FILE_EXTENSION} 扩展名"
        )
    if final_path.suffix.lower() != ".mp4":
        raise ValueError(  # 文案被 map_upstream_error 匹配，改动需同步
            "解密输出视频必须使用 .mp4 扩展名"
        )

    final_path.parent.mkdir(parents=True, exist_ok=True)
    fragmented_path = final_path.with_name(f"{final_path.name}.fragmented.partial")
    partial_path = final_path.with_name(f"{final_path.name}.partial")
    cipher_class, algorithms, modes, _, invalid_tag = _require_cryptography()

    try:
        _emit_progress(progress_callback, 0.0, "正在验证加密文件")
        with source_path.open("rb") as source:
            preamble, header, salt, nonce, n, r, p, payload_offset = (
                _read_encrypted_header(source)
            )
            source.seek(0, os.SEEK_END)
            file_size = source.tell()
            ciphertext_size = file_size - payload_offset - TAG_SIZE
            if ciphertext_size <= 0:
                raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
                    "密文文件不包含完整的视频负载"
                )
            source.seek(file_size - TAG_SIZE)
            tag = source.read(TAG_SIZE)
            source.seek(payload_offset)

            key = _derive_key(password, salt, n, r, p)
            decryptor = cipher_class(
                algorithms.AES(key),
                modes.GCM(nonce, tag),
            ).decryptor()
            decryptor.authenticate_additional_data(preamble + header)

            remaining = ciphertext_size
            processed = 0
            last_percent = -1
            with fragmented_path.open("wb") as target:
                while remaining:
                    chunk = source.read(min(IO_CHUNK_SIZE, remaining))
                    if not chunk:
                        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
                            "密文视频负载被意外截断"
                        )
                    target.write(decryptor.update(chunk))
                    remaining -= len(chunk)
                    processed += len(chunk)
                    percent = int(processed / ciphertext_size * 100)
                    if percent != last_percent:
                        _emit_progress(
                            progress_callback,
                            percent / 100 * 0.90,
                            "正在解密视频数据",
                        )
                        last_percent = percent
                target.write(decryptor.finalize())
                target.flush()
                os.fsync(target.fileno())
        _emit_progress(progress_callback, 0.90, "密文验证通过，正在整理 MP4 索引")
        _remux_standard_mp4(fragmented_path, partial_path, progress_callback)
        os.replace(partial_path, final_path)
        _emit_progress(progress_callback, 1.0, "解密完成，MP4 播放索引已生成")
        return final_path
    except invalid_tag as error:
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            "密码错误或密文文件已经损坏"
        ) from error
    except (ValueError, FileNotFoundError, VideoEncryptionError):
        raise
    except Exception as error:
        raise VideoEncryptionError(  # 文案被 map_upstream_error 匹配，改动需同步
            f"解密视频失败：{error}"
        ) from error
    finally:
        if fragmented_path.exists():
            fragmented_path.unlink()
        if partial_path.exists():
            partial_path.unlink()
