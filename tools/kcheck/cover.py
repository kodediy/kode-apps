"""The cover the marketplace takes: the app's icon with no transparent pixel.

The marketplace refuses a cover with transparency (`cover_transparent`), and
an icon drawn as a disc leaves its corners clear. An 8-bit PNG with an alpha
channel (grey + alpha or RGBA, not interlaced) is laid on the app's colour and
written again as plain RGB; any other icon goes as it is. Standard library
only, like the rest of the tools.
"""
from __future__ import annotations

import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
DEPTH = 8                       # the one bit depth flattened
GREY_ALPHA = 4                  # PNG colour type: grey and alpha
RGBA = 6                        # PNG colour type: red, green, blue and alpha
RGB = 2                         # PNG colour type of the cover written
BYTES_PER_PIXEL = {GREY_ALPHA: 2, RGBA: 4}
OPAQUE = 255                    # the alpha of a pixel that hides what is under it
FILTER_NONE, FILTER_SUB, FILTER_UP, FILTER_AVERAGE, FILTER_PAETH = range(5)


def _chunks(png: bytes):
    """Every (type, data) chunk of png, in order."""
    pos = len(SIGNATURE)
    while pos + 8 <= len(png):
        size, kind = struct.unpack(">I4s", png[pos:pos + 8])
        yield kind, png[pos + 8:pos + 8 + size]
        pos += 12 + size


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _rows(raw: bytes, width: int, height: int, bpp: int):
    """The pixel rows of raw, each with its filter undone."""
    stride = width * bpp
    prev = bytearray(stride)
    pos = 0
    for _ in range(height):
        kind = raw[pos]
        row = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        for i in range(stride):
            left = row[i - bpp] if i >= bpp else 0
            up_left = prev[i - bpp] if i >= bpp else 0
            if kind == FILTER_SUB:
                row[i] = (row[i] + left) & 0xFF
            elif kind == FILTER_UP:
                row[i] = (row[i] + prev[i]) & 0xFF
            elif kind == FILTER_AVERAGE:
                row[i] = (row[i] + ((left + prev[i]) >> 1)) & 0xFF
            elif kind == FILTER_PAETH:
                row[i] = (row[i] + _paeth(left, prev[i], up_left)) & 0xFF
            elif kind != FILTER_NONE:
                raise ValueError(f"PNG row filter {kind} does not exist")
        yield row
        prev = row


def opaque(png: bytes, color: str) -> bytes:
    """png laid on color (#RRGGBB) when it has an alpha channel, else png unchanged."""
    if not png.startswith(SIGNATURE):
        return png
    chunks = list(_chunks(png))
    ihdr = next((data for kind, data in chunks if kind == b"IHDR"), b"")
    if len(ihdr) < 13:
        return png
    width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", ihdr[:13])
    if ctype not in BYTES_PER_PIXEL or depth != DEPTH or interlace != 0:
        return png
    bpp = BYTES_PER_PIXEL[ctype]
    ground = bytes.fromhex(color[1:])
    raw = zlib.decompress(b"".join(data for kind, data in chunks if kind == b"IDAT"))
    out = bytearray()
    for row in _rows(raw, width, height, bpp):
        out.append(FILTER_NONE)
        for x in range(0, len(row), bpp):
            if ctype == RGBA:
                pixel, alpha = row[x:x + 3], row[x + 3]
            else:
                pixel, alpha = bytes([row[x]]) * 3, row[x + 1]
            for ch in range(3):
                out.append((pixel[ch] * alpha + ground[ch] * (OPAQUE - alpha) + OPAQUE // 2) // OPAQUE)
    header = struct.pack(">IIBBBBB", width, height, DEPTH, RGB, 0, 0, 0)
    return (SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(bytes(out), 9))
            + _chunk(b"IEND", b""))
