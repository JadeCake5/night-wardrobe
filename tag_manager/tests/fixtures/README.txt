sample.evideo — 测试固件

来源：由 comfyui-encrypt-video 上游 2.0.3 真实加密器一次性生成（2026-09-04）。
内容：3 帧 18x12 随机画面（h264/yuv420p）+ 8kHz 单声道 220Hz 正弦 AAC 音轨，24fps。
密码：正确密码
用途：验证 tag_manager 内置解密核心对上游加密产物的格式兼容性（错密码、篡改、非密文用例也基于本文件派生）。
重新生成：在上游仓库环境调用 video_crypto.encode_encrypted_video，参数见 tests/test_video_decrypt.py 中的固件断言。
