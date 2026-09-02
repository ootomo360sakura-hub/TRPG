"""QRコード生成(バイトモード、標準ライブラリのみ)。

iPhoneからサーバURLを開くためのQRを、外部パッケージなしで作るための最小実装。
対応範囲はバージョン1〜10・誤り訂正レベルL/Mのバイトモードで、URL程度の
短い文字列には十分。生成物はモジュール行列 / ASCII / PNGバイト列で取り出せる。
"""

from __future__ import annotations

import struct
import zlib

# 各バージョンの総コードワード数(バージョン1〜10)
_TOTAL_CODEWORDS = [26, 44, 70, 100, 134, 172, 196, 242, 292, 346]

# (バージョン, レベル) -> (ブロックあたりのECコードワード数, [(ブロック数, データCW数), ...])
_EC_BLOCKS = {
    ("L", 1): (7, [(1, 19)]),
    ("L", 2): (10, [(1, 34)]),
    ("L", 3): (15, [(1, 55)]),
    ("L", 4): (20, [(1, 80)]),
    ("L", 5): (26, [(1, 108)]),
    ("L", 6): (18, [(2, 68)]),
    ("L", 7): (20, [(2, 78)]),
    ("L", 8): (24, [(2, 97)]),
    ("L", 9): (30, [(2, 116)]),
    ("L", 10): (18, [(2, 68), (2, 69)]),
    ("M", 1): (10, [(1, 16)]),
    ("M", 2): (16, [(1, 28)]),
    ("M", 3): (26, [(1, 44)]),
    ("M", 4): (18, [(2, 32)]),
    ("M", 5): (24, [(2, 43)]),
    ("M", 6): (16, [(4, 27)]),
    ("M", 7): (18, [(4, 31)]),
    ("M", 8): (22, [(2, 38), (2, 39)]),
    ("M", 9): (22, [(3, 36), (2, 37)]),
    ("M", 10): (26, [(4, 43), (1, 44)]),
}

# 位置合わせパターンの中心座標(バージョン1〜10)
_ALIGN_CENTERS = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
    10: [6, 28, 50],
}

_EC_LEVEL_BITS = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}


class QRError(ValueError):
    """データが大きすぎるなど、QRを生成できない場合に送出する。"""


# --- GF(256) 演算 -----------------------------------------------------------

_EXP = [0] * 512
_LOG = [0] * 256


def _init_tables() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_tables()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree: int) -> list[int]:
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            nxt[j] ^= _gf_mul(coef, 1)
            nxt[j + 1] ^= _gf_mul(coef, _EXP[i])
        poly = nxt
    return poly


def _rs_encode(data: bytes, ec_count: int) -> list[int]:
    gen = _rs_generator(ec_count)
    rem = [0] * ec_count
    for byte in data:
        factor = byte ^ rem[0]
        rem = rem[1:] + [0]
        for i, coef in enumerate(gen[1:]):
            rem[i] ^= _gf_mul(coef, factor)
    return rem


# --- BCH(形式情報・型番情報) ------------------------------------------------


def _bch(value: int, poly: int, poly_bits: int) -> int:
    rest = value
    while rest.bit_length() >= poly_bits:
        rest ^= poly << (rest.bit_length() - poly_bits)
    return rest


def _format_bits(ec_level: str, mask: int) -> int:
    value = (_EC_LEVEL_BITS[ec_level] << 3) | mask
    bits = (value << 10) | _bch(value << 10, 0b10100110111, 11)
    return bits ^ 0b101010000010010


def _version_bits(version: int) -> int:
    return (version << 12) | _bch(version << 12, 0b1111100100101, 13)


# --- データ符号化 -----------------------------------------------------------


def _pick_version(length: int, ec_level: str) -> int:
    for version in range(1, 11):
        _, blocks = _EC_BLOCKS[(ec_level, version)]
        data_capacity = sum(count * size for count, size in blocks)
        count_bits = 8 if version < 10 else 16
        needed = (4 + count_bits + length * 8 + 7) // 8
        if needed <= data_capacity:
            return version
    raise QRError(f"データが大きすぎます({length}バイト、対応は最大バージョン10)")


def _encode_data(data: bytes, version: int, ec_level: str) -> list[int]:
    ec_count, blocks = _EC_BLOCKS[(ec_level, version)]
    data_capacity = sum(count * size for count, size in blocks)
    count_bits = 8 if version < 10 else 16

    bits: list[int] = []

    def push(value: int, width: int) -> None:
        for i in range(width - 1, -1, -1):
            bits.append((value >> i) & 1)

    push(0b0100, 4)  # バイトモード
    push(len(data), count_bits)
    for byte in data:
        push(byte, 8)

    capacity_bits = data_capacity * 8
    push(0, min(4, capacity_bits - len(bits)))
    while len(bits) % 8:
        bits.append(0)

    codewords = [int("".join(str(b) for b in bits[i:i + 8]), 2) for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)
    for i in range(data_capacity - len(codewords)):
        codewords.append(pad[i % 2])

    # ブロック分割 → RS符号化 → インターリーブ
    data_blocks: list[list[int]] = []
    ec_blocks: list[list[int]] = []
    pos = 0
    for count, size in blocks:
        for _ in range(count):
            chunk = codewords[pos:pos + size]
            pos += size
            data_blocks.append(chunk)
            ec_blocks.append(_rs_encode(bytes(chunk), ec_count))

    result: list[int] = []
    for i in range(max(len(b) for b in data_blocks)):
        for block in data_blocks:
            if i < len(block):
                result.append(block[i])
    for i in range(ec_count):
        for block in ec_blocks:
            result.append(block[i])
    return result


# --- 行列の構築 -------------------------------------------------------------


def _new_matrix(size: int) -> list[list[int]]:
    return [[0] * size for _ in range(size)]


def _place_function_patterns(matrix: list[list[int]], reserved: list[list[int]], version: int) -> None:
    size = len(matrix)

    def put(r: int, c: int, value: int) -> None:
        matrix[r][c] = value
        reserved[r][c] = 1

    # 位置検出パターン + 分離パターン
    for base_r, base_c in ((0, 0), (0, size - 7), (size - 7, 0)):
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = base_r + dr, base_c + dc
                if not (0 <= r < size and 0 <= c < size):
                    continue
                inner = 0 <= dr <= 6 and 0 <= dc <= 6
                if inner:
                    ring = max(abs(dr - 3), abs(dc - 3))
                    put(r, c, 1 if ring != 2 else 0)
                else:
                    put(r, c, 0)

    # タイミングパターン
    for i in range(8, size - 8):
        put(6, i, 1 if i % 2 == 0 else 0)
        put(i, 6, 1 if i % 2 == 0 else 0)

    # 位置合わせパターン(3つの位置検出パターンと重なる隅には置かない)
    centers = _ALIGN_CENTERS[version]
    skip = {(6, 6), (6, centers[-1]), (centers[-1], 6)} if centers else set()
    for r_center in centers:
        for c_center in centers:
            if (r_center, c_center) in skip:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    ring = max(abs(dr), abs(dc))
                    put(r_center + dr, c_center + dc, 1 if ring != 1 else 0)

    # 固定の暗モジュール
    put(size - 8, 8, 1)

    # 形式情報の領域を予約
    for i in range(9):
        if not reserved[8][i]:
            reserved[8][i] = 1
        if not reserved[i][8]:
            reserved[i][8] = 1
    for i in range(8):
        reserved[8][size - 1 - i] = 1
        reserved[size - 1 - i][8] = 1

    # 型番情報の領域を予約(バージョン7以上)
    if version >= 7:
        for i in range(6):
            for j in range(3):
                reserved[size - 11 + j][i] = 1
                reserved[i][size - 11 + j] = 1


def _place_data(matrix: list[list[int]], reserved: list[list[int]], codewords: list[int]) -> None:
    size = len(matrix)
    bits = []
    for cw in codewords:
        for i in range(7, -1, -1):
            bits.append((cw >> i) & 1)

    index = 0
    upward = True
    col = size - 1
    while col > 0:
        if col == 6:  # 縦のタイミングパターン列は飛ばす
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if reserved[row][c]:
                    continue
                matrix[row][c] = bits[index] if index < len(bits) else 0
                index += 1
        upward = not upward
        col -= 2


def _mask_condition(mask: int, r: int, c: int) -> bool:
    if mask == 0:
        return (r + c) % 2 == 0
    if mask == 1:
        return r % 2 == 0
    if mask == 2:
        return c % 3 == 0
    if mask == 3:
        return (r + c) % 3 == 0
    if mask == 4:
        return (r // 2 + c // 3) % 2 == 0
    if mask == 5:
        return (r * c) % 2 + (r * c) % 3 == 0
    if mask == 6:
        return ((r * c) % 2 + (r * c) % 3) % 2 == 0
    return ((r + c) % 2 + (r * c) % 3) % 2 == 0


def _apply_mask(matrix: list[list[int]], reserved: list[list[int]], mask: int) -> list[list[int]]:
    size = len(matrix)
    out = [row[:] for row in matrix]
    for r in range(size):
        for c in range(size):
            if not reserved[r][c] and _mask_condition(mask, r, c):
                out[r][c] ^= 1
    return out


def _place_format_info(matrix: list[list[int]], version: int, ec_level: str, mask: int) -> None:
    size = len(matrix)
    bits = _format_bits(ec_level, mask)
    for i in range(15):
        bit = (bits >> i) & 1
        if i < 6:
            matrix[i][8] = bit
        elif i == 6:
            matrix[7][8] = bit
        elif i == 7:
            matrix[8][8] = bit
        elif i == 8:
            matrix[8][7] = bit
        else:
            matrix[8][14 - i] = bit
        if i < 8:
            matrix[8][size - 1 - i] = bit
        else:
            matrix[size - 15 + i][8] = bit

    if version >= 7:
        vbits = _version_bits(version)
        for i in range(18):
            bit = (vbits >> i) & 1
            r, c = i // 3, i % 3
            matrix[size - 11 + c][r] = bit
            matrix[r][size - 11 + c] = bit


def _penalty(matrix: list[list[int]]) -> int:
    size = len(matrix)
    score = 0

    # 規則1: 同色5連以上
    for line in list(matrix) + [list(col) for col in zip(*matrix)]:
        run_value, run_len = line[0], 1
        for value in line[1:]:
            if value == run_value:
                run_len += 1
            else:
                if run_len >= 5:
                    score += 3 + (run_len - 5)
                run_value, run_len = value, 1
        if run_len >= 5:
            score += 3 + (run_len - 5)

    # 規則2: 2x2の同色ブロック
    for r in range(size - 1):
        for c in range(size - 1):
            block = matrix[r][c] + matrix[r][c + 1] + matrix[r + 1][c] + matrix[r + 1][c + 1]
            if block in (0, 4):
                score += 3

    # 規則3: 位置検出パターン類似
    pattern_a = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    pattern_b = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]
    for line in list(matrix) + [list(col) for col in zip(*matrix)]:
        for i in range(size - 10):
            window = line[i:i + 11]
            if window == pattern_a or window == pattern_b:
                score += 40

    # 規則4: 暗モジュールの比率
    dark = sum(sum(row) for row in matrix)
    ratio = dark * 100 // (size * size)
    score += 10 * (abs(ratio - 50) // 5)
    return score


class QRCode:
    """生成済みQRコード。``matrix[row][col]`` が1なら暗モジュール。"""

    def __init__(self, matrix: list[list[int]], version: int, ec_level: str, mask: int):
        self.matrix = matrix
        self.version = version
        self.ec_level = ec_level
        self.mask = mask

    @property
    def size(self) -> int:
        return len(self.matrix)

    def to_ascii(self, border: int = 2) -> str:
        """端末表示用に半角ブロック文字2つで1モジュールを描画する。"""
        size = self.size
        rows = [[0] * (size + border * 2) for _ in range(border)]
        for row in self.matrix:
            rows.append([0] * border + list(row) + [0] * border)
        rows.extend([[0] * (size + border * 2) for _ in range(border)])

        lines = []
        for i in range(0, len(rows), 2):
            top = rows[i]
            bottom = rows[i + 1] if i + 1 < len(rows) else [0] * len(top)
            line = []
            for t, b in zip(top, bottom):
                if t and b:
                    line.append("█")
                elif t:
                    line.append("▀")
                elif b:
                    line.append("▄")
                else:
                    line.append(" ")
            lines.append("".join(line))
        return "\n".join(lines)

    def to_png(self, scale: int = 6, border: int = 4) -> bytes:
        """1bitグレースケールのPNGバイト列を返す(依存なしで書き出す)。"""
        size = self.size
        width = (size + border * 2) * scale

        def row_pixels(matrix_row: list[int] | None) -> bytes:
            if matrix_row is None:
                return b"\xff" * width
            pixels = bytearray(b"\xff" * (border * scale))
            for value in matrix_row:
                pixels += bytes([0x00 if value else 0xFF]) * scale
            pixels += b"\xff" * (border * scale)
            return bytes(pixels)

        raw = bytearray()
        for _ in range(border * scale):
            raw += b"\x00" + row_pixels(None)
        for matrix_row in self.matrix:
            line = row_pixels(matrix_row)
            for _ in range(scale):
                raw += b"\x00" + line
        for _ in range(border * scale):
            raw += b"\x00" + row_pixels(None)

        def chunk(tag: bytes, payload: bytes) -> bytes:
            body = tag + payload
            return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

        header = struct.pack(">IIBBBBB", width, width, 8, 0, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b"")
        )


def make(text: str, ec_level: str = "M") -> QRCode:
    """文字列からQRコードを生成する。"""
    if ec_level not in ("L", "M"):
        raise QRError("対応している誤り訂正レベルは L / M のみです")
    data = text.encode("utf-8")
    version = _pick_version(len(data), ec_level)
    codewords = _encode_data(data, version, ec_level)

    size = version * 4 + 17
    base = _new_matrix(size)
    reserved = _new_matrix(size)
    _place_function_patterns(base, reserved, version)
    _place_data(base, reserved, codewords)

    best: tuple[int, int, list[list[int]]] | None = None
    for mask in range(8):
        candidate = _apply_mask(base, reserved, mask)
        _place_format_info(candidate, version, ec_level, mask)
        score = _penalty(candidate)
        if best is None or score < best[0]:
            best = (score, mask, candidate)

    assert best is not None
    _, mask, matrix = best
    return QRCode(matrix, version, ec_level, mask)
