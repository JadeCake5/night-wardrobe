from __future__ import annotations

import io
import json
import struct
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tag_manager import gallery


def build_exif_with_user_comment(comment_text: str) -> bytes:
    comment = b"ASCII\x00\x00\x00" + comment_text.encode("utf-8")
    ifd0_off = 8
    exif_ifd_off = ifd0_off + 18
    data_off = exif_ifd_off + 18
    buf = io.BytesIO()
    buf.write(b"II*\x00" + struct.pack("<I", ifd0_off))
    buf.write(struct.pack("<H", 1))
    buf.write(struct.pack("<HHI", gallery.EXIF_IFD_TAG, 4, 1) + struct.pack("<I", exif_ifd_off))
    buf.write(struct.pack("<I", 0))
    buf.write(struct.pack("<H", 1))
    buf.write(struct.pack("<HHI", gallery.USER_COMMENT_TAG, 7, len(comment)) + struct.pack("<I", data_off))
    buf.write(struct.pack("<I", 0))
    buf.write(comment)
    return b"Exif\x00\x00" + buf.getvalue()


EFFICIENT_LOADER_PROMPT = {
    "1": {
        "inputs": {
            "ckpt_name": "waiIllustriousSDXL_v160.safetensors",
            "positive": "masterpiece, 1girl, solo, standing",
            "negative": "worst quality, bad anatomy",
        },
        "class_type": "Efficient Loader",
    },
    "2": {
        "inputs": {
            "seed": 42,
            "positive": ["1", 1],
            "negative": ["1", 2],
            "model": ["1", 0],
        },
        "class_type": "KSampler (Efficient)",
    },
}

CONTROLNET_CHAIN_PROMPT = {
    "1": {
        "inputs": {
            "ckpt_name": "waiIllustriousSDXL_v160.safetensors",
            "positive": "babydoll, white dress, 1girl",
            "negative": "outline, text, low quality",
        },
        "class_type": "Efficient Loader",
    },
    "5": {
        "inputs": {
            "positive": ["1", 1],
            "negative": ["1", 2],
            "control_net": ["2", 0],
        },
        "class_type": "ControlNetApplyAdvanced",
    },
    "6": {
        "inputs": {
            "seed": 7,
            "positive": ["5", 0],
            "negative": ["5", 1],
            "model": ["1", 0],
        },
        "class_type": "KSampler (Efficient)",
    },
}

CLIP_TEXT_ENCODE_PROMPT = {
    "3": {
        "inputs": {"text": "sunny day, 1boy", "clip": ["4", 0]},
        "class_type": "CLIPTextEncode",
    },
    "5": {
        "inputs": {"text": "blurry, lowres", "clip": ["4", 0]},
        "class_type": "CLIPTextEncode",
    },
    "6": {
        "inputs": {"positive": ["3", 0], "negative": ["5", 0]},
        "class_type": "KSampler",
    },
}


class ExtractPromptsComfyUIVariantsTests(unittest.TestCase):
    def test_efficient_loader节点直接存positive_negative字符串(self) -> None:
        meta = {"prompt": json.dumps(EFFICIENT_LOADER_PROMPT)}
        positive, negative = gallery.extract_prompts(meta)[:2]

        self.assertEqual("masterpiece, 1girl, solo, standing", positive)
        self.assertEqual("worst quality, bad anatomy", negative)

    def test_经controlnet传递节点回溯到efficient_loader(self) -> None:
        meta = {"prompt": json.dumps(CONTROLNET_CHAIN_PROMPT)}
        positive, negative = gallery.extract_prompts(meta)[:2]

        self.assertEqual("babydoll, white dress, 1girl", positive)
        self.assertEqual("outline, text, low quality", negative)

    def test_标准clip_text_encode工作流保持原有行为(self) -> None:
        meta = {"prompt": json.dumps(CLIP_TEXT_ENCODE_PROMPT)}
        positive, negative = gallery.extract_prompts(meta)[:2]

        self.assertEqual("sunny day, 1boy", positive)
        self.assertEqual("blurry, lowres", negative)

    def test_text链接优先于同名positive输入(self) -> None:
        prompt = {
            "1": {
                "inputs": {"text": ["2", 0], "positive": "不应取这个"},
                "class_type": "Reroute",
            },
            "2": {
                "inputs": {"text": "链接回溯的提示词"},
                "class_type": "CLIPTextEncode",
            },
            "3": {
                "inputs": {"positive": ["1", 0]},
                "class_type": "KSampler",
            },
        }
        positive, negative = gallery.find_ksampler_connections(prompt)

        self.assertEqual("链接回溯的提示词", positive)
        self.assertEqual("", negative)


class ReadImageMetadataExifIfdTests(unittest.TestCase):
    def test_jpeg的usercomment藏在exif子ifd也能读出(self) -> None:
        comment_text = "1girl, solo\nNegative prompt: lowres, bad hands\nSteps: 28, Sampler: Euler a"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.jpg"
            img = Image.new("RGB", (8, 8), "white")
            img.save(path, "JPEG", exif=build_exif_with_user_comment(comment_text))

            meta = gallery.read_image_metadata(path)

        self.assertEqual(comment_text, meta.get("parameters"))
        self.assertEqual("EXIF UserComment", meta.get("_metadata_source"))
        self.assertNotIn(str(gallery.EXIF_IFD_TAG), meta)

        positive, negative = gallery.extract_prompts(meta)[:2]
        self.assertEqual("1girl, solo", positive)
        self.assertEqual("lowres, bad hands", negative)


if __name__ == "__main__":
    unittest.main()
