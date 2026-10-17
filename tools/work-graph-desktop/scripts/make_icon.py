"""앱 아이콘 생성기 (HARN-208) — 표준 라이브러리만으로 assets/icon.ico·icon.png를 만든다.

어두운 둥근 사각형 위에 작업 그래프(청록 노드 → 가운데 노드 → 호박색 사람 게이트·회색 대기)를
그린다.
각 크기를 직접 그리고(작은 크기에서 선이 사라지지 않게 최소 두께를 둔다) 4×4 초표본으로 가장자리를
부드럽게 한다. ICO는 크기별 PNG를 담는 형식(Windows Vista 이후 지원)이다.

실행: python3 scripts/make_icon.py   (작업 디렉터리 = tools/work-graph-desktop)
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
PNG_SIZE = 512
SS = 4  # 한 픽셀을 SS×SS 표본으로 나눠 평균낸다

BG_TOP = (0x13, 0x1B, 0x25)
BG_BOTTOM = (0x0B, 0x10, 0x16)
EDGE = (0x2D, 0xD4, 0xBF)
TEAL = (0x14, 0xB8, 0xA6)
TEAL_HI = (0x5E, 0xEA, 0xD4)
AMBER = (0xF5, 0x9E, 0x0B)
SLATE = (0x64, 0x74, 0x8B)

# 정규화 좌표(0~1)의 노드와 방향 간선
NODES = {
    "a": ((0.28, 0.29), TEAL),
    "b": ((0.72, 0.29), TEAL),
    "c": ((0.50, 0.54), TEAL_HI),
    "d": ((0.29, 0.77), AMBER),
    "e": ((0.71, 0.77), SLATE),
}
EDGES = (("a", "c"), ("b", "c"), ("c", "d"), ("c", "e"))
CORNER = 0.22
NODE_R = 0.095
RING = 0.028  # 노드 둘레의 배경색 테 — 간선이 노드 밑으로 들어가 보이게
LINE_W = 0.05


def _seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _in_rounded_square(x: float, y: float, r: float) -> bool:
    qx = max(abs(x - 0.5) - (0.5 - r), 0.0)
    qy = max(abs(y - 0.5) - (0.5 - r), 0.0)
    return qx * qx + qy * qy <= r * r


def _sample(x: float, y: float, line_w: float, ring: float) -> tuple[float, float, float, float]:
    """정규화 좌표 한 점의 색(RGBA, 0~255 실수)."""
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0) or not _in_rounded_square(x, y, CORNER):
        return (0.0, 0.0, 0.0, 0.0)
    color = tuple(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * y for i in range(3))
    for a, b in EDGES:
        (ax, ay), _ = NODES[a]
        (bx, by), _ = NODES[b]
        if _seg_dist(x, y, ax, ay, bx, by) <= line_w / 2:
            color = EDGE
    for (nx, ny), fill in NODES.values():
        d = math.hypot(x - nx, y - ny)
        if d <= NODE_R:
            color = fill
        elif d <= NODE_R + ring:
            color = tuple(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * y for i in range(3))
    return (float(color[0]), float(color[1]), float(color[2]), 255.0)


def render(size: int) -> bytes:
    """size×size RGBA 바이트(행 우선)."""
    # 작은 크기에서 선·테가 한 픽셀 밑으로 사라지지 않게 픽셀 단위 최소 두께를 둔다
    line_w = max(LINE_W, 1.6 / size)
    ring = max(RING, 0.9 / size)
    out = bytearray()
    n = SS * SS
    for py in range(size):
        for px in range(size):
            acc = [0.0, 0.0, 0.0, 0.0]
            for sy in range(SS):
                for sx in range(SS):
                    x = (px + (sx + 0.5) / SS) / size
                    y = (py + (sy + 0.5) / SS) / size
                    r, g, b, a = _sample(x, y, line_w, ring)
                    acc[0] += r * a
                    acc[1] += g * a
                    acc[2] += b * a
                    acc[3] += a
            alpha = acc[3] / n
            if acc[3] > 0:
                out += bytes(round(acc[i] / acc[3]) for i in range(3))
            else:
                out += b"\x00\x00\x00"
            out.append(round(alpha))
    return bytes(out)


def png_bytes(size: int, rgba: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    stride = size * 4
    raw = b"".join(b"\x00" + rgba[y * stride : (y + 1) * stride] for y in range(size))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    idat = zlib.compress(raw, 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def ico_bytes(images: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        dim = 0 if size >= 256 else size  # ICO 규약: 256은 0으로 적는다
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return header + entries + blobs


def main() -> None:
    OUT.mkdir(exist_ok=True)
    images = [(s, png_bytes(s, render(s))) for s in ICO_SIZES]
    (OUT / "icon.ico").write_bytes(ico_bytes(images))
    (OUT / "icon.png").write_bytes(png_bytes(PNG_SIZE, render(PNG_SIZE)))
    print(f"icon.ico {len(images)}개 크기 · icon.png {PNG_SIZE}px → {OUT}")


if __name__ == "__main__":
    main()
