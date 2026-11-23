"""
Pure-Python ISO/IEC 18004 QR Code Generator (Versions 1..6, EC Level L, Byte Mode)
for Legacy PSCam Sensor.

Zero external QR dependencies — implements Reed-Solomon GF(256) polynomial arithmetic,
format BCH(15,5) encoding, mask penalty evaluation, and high-contrast Pillow rendering.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple
from PIL import Image, ImageDraw

# Capacity (data codewords) and ECC codewords per block for QR Versions 1..6 at EC Level L
_QR_VERSION_L_SPECS: Dict[int, Tuple[int, int, List[int]]] = {
    # version: (total_data_bytes, ecc_bytes, alignment_centers)
    1: (19, 7, []),
    2: (34, 10, [6, 18]),
    3: (55, 15, [6, 22]),
    4: (80, 20, [6, 26]),
    5: (108, 26, [6, 30]),
    6: (136, 18, [6, 34]),  # Note: v6-L has 2 blocks of (68 data, 18 ecc)
}

# Precomputed BCH(15,5) format information strings for EC Level L (01) and mask patterns 0..7
_QR_FORMAT_BITS_L = [
    0x77C4, 0x72F3, 0x7DAA, 0x789D,
    0x662F, 0x6318, 0x6C41, 0x6976,
]


class QRCodeGenerator:
    """
    Pure-Python ISO/IEC 18004 QR Code matrix and Pillow image generator.
    Supports URLs up to 134 bytes (Versions 1 to 6, EC Level L, Byte Mode).
    Zero external dependencies.
    """

    _GF_EXP = [0] * 512
    _GF_LOG = [0] * 256
    _GF_INIT = False

    @classmethod
    def _init_gf(cls) -> None:
        if cls._GF_INIT:
            return
        x = 1
        for i in range(255):
            cls._GF_EXP[i] = x
            cls._GF_LOG[x] = i
            x <<= 1
            if x & 0x100:
                x ^= 0x11D
        for i in range(255, 512):
            cls._GF_EXP[i] = cls._GF_EXP[i - 255]
        cls._GF_INIT = True

    @classmethod
    def _gf_mul(cls, a: int, b: int) -> int:
        if a == 0 or b == 0:
            return 0
        return cls._GF_EXP[cls._GF_LOG[a] + cls._GF_LOG[b]]

    @classmethod
    def _rs_generator_poly(cls, degree: int) -> List[int]:
        cls._init_gf()
        poly = [1]
        for i in range(degree):
            root = cls._GF_EXP[i]
            next_poly = [0] * (len(poly) + 1)
            for j, coeff in enumerate(poly):
                next_poly[j] ^= coeff
                next_poly[j + 1] ^= cls._gf_mul(coeff, root)
            poly = next_poly
        return poly

    @classmethod
    def _rs_encode(cls, data: List[int], ecc_len: int) -> List[int]:
        gen = cls._rs_generator_poly(ecc_len)
        rem = [0] * ecc_len
        for b in data:
            factor = b ^ rem[0]
            rem = rem[1:] + [0]
            if factor != 0:
                for i in range(ecc_len):
                    rem[i] ^= cls._gf_mul(gen[i + 1], factor)
        return rem

    @classmethod
    def encode_matrix(cls, text: str) -> List[List[bool]]:
        """Encodes an ASCII/UTF-8 string into a 2D boolean QR matrix (True = dark module)."""
        payload = text.encode("utf-8")
        length = len(payload)

        # Select minimum QR version (1..6) that fits Byte mode header (4 bits mode + 8 bits len) + payload
        version = 0
        for v in range(1, 7):
            cap = _QR_VERSION_L_SPECS[v][0]
            if length + 2 <= cap:
                version = v
                break
        if version == 0:
            raise ValueError(f"QR payload too long ({length} bytes; max 134 bytes).")

        total_data, ecc_per_block, align_centers = _QR_VERSION_L_SPECS[version]

        # Build bit stream: Mode 0100 (Byte), 8-bit character count, data bytes, terminator
        bits: List[int] = [0, 1, 0, 0]
        for i in range(7, -1, -1):
            bits.append((length >> i) & 1)
        for byte in payload:
            for i in range(7, -1, -1):
                bits.append((byte >> i) & 1)

        max_bits = total_data * 8
        term = min(4, max_bits - len(bits))
        bits.extend([0] * term)
        while len(bits) % 8 != 0:
            bits.append(0)

        codewords: List[int] = []
        for i in range(0, len(bits), 8):
            val = 0
            for bit in bits[i:i + 8]:
                val = (val << 1) | bit
            codewords.append(val)

        pad_bytes = [0xEC, 0x11]
        pad_idx = 0
        while len(codewords) < total_data:
            codewords.append(pad_bytes[pad_idx % 2])
            pad_idx += 1

        # Reed-Solomon ECC generation & block interleaving
        if version < 6:
            ecc = cls._rs_encode(codewords, ecc_per_block)
            final_codewords = codewords + ecc
        else:
            b1 = codewords[:68]
            b2 = codewords[68:]
            e1 = cls._rs_encode(b1, ecc_per_block)
            e2 = cls._rs_encode(b2, ecc_per_block)
            final_codewords = []
            for i in range(68):
                final_codewords.extend((b1[i], b2[i]))
            for i in range(ecc_per_block):
                final_codewords.extend((e1[i], e2[i]))

        size = 17 + 4 * version
        matrix: List[List[Optional[bool]]] = [[None] * size for _ in range(size)]
        reserved: List[List[bool]] = [[False] * size for _ in range(size)]

        def set_func(r: int, c: int, dark: bool) -> None:
            if 0 <= r < size and 0 <= c < size:
                matrix[r][c] = dark
                reserved[r][c] = True

        # 1. Finder patterns + separators
        for fr, fc in ((0, 0), (0, size - 7), (size - 7, 0)):
            for dr in range(-1, 8):
                for dc in range(-1, 8):
                    rr, cc = fr + dr, fc + dc
                    if 0 <= rr < size and 0 <= cc < size:
                        if 0 <= dr <= 6 and 0 <= dc <= 6:
                            is_dark = (
                                dr in (0, 6)
                                or dc in (0, 6)
                                or (2 <= dr <= 4 and 2 <= dc <= 4)
                            )
                            set_func(rr, cc, is_dark)
                        else:
                            set_func(rr, cc, False)

        # 2. Alignment patterns
        for ar in align_centers:
            for ac in align_centers:
                if (ar == 6 and ac == 6) or (ar == 6 and ac == size - 7) or (ar == size - 7 and ac == 6):
                    continue
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        is_dark = max(abs(dr), abs(dc)) in (0, 2)
                        set_func(ar + dr, ac + dc, is_dark)

        # 3. Timing patterns
        for i in range(8, size - 8):
            dark = (i % 2 == 0)
            if not reserved[6][i]:
                set_func(6, i, dark)
            if not reserved[i][6]:
                set_func(i, 6, dark)

        # 4. Dark module & format info reservation
        set_func(4 * version + 9, 8, True)
        for i in range(9):
            if i != 6:
                reserved[8][i] = True
                reserved[i][8] = True
        for i in range(8):
            reserved[8][size - 1 - i] = True
            reserved[size - 1 - i][8] = True

        # 5. Zig-zag data bit placement
        all_bits: List[int] = []
        for cw in final_codewords:
            for i in range(7, -1, -1):
                all_bits.append((cw >> i) & 1)

        bit_idx = 0
        col = size - 1
        upward = True
        while col > 0:
            if col == 6:
                col -= 1
            row_iter = range(size - 1, -1, -1) if upward else range(size)
            for row in row_iter:
                for c_off in (0, -1):
                    cc = col + c_off
                    if not reserved[row][cc]:
                        dark = bool(all_bits[bit_idx]) if bit_idx < len(all_bits) else False
                        matrix[row][cc] = dark
                        bit_idx += 1
            upward = not upward
            col -= 2

        # 6. Evaluate masks 0..7 and pick lowest penalty
        best_penalty = 10**9
        best_grid: Optional[List[List[bool]]] = None

        mask_funcs: List[Callable[[int, int], bool]] = [
            lambda r, c: (r + c) % 2 == 0,
            lambda r, c: r % 2 == 0,
            lambda r, c: c % 3 == 0,
            lambda r, c: (r + c) % 3 == 0,
            lambda r, c: (r // 2 + c // 3) % 2 == 0,
            lambda r, c: ((r * c) % 2 + (r * c) % 3) == 0,
            lambda r, c: (((r * c) % 2 + (r * c) % 3) % 2) == 0,
            lambda r, c: (((r + c) % 2 + (r * c) % 3) % 2) == 0,
        ]

        for m_idx, m_fn in enumerate(mask_funcs):
            cand = [[bool(matrix[r][c]) for c in range(size)] for r in range(size)]
            for r in range(size):
                for c in range(size):
                    if not reserved[r][c] and m_fn(r, c):
                        cand[r][c] = not cand[r][c]

            cls._write_format_bits(cand, size, m_idx)
            pen = cls._compute_penalty(cand, size)
            if pen < best_penalty:
                best_penalty = pen
                best_grid = cand

        assert best_grid is not None
        return best_grid

    @staticmethod
    def _write_format_bits(grid: List[List[bool]], size: int, mask_idx: int) -> None:
        fmt = _QR_FORMAT_BITS_L[mask_idx]
        bits = [bool((fmt >> i) & 1) for i in range(15)]

        # Around top-left finder
        coords_tl = [
            (8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
            (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8),
        ]
        for idx, (r, c) in enumerate(coords_tl):
            grid[r][c] = bits[14 - idx]

        # Split between bottom-left and top-right finders
        for i in range(7):
            grid[size - 1 - i][8] = bits[14 - i]
        for i in range(7, 15):
            grid[8][size - 15 + i] = bits[14 - i]

    @staticmethod
    def _compute_penalty(grid: List[List[bool]], size: int) -> int:
        penalty = 0
        # Rule 1: 5+ consecutive same-colored modules in row/col
        for r in range(size):
            run = 1
            for c in range(1, size):
                if grid[r][c] == grid[r][c - 1]:
                    run += 1
                else:
                    if run >= 5:
                        penalty += 3 + (run - 5)
                    run = 1
            if run >= 5:
                penalty += 3 + (run - 5)

        for c in range(size):
            run = 1
            for r in range(1, size):
                if grid[r][c] == grid[r - 1][c]:
                    run += 1
                else:
                    if run >= 5:
                        penalty += 3 + (run - 5)
                    run = 1
            if run >= 5:
                penalty += 3 + (run - 5)

        # Rule 2: 2x2 blocks
        for r in range(size - 1):
            for c in range(size - 1):
                v = grid[r][c]
                if grid[r][c + 1] == v and grid[r + 1][c] == v and grid[r + 1][c + 1] == v:
                    penalty += 3
        return penalty

    @classmethod
    def render_pil_image(
        cls,
        text: str,
        box_size_px: int = 160,
        fg_color: Tuple[int, int, int, int] = (15, 23, 42, 255),
        bg_color: Tuple[int, int, int, int] = (255, 255, 255, 255),
        quiet_zone: int = 2,
    ) -> Image.Image:
        """Renders a crisp, high-contrast QR Code PIL Image ready for QPixmap conversion."""
        grid = cls.encode_matrix(text)
        n = len(grid)
        total_modules = n + quiet_zone * 2
        scale = max(4, (box_size_px * 2) // total_modules)
        canvas_px = total_modules * scale

        img = Image.new("RGBA", (canvas_px, canvas_px), bg_color)
        draw = ImageDraw.Draw(img)

        for r in range(n):
            for c in range(n):
                if grid[r][c]:
                    x0 = (c + quiet_zone) * scale
                    y0 = (r + quiet_zone) * scale
                    draw.rectangle([x0, y0, x0 + scale - 1, y0 + scale - 1], fill=fg_color)

        if canvas_px != box_size_px:
            img = img.resize((box_size_px, box_size_px), Image.Resampling.NEAREST)
        return img


__all__ = ["QRCodeGenerator"]
