"""kcheck.cover: an icon with an alpha channel laid on the app's colour, any other sent as it is.

    tools/run_tests.sh
"""
import struct
import unittest
import zlib

from tests.helpers import png_bytes

from kcheck import cover


def rgb_rows(png):
    """The colour type and the pixel rows of a cover opaque() wrote, every row unfiltered."""
    pos, idat = 8, b""
    while pos < len(png):
        size, kind = struct.unpack(">I4s", png[pos:pos + 8])
        data = png[pos + 8:pos + 8 + size]
        if kind == b"IHDR":
            width, ctype = struct.unpack(">I", data[:4])[0], data[9]
        elif kind == b"IDAT":
            idat += data
        pos += 12 + size
    raw = zlib.decompress(idat)
    stride = 1 + width * 3
    rows = [raw[i:i + stride] for i in range(0, len(raw), stride)]
    if any(row[0] != 0 for row in rows):
        raise AssertionError("a cover row is filtered")
    return ctype, [bytes(row[1:]) for row in rows]


class CoverTest(unittest.TestCase):
    def test_clear_pixel_takes_the_colour(self):
        png = png_bytes(6, [bytes([255, 0, 0, 255, 0, 0, 0, 0])])
        self.assertEqual(rgb_rows(cover.opaque(png, "#191919")), (2, [bytes([255, 0, 0, 25, 25, 25])]))

    def test_half_alpha_blends(self):
        png = png_bytes(6, [bytes([255, 255, 255, 128])])
        self.assertEqual(rgb_rows(cover.opaque(png, "#000000"))[1], [bytes([128, 128, 128])])

    def test_every_filter_is_undone(self):
        rows = [bytes(((x * 37 + y * 91 + c * 13) & 0xFF) if c < 3 else 255 for x in range(3) for c in range(4))
                for y in range(5)]
        got = rgb_rows(cover.opaque(png_bytes(6, rows, [0, 1, 2, 3, 4]), "#000000"))[1]
        self.assertEqual(got, [bytes(v for i, v in enumerate(row) if i % 4 != 3) for row in rows])

    def test_grey_and_alpha(self):
        png = png_bytes(4, [bytes([200, 255, 0, 0])])
        self.assertEqual(rgb_rows(cover.opaque(png, "#102030"))[1], [bytes([200, 200, 200, 16, 32, 48])])

    def test_rgb_goes_as_it_is(self):
        png = png_bytes(2, [bytes([1, 2, 3])])
        self.assertEqual(cover.opaque(png, "#191919"), png)

    def test_jpeg_goes_as_it_is(self):
        jpeg = b"\xff\xd8\xff\xe0" + bytes(16)
        self.assertEqual(cover.opaque(jpeg, "#191919"), jpeg)


if __name__ == "__main__":
    unittest.main()
