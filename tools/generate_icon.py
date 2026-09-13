"""生成程序图标 assets/app.ico（纯标准库，无第三方依赖）。

复用与主窗口相同的蓝底三柱状条设计，生成多尺寸 .ico，
供 PyInstaller 打包时作为 exe 图标与版本资源。

用法（在项目根目录执行）：
    python tools\\generate_icon.py
"""
import struct
import sys
import zlib
from pathlib import Path

# 允许从任意位置运行本脚本时都能导入项目包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from r_monitor import config  # noqa: E402

_ASSETS = Path(__file__).resolve().parents[1] / "assets"
_OUT = _ASSETS / "app.ico"

# 品牌色：单一来源 r_monitor.config.BRAND_COLOR，图标与托盘图标背景共用
_BG = tuple(int(config.BRAND_COLOR[i:i + 2], 16) for i in (1, 3, 5))  # "#1976d2" -> (25, 118, 210)
_WHITE = (255, 255, 255)
_SIZE = 64


def _bgra(img):
    """RGBA 像素 -> BGRA 字节串。"""
    out = bytearray()
    for r, g, b, a in img:
        out += bytes((b, g, r, a))
    return bytes(out)


def _render(size: int):
    """渲染 size×size 图标，返回 BGRA 像素字节。"""
    s = 64.0
    pixels = []
    for y in range(size):
        for x in range(size):
            fx, fy = x / size * s, y / size * s
            r = g = b = 0
            a = 0

            # 圆角矩形背景（半径 14）
            if _in_rounded_rect(fx, fy, 0, 0, s, s, 14):
                r, g, b = _BG
                a = 255

            # 三根白色柱（14,34/28,22/42,12，宽 8，高 16/28/38）
            for bx, by, bh in ((14, 34, 16), (28, 22, 28), (42, 12, 38)):
                if bx <= fx < bx + 8 and by <= fy < by + bh:
                    r, g, b = _WHITE
                    a = 255

            pixels.append((r, g, b, a))
    return _bgra(pixels)


def _in_rounded_rect(x, y, left, top, w, h, radius) -> bool:
    if not (left <= x < left + w and top <= y < top + h):
        return False
    cx = min(max(x, left + radius), left + w - radius)
    cy = min(max(y, top + radius), top + h - radius)
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= radius * radius


def _png(data: bytes, size: int) -> bytes:
    """把 BGRA 原始像素打包成 PNG（含 alpha）。"""

    def chunk(tag, payload):
        c = tag + payload
        return struct.pack(">I", len(payload)) + c + struct.pack(">I", zlib.crc32(c))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8bit RGBA
    raw = bytearray()
    stride = size * 4
    for y in range(size):
        raw.append(0)  # filter: none
        raw += data[y * stride:(y + 1) * stride]
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def main():
    sizes = (16, 32, 48, 64, 128, 256)
    _ASSETS.mkdir(parents=True, exist_ok=True)

    images = [_png(_render(s), s) for s in sizes]

    # ICO 头部
    header = struct.pack("<HHH", 0, 1, len(sizes))
    entries = b""
    offset = 6 + 16 * len(sizes)
    for s, img in zip(sizes, images, strict=True):
        # ICO 目录项的宽/高各占 1 字节，256 必须编码为 0
        b = s if s < 256 else 0
        entries += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(img), offset)
        offset += len(img)

    _OUT.write_bytes(header + entries + b"".join(images))
    print(f"已生成 {_OUT}（{len(sizes)} 个尺寸，品牌色 {_BG}）")
    print(f"应用版本：{config.APP_VERSION}")


if __name__ == "__main__":
    main()
