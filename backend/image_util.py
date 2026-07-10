"""图像输入通道：将图片编码为内容块，打通多模态输入。

用法：
  from backend.image_util import image_block, encode_image

  # 获取单个内容块
  block = image_block("screenshot.png")

  # 构造多模态 user 消息
  msg = {"role": "user", "content": [
      {"type": "text", "text": "这张截图显示了什么？"},
      image_block("screenshot.png"),
  ]}

模型支持：DeepSeek 当前模型可能不支持视觉输入，用一个支持视觉的
OpenAI 兼容模型（如 gpt-4o）替换 base_url/model 即可验证通道。
本模块的价值在于「结构已经打通」——换模型只需改 env，不改代码。
"""
from __future__ import annotations
import base64
import io
import mimetypes
from pathlib import Path
from typing import Any


# 长边像素上限，超过则等比缩放（省 token、避免被拒）
MAX_LONG_SIDE = 1568


def _guess_media_type(path: str | Path) -> str:
    """根据文件扩展名猜测 MIME 类型，回退到 image/png。"""
    mt, _ = mimetypes.guess_type(str(path))
    if mt and mt.startswith("image/"):
        return mt
    return "image/png"


def _resize_image(data: bytes, media_type: str) -> bytes:
    """将图片缩放到长边 ≤ MAX_LONG_SIDE，返回同格式的字节。

    需要 Pillow；若未安装则原样返回（打印提示）。
    """
    try:
        from PIL import Image
    except ImportError:
        print("[提示] Pillow 未安装，跳过图片缩放。安装：pip install Pillow")
        return data

    try:
        img = Image.open(io.BytesIO(data))
    except Exception:
        return data  # 无法解码，原样返回

    w, h = img.size
    long_side = max(w, h)
    if long_side <= MAX_LONG_SIDE:
        return data

    ratio = MAX_LONG_SIDE / long_side
    new_size = (int(w * ratio), int(h * ratio))
    # 仅当缩小时才用高质量 LANCZOS
    img = img.resize(new_size, Image.LANCZOS if hasattr(Image, "LANCZOS") else Image.BICUBIC)

    # 确定输出格式
    fmt = None
    if "png" in media_type:
        fmt = "PNG"
    elif "jpeg" in media_type or "jpg" in media_type:
        fmt = "JPEG"
    elif "webp" in media_type:
        fmt = "WEBP"
    else:
        fmt = "PNG"

    buf = io.BytesIO()
    save_kwargs: dict[str, Any] = {"format": fmt}
    if fmt == "JPEG":
        save_kwargs["quality"] = 85
    img.save(buf, **save_kwargs)
    return buf.getvalue()


def image_block(path: str | Path, media_type: str | None = None) -> dict[str, Any]:
    """将图片文件编码为 Anthropic/OpenAI 兼容的内容块。

    参数：
      path: 图片文件路径
      media_type: MIME 类型（如 image/png），不传则从扩展名推断

    返回：
      {"type": "image", "source": {"type": "base64", "media_type": "...", "data": "..."}}
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"图片文件不存在：{path}")

    if media_type is None:
        media_type = _guess_media_type(str(path))

    raw = path.read_bytes()
    resized = _resize_image(raw, media_type)
    b64 = base64.b64encode(resized).decode("ascii")

    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": b64,
        },
    }


def encode_image(path: str | Path, media_type: str | None = None) -> str:
    """便捷函数：只返回 base64 字符串（不含外层结构）。

    用于需要直接拼 data URL 的场景。
    """
    block = image_block(path, media_type)
    return block["source"]["data"]
