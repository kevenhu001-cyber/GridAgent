"""Generate deterministic, simple package logos without external dependencies."""
import math
import struct
import sys
import zlib
from pathlib import Path


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def logo(size):
    nodes = ((0.25, 0.5), (0.5, 0.25), (0.75, 0.5), (0.5, 0.75))
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            u, v = (x + 0.5) / size, (y + 0.5) / size
            rounded = math.hypot(max(0.0, abs(u - 0.5) - 0.31), max(0.0, abs(v - 0.5) - 0.31))
            color = (22, 36, 54, 255) if rounded <= 0.15 else (0, 0, 0, 0)
            for i, (ax, ay) in enumerate(nodes):
                bx, by = nodes[(i + 1) % len(nodes)]
                dx, dy = bx - ax, by - ay
                t = max(0, min(1, ((u - ax) * dx + (v - ay) * dy) / (dx * dx + dy * dy)))
                if math.hypot(u - ax - t * dx, v - ay - t * dy) < 0.022:
                    color = (218, 235, 246, 255)
            if any(math.hypot(u - a, v - b) < 0.057 for a, b in nodes):
                color = (104, 207, 217, 255)
            row.extend(color)
        rows.append(row)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def main():
    folder = Path(sys.argv[1])
    folder.mkdir(parents=True, exist_ok=True)
    for filename, size in (("StoreLogo.png", 50), ("Square44x44Logo.png", 44), ("Square150x150Logo.png", 150)):
        (folder / filename).write_bytes(logo(size))


if __name__ == "__main__":
    main()
