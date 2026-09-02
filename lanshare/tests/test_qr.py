"""QRエンコーダの検証。

生成した行列を逆向きに読み戻し、
* 機能パターン(位置検出・タイミング・位置合わせ)の配置
* 形式情報のBCH符号
* データ+誤り訂正コードワードのRSシンドロームが0であること
* 復元した本文が入力と一致すること
を確認する。
"""

import unittest

from lanshare import qr


def _unmask_bits(code: qr.QRCode) -> list[int]:
    size = code.size
    base = qr._new_matrix(size)
    reserved = qr._new_matrix(size)
    qr._place_function_patterns(base, reserved, code.version)

    bits: list[int] = []
    upward = True
    col = size - 1
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if reserved[row][c]:
                    continue
                value = code.matrix[row][c]
                if qr._mask_condition(code.mask, row, c):
                    value ^= 1
                bits.append(value)
        upward = not upward
        col -= 2
    return bits


def _codewords(code: qr.QRCode) -> list[int]:
    bits = _unmask_bits(code)
    total = _TOTAL[code.version - 1]
    return [int("".join(str(b) for b in bits[i * 8:i * 8 + 8]), 2) for i in range(total)]


_TOTAL = [26, 44, 70, 100, 134, 172, 196, 242, 292, 346]


def _deinterleave(code: qr.QRCode) -> list[tuple[list[int], list[int]]]:
    """インターリーブを解いて (データ, EC) のブロック列に戻す。"""
    stream = _codewords(code)
    ec_count, layout = qr._EC_BLOCKS[(code.ec_level, code.version)]
    sizes = [size for count, size in layout for _ in range(count)]
    data_blocks: list[list[int]] = [[] for _ in sizes]
    index = 0
    for position in range(max(sizes)):
        for block, size in enumerate(sizes):
            if position < size:
                data_blocks[block].append(stream[index])
                index += 1
    ec_blocks: list[list[int]] = [[] for _ in sizes]
    for position in range(ec_count):
        for block in range(len(sizes)):
            ec_blocks[block].append(stream[index])
            index += 1
    return list(zip(data_blocks, ec_blocks))


def _syndromes_zero(data: list[int], ec: list[int]) -> bool:
    codeword = data + ec
    for i in range(len(ec)):
        acc = 0
        for byte in codeword:
            acc = qr._gf_mul(acc, qr._EXP[i]) ^ byte
        if acc:
            return False
    return True


def _decode_payload(code: qr.QRCode) -> bytes:
    blocks = _deinterleave(code)
    data = [byte for block, _ in blocks for byte in block]
    bits = "".join(f"{byte:08b}" for byte in data)
    mode = int(bits[:4], 2)
    assert mode == 0b0100, "バイトモードではありません"
    count_bits = 8 if code.version < 10 else 16
    length = int(bits[4:4 + count_bits], 2)
    start = 4 + count_bits
    payload = bits[start:start + length * 8]
    return bytes(int(payload[i:i + 8], 2) for i in range(0, len(payload), 8))


class QRStructureTest(unittest.TestCase):
    def test_finder_and_timing_patterns(self):
        code = qr.make("https://example.local:8765/", "M")
        size = code.size
        for base_r, base_c in ((0, 0), (0, size - 7), (size - 7, 0)):
            self.assertEqual(code.matrix[base_r][base_c], 1)
            self.assertEqual(code.matrix[base_r + 1][base_c + 1], 0)
            self.assertEqual(code.matrix[base_r + 3][base_c + 3], 1)
        for i in range(8, size - 8):
            self.assertEqual(code.matrix[6][i], 1 if i % 2 == 0 else 0)
            self.assertEqual(code.matrix[i][6], 1 if i % 2 == 0 else 0)

    def test_alignment_pattern_on_timing_row(self):
        """バージョン7以上ではタイミングパターン上にも位置合わせパターンが必要。"""
        code = qr.make("x" * 130, "M")  # バージョン7以上になる長さ
        self.assertGreaterEqual(code.version, 7)
        centers = qr._ALIGN_CENTERS[code.version]
        r_center, c_center = 6, centers[1]
        self.assertEqual(code.matrix[r_center][c_center], 1)  # 中心
        self.assertEqual(code.matrix[r_center][c_center + 1], 0)  # 白リング
        self.assertEqual(code.matrix[r_center][c_center + 2], 1)  # 外周
        self.assertEqual(code.matrix[r_center - 2][c_center - 2], 1)

    def test_format_information_is_valid_bch(self):
        code = qr.make("test", "L")
        size = code.size
        read = 0
        for i in range(15):
            if i < 6:
                bit = code.matrix[i][8]
            elif i == 6:
                bit = code.matrix[7][8]
            elif i == 7:
                bit = code.matrix[8][8]
            elif i == 8:
                bit = code.matrix[8][7]
            else:
                bit = code.matrix[8][14 - i]
            read |= bit << i
        self.assertEqual(read, qr._format_bits(code.ec_level, code.mask))
        unmasked = read ^ 0b101010000010010
        self.assertEqual(qr._bch(unmasked, 0b10100110111, 11), 0)


class QRRoundTripTest(unittest.TestCase):
    def test_round_trip_across_versions(self):
        for level in ("L", "M"):
            for length in (1, 10, 44, 80, 120, 180, 200):
                with self.subTest(level=level, length=length):
                    text = "https://example.local/" + "a" * max(0, length - 22)
                    text = text[:length] if length >= 22 else "a" * length
                    try:
                        code = qr.make(text, level)
                    except qr.QRError:
                        continue
                    for data, ec in _deinterleave(code):
                        self.assertTrue(_syndromes_zero(data, ec), "RSシンドロームが0でない")
                    self.assertEqual(_decode_payload(code).decode(), text)

    def test_utf8_payload(self):
        text = "http://192.168.0.10:8765/?pin=012345"
        code = qr.make(text, "M")
        self.assertEqual(_decode_payload(code).decode(), text)

    def test_version_selection(self):
        self.assertEqual(qr.make("a", "M").version, 1)
        self.assertEqual(qr.make("a" * 40, "M").version, 3)

    def test_too_long(self):
        with self.assertRaises(qr.QRError):
            qr.make("a" * 300, "M")

    def test_unsupported_level(self):
        with self.assertRaises(qr.QRError):
            qr.make("a", "H")


class QROutputTest(unittest.TestCase):
    def test_png_header_and_size(self):
        code = qr.make("http://192.168.0.2:8765/", "M")
        png = code.to_png(scale=4, border=2)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        width = int.from_bytes(png[16:20], "big")
        self.assertEqual(width, (code.size + 4) * 4)

    def test_ascii_dimensions(self):
        code = qr.make("abc", "M")
        lines = code.to_ascii(border=2).splitlines()
        self.assertEqual(len(lines[0]), code.size + 4)


if __name__ == "__main__":
    unittest.main()
