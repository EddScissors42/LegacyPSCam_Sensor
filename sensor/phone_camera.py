"""
Smartphone Camera WebApp Server, Pure-Python QR Code Generator & Extensible Edge Protocol
for Legacy PSCam Sensor.

Allows any Android or iOS (iPhone) smartphone on the local Wi-Fi network to act as a
low-latency 30/60 FPS motion tracking camera via its built-in mobile browser (Safari / Chrome)
without installing any APK or IPA.

Architecture:
1. QRCodeGenerator: Pure-Python ISO/IEC 18004 QR Code encoder (Byte mode, Reed-Solomon GF(256))
   with high-DPI Pillow / QPixmap rendering.
2. SelfSignedTLSManager: Pure-Python ASN.1 DER X.509v3 certificate signer (with dynamic LAN IP
   in Subject Alternative Name) so mobile browsers grant `navigator.mediaDevices.getUserMedia`
   Secure Context access over `https://<LAN_IP>:<PORT>`.
3. Hybrid Extensible WebSocket Protocol (`pc_video` + `phone_edge` future-ready):
   - Mode `pc_video` (Default): Phone streams hardware-encoded JPEG binary frames with
     zero-queue backpressure (`ws.bufferedAmount === 0`), and the PC runs MediaPipe Pose.
   - Mode `phone_edge` (Future-Ready Hook): Phone can stream pre-computed `edge_metrics`
     JSON packets (`norm_landmarks`, `world_landmarks`, `kinect_joints`, `imu_accel`) for
     on-device edge offloading without changing the transport protocol.
4. PhoneCameraServer: Single-port auto-detecting HTTP/HTTPS + WS/WSS daemon server.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import math
import os
import secrets
import socket
import ssl
import struct
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

import cv2
import numpy as np
from PIL import Image, ImageDraw


# =============================================================================
# 1. PURE-PYTHON ISO/IEC 18004 QR CODE GENERATOR (VERSIONS 1..6, EC LEVEL L)
# =============================================================================

# Capacity (data codewords) and ECC codewords per block for QR Versions 1..6 at EC Level L (1 block)
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
        best_mask = 0
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
                best_mask = m_idx
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


# =============================================================================
# 2. SELF-SIGNED X.509v3 TLS CERTIFICATE GENERATOR (PURE PYTHON ASN.1 DER)
# =============================================================================

# Pre-generated dedicated local development RSA-2048 prime pair (p, q) for fast (<1ms)
# pure-Python dynamic X.509v3 certificate signing with arbitrary LAN IP SANs.
_LOCAL_RSA_P = int(
    "ee54fa447002fabbf7ddda5afeb814c83d4a10f3410c129afe22f0a6f96eaf55"
    "790680254ad3963494504103c193ed73b990d6f6ad57fd15eeed506b3f7c0f9e"
    "0ac878b67e5b251b9d7268c615ee2811a8241cb6fa5f45883c304872ecc00f75"
    "6dfa3d83565a6d98e34a6a315e4e093135b009efba5874f43b063a97319336a9",
    16,
)
_LOCAL_RSA_Q = int(
    "ea9c5505f402c2b3121a8ffd8789000319f32f3e5408d060b7df7783e8ea613a"
    "d8be19a3776db1e5714a2ca7d03cc57346d49af75d47961a4eb00336182d9fda"
    "0d29363f67350b5839ec8174e419805203723772f9282e338fa009bd2f92e60d"
    "94374a5cb4169ac08d5ed1285404134b4d1b766b85ee2d623ddf4f7c1a7d4edd",
    16,
)


def _asn1_len(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    out = []
    while length > 0:
        out.append(length & 0xFF)
        length >>= 8
    out.reverse()
    return bytes([0x80 | len(out)] + out)


def _asn1_tag(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + _asn1_len(len(content)) + content


def _asn1_int(val: int) -> bytes:
    if val == 0:
        return _asn1_tag(0x02, b"\x00")
    b = val.to_bytes((val.bit_length() + 7) // 8, "big")
    if b[0] & 0x80:
        b = b"\x00" + b
    return _asn1_tag(0x02, b)


def _asn1_seq(*items: bytes) -> bytes:
    return _asn1_tag(0x30, b"".join(items))


def _asn1_set(*items: bytes) -> bytes:
    return _asn1_tag(0x31, b"".join(items))


def _asn1_oid(oid_tuple: Tuple[int, ...]) -> bytes:
    out = [40 * oid_tuple[0] + oid_tuple[1]]
    for arc in oid_tuple[2:]:
        if arc == 0:
            out.append(0)
        else:
            sub = []
            while arc > 0:
                sub.append(arc & 0x7F)
                arc >>= 7
            for i in range(len(sub) - 1, 0, -1):
                out.append(sub[i] | 0x80)
            out.append(sub[0])
    return _asn1_tag(0x06, bytes(out))


def _asn1_utf8(text: str) -> bytes:
    return _asn1_tag(0x0C, text.encode("utf-8"))


def _asn1_utctime(ts_str: str) -> bytes:
    return _asn1_tag(0x17, ts_str.encode("ascii"))


def _asn1_bitstring(data: bytes) -> bytes:
    return _asn1_tag(0x03, b"\x00" + data)


def _asn1_octetstring(data: bytes) -> bytes:
    return _asn1_tag(0x04, data)


def _pem_encode(label: str, der_bytes: bytes) -> str:
    b64 = base64.b64encode(der_bytes).decode("ascii")
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    return f"-----BEGIN {label}-----\n" + "\n".join(lines) + f"\n-----END {label}-----\n"


class SelfSignedTLSManager:
    """
    Generates an in-memory/temp-cached X.509v3 Self-Signed Certificate & RSA-2048 Private Key
    with the current PC's LAN IPv4 address in SubjectAltName (SAN) using pure Python.
    """

    @staticmethod
    def build_self_signed_pem(lan_ip: str = "127.0.0.1") -> Tuple[str, str]:
        p = _LOCAL_RSA_P
        q = _LOCAL_RSA_Q
        n = p * q
        e = 65537
        phi = (p - 1) * (q - 1)
        d = pow(e, -1, phi)
        dp = d % (p - 1)
        dq = d % (q - 1)
        qi = pow(q, -1, p)

        # 1. PKCS#1 RSAPrivateKey DER
        priv_der = _asn1_seq(
            _asn1_int(0),
            _asn1_int(n),
            _asn1_int(e),
            _asn1_int(d),
            _asn1_int(p),
            _asn1_int(q),
            _asn1_int(dp),
            _asn1_int(dq),
            _asn1_int(qi),
        )
        key_pem = _pem_encode("RSA PRIVATE KEY", priv_der)

        # 2. X.509v3 TBSCertificate DER
        # OIDs:
        # sha256WithRSAEncryption = 1.2.840.113549.1.1.11
        # rsaEncryption = 1.2.840.113549.1.1.1
        # commonName = 2.5.4.3
        # subjectAltName = 2.5.29.17
        # basicConstraints = 2.5.29.19
        alg_sha256_rsa = _asn1_seq(_asn1_oid((1, 2, 840, 113549, 1, 1, 11)), _asn1_tag(0x05, b""))
        alg_rsa = _asn1_seq(_asn1_oid((1, 2, 840, 113549, 1, 1, 1)), _asn1_tag(0x05, b""))

        cn_attr = _asn1_seq(_asn1_oid((2, 5, 4, 3)), _asn1_utf8("Legacy PSCam Sensor"))
        name_dn = _asn1_seq(_asn1_set(cn_attr))

        validity = _asn1_seq(_asn1_utctime("240101000000Z"), _asn1_utctime("361231235959Z"))

        pub_key_der = _asn1_seq(_asn1_int(n), _asn1_int(e))
        spki = _asn1_seq(alg_rsa, _asn1_bitstring(pub_key_der))

        # SubjectAltName: DNS:localhost, IP:127.0.0.1, IP:<lan_ip>
        san_items = [
            _asn1_tag(0x82, b"localhost"),
            _asn1_tag(0x87, socket.inet_aton("127.0.0.1")),
        ]
        try:
            ip_bytes = ipaddress.IPv4Address(lan_ip).packed
            if lan_ip != "127.0.0.1":
                san_items.append(_asn1_tag(0x87, ip_bytes))
        except Exception:
            pass

        san_ext = _asn1_seq(
            _asn1_oid((2, 5, 29, 17)),
            _asn1_octetstring(_asn1_seq(*san_items)),
        )
        bc_ext = _asn1_seq(
            _asn1_oid((2, 5, 29, 19)),
            _asn1_octetstring(_asn1_seq()),
        )
        extensions = _asn1_tag(0xA3, _asn1_seq(bc_ext, san_ext))

        serial_num = int(hashlib.sha256(lan_ip.encode("utf-8")).hexdigest()[:15], 16) | 1
        tbs_der = _asn1_seq(
            _asn1_tag(0xA0, _asn1_int(2)),  # v3
            _asn1_int(serial_num),
            alg_sha256_rsa,
            name_dn,
            validity,
            name_dn,
            spki,
            extensions,
        )

        # 3. PKCS#1 v1.5 SHA-256 Signature
        digest = hashlib.sha256(tbs_der).digest()
        digest_info = _asn1_seq(
            _asn1_seq(_asn1_oid((2, 16, 840, 1, 101, 3, 4, 2, 1)), _asn1_tag(0x05, b"")),
            _asn1_octetstring(digest),
        )
        k_len = (n.bit_length() + 7) // 8
        pad_len = k_len - len(digest_info) - 3
        em = b"\x00\x01" + (b"\xFF" * pad_len) + b"\x00" + digest_info
        sig_int = pow(int.from_bytes(em, "big"), d, n)
        sig_bytes = sig_int.to_bytes(k_len, "big")

        cert_der = _asn1_seq(tbs_der, alg_sha256_rsa, _asn1_bitstring(sig_bytes))
        cert_pem = _pem_encode("CERTIFICATE", cert_der)
        return cert_pem, key_pem

    @classmethod
    def create_ssl_context(cls, lan_ip: str = "127.0.0.1") -> ssl.SSLContext:
        cert_pem, key_pem = cls.build_self_signed_pem(lan_ip)
        tmp_dir = Path(tempfile.gettempdir()) / "legacy_pscam_tls"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        cert_path = tmp_dir / "phone_cam_cert.pem"
        key_path = tmp_dir / "phone_cam_key.pem"
        cert_path.write_text(cert_pem, encoding="ascii")
        key_path.write_text(key_pem, encoding="ascii")

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
        return ctx


# =============================================================================
# 3. EMBEDDED HTML5 / JS MOBILE WEBAPP (ENGLISH UI, BACKPRESSURE + EDGE HOOKS)
# =============================================================================

EXPIRED_SESSION_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Legacy PSCam Sensor — Session Expired</title>
<style>
  body {
    background: #070B14; color: #F8FAFC;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px;
  }
  .card {
    max-width: 380px; width: 100%; background: #111827; border: 1px solid #1E293B;
    border-radius: 14px; padding: 22px; text-align: center;
  }
  h1 { font-size: 18px; margin-bottom: 10px; color: #38BDF8; }
  p { font-size: 13px; color: #94A3B8; line-height: 1.5; }
</style>
</head>
<body>
  <div class="card">
    <h1>Pairing Session Expired</h1>
    <p>This link is no longer active. Please scan the current QR Code on your PC to connect your phone camera.</p>
  </div>
</body>
</html>
"""

MOBILE_WEBAPP_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Legacy PSCam Sensor — Phone Camera</title>
<style>
  :root {
    --ps-blue: #00439C;
    --ps-accent: #38BDF8;
    --bg-dark: #070B14;
    --card-bg: #111827;
    --border: #1E293B;
    --text-main: #F8FAFC;
    --text-muted: #94A3B8;
    --ok: #22C55E;
    --warn: #F59E0B;
    --err: #EF4444;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; user-select: none; -webkit-user-select: none; }
  body {
    background: var(--bg-dark);
    color: var(--text-main);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 14px;
  }
  .header {
    width: 100%; max-width: 460px;
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 16px; background: var(--card-bg);
    border: 1px solid var(--border); border-radius: 12px;
    margin-bottom: 12px;
  }
  .brand { font-size: 16px; font-weight: 700; color: #FFFFFF; letter-spacing: 0.3px; }
  .sub { font-size: 11px; color: var(--text-muted); }
  .badge {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 5px 10px; border-radius: 999px;
    font-size: 11px; font-weight: 700;
    background: rgba(245, 158, 11, 0.15); color: var(--warn);
  }
  .badge.connected { background: rgba(34, 197, 94, 0.16); color: var(--ok); }
  .badge.error { background: rgba(239, 68, 68, 0.16); color: var(--err); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }

  .preview-wrap {
    position: relative; width: 100%; max-width: 460px;
    background: #000; border: 1px solid var(--border);
    border-radius: 14px; overflow: hidden;
    aspect-ratio: 4 / 3; display: flex; align-items: center; justify-content: center;
    margin-bottom: 12px;
  }
  video { width: 100%; height: 100%; object-fit: cover; }
  video.mirrored { transform: scaleX(-1); }
  .hud-pill {
    position: absolute; top: 10px; left: 10px;
    background: rgba(7, 11, 20, 0.78); backdrop-filter: blur(6px);
    padding: 5px 10px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.12);
    font-size: 11px; font-weight: 600; color: #E2E8F0;
  }
  .controls {
    width: 100%; max-width: 460px;
    display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
    margin-bottom: 12px;
  }
  button {
    background: var(--card-bg); color: var(--text-main);
    border: 1px solid var(--border); border-radius: 10px;
    padding: 13px 12px; font-size: 13px; font-weight: 600;
    cursor: pointer; transition: 0.15s ease;
  }
  button:active { transform: scale(0.98); background: var(--ps-blue); }
  button.primary { background: var(--ps-blue); border-color: #1D4ED8; }
  .btn-dim {
    grid-column: span 2;
    background: var(--card-bg);
    color: var(--text-muted);
    border: 1px solid var(--border);
  }
  .btn-dim:active { transform: scale(0.98); background: #1E293B; color: var(--text-main); }
  .info-card {
    width: 100%; max-width: 460px;
    background: var(--card-bg); border: 1px solid var(--border);
    border-radius: 12px; padding: 12px 14px;
    font-size: 12px; color: var(--text-muted); line-height: 1.5;
  }
  #oledOverlay {
    display: none; position: fixed; inset: 0; background: #000000;
    z-index: 9999; flex-direction: column; align-items: center; justify-content: center;
    color: #334155; font-size: 13px; text-align: center; padding: 24px;
  }
</style>
</head>
<body>
  <div class="header">
    <div>
      <div class="brand">Legacy PSCam Sensor</div>
      <div class="sub" id="deviceLabel">Phone Camera Stream</div>
    </div>
    <div class="badge" id="statusBadge"><span class="dot"></span><span id="statusText">Connecting...</span></div>
  </div>

  <div class="preview-wrap" id="previewWrap">
    <video id="camVideo" autoplay playsinline webkit-playsinline muted class="mirrored"></video>
    <div class="hud-pill" id="statsPill">Standby • Waiting for PC</div>
  </div>

  <div class="controls">
    <button id="btnLensFront" class="primary" onclick="setCameraLens('user')">Front Camera</button>
    <button id="btnLensRear" onclick="setCameraLens('environment')">Rear Camera</button>
    <button id="btnDim" class="btn-dim" onclick="enableOledSaver()">Dim Screen</button>
  </div>

  <div class="info-card" id="infoBox">
    Place your smartphone on a stable stand facing your dance area. Keep this browser tab open while dancing in Just Dance PC.
  </div>

  <div id="oledOverlay" onclick="disableOledSaver()">
    <div style="font-weight:700; color:#475569; margin-bottom:6px;">SCREEN DIMMED</div>
    <div>Tap anywhere on screen to restore preview</div>
    <div style="margin-top:8px; font-size:11px; color:#334155;">Tip: Lower phone brightness for cooler operation</div>
  </div>

  <canvas id="captureCanvas" style="display:none;"></canvas>

<script>
const sessionToken = new URLSearchParams(location.search).get("t") || "";
let ws = null;
let stream = null;
let facingMode = "user"; // "user" (Front) or "environment" (Rear)
let targetW = 640;
let targetH = 480;
let targetFps = 30;
let jpegQuality = 0.55; // Thermal-friendly quality (ideal for MediaPipe pose without overheating)
let processingMode = "pc_video"; // "pc_video" or "phone_edge" (future edge offload)
let streamingActive = false; // Standby until PC starts tracking (saves battery & prevents overheating)
let manualDisconnect = false;
let reconnectAttempts = 0;
let sentFrames = 0;
let displayFps = 0;
let lastFpsTick = performance.now();
let captureTimer = null;
let heartbeatTimer = null;
let hiddenShutdownTimer = null;
let wakeLock = null;

const previewWrap = document.getElementById("previewWrap");
const videoEl = document.getElementById("camVideo");
const canvasEl = document.getElementById("captureCanvas");
const ctx = canvasEl.getContext("2d", { alpha: false, desynchronized: true });
const statusBadge = document.getElementById("statusBadge");
const statusText = document.getElementById("statusText");
const statsPill = document.getElementById("statsPill");
const btnLensFront = document.getElementById("btnLensFront");
const btnLensRear = document.getElementById("btnLensRear");

function detectDeviceName() {
  const ua = navigator.userAgent || "";
  if (/iPhone/i.test(ua)) return "iPhone (iOS Safari)";
  if (/iPad/i.test(ua)) return "iPad (iPadOS)";
  if (/Android/i.test(ua)) {
    const m = ua.match(/Android\s+[\d.]+;\s*([^;)]+)/i);
    return m && m[1] ? `Android (${m[1].trim()})` : "Android Smartphone";
  }
  return "Smartphone WebApp";
}

function setStatus(state, text) {
  statusBadge.className = "badge " + (state === "ok" ? "connected" : (state === "err" ? "error" : ""));
  statusText.textContent = text;
}

async function requestWakeLock() {
  try {
    if ("wakeLock" in navigator) {
      wakeLock = await navigator.wakeLock.request("screen");
    }
  } catch (e) {}
}

async function startCamera() {
  if (manualDisconnect) return;
  if (stream) {
    stream.getTracks().forEach(t => t.stop());
    stream = null;
  }
  try {
    const constraints = {
      audio: false,
      video: {
        facingMode: { ideal: facingMode },
        width: { ideal: targetW },
        height: { ideal: targetH },
        frameRate: { ideal: targetFps, max: Math.max(30, targetFps) }
      }
    };
    stream = await navigator.mediaDevices.getUserMedia(constraints);
    if (manualDisconnect) {
      stream.getTracks().forEach(t => t.stop());
      stream = null;
      return;
    }
    videoEl.srcObject = stream;
    videoEl.className = (facingMode === "user") ? "mirrored" : "";
    updateLensButtons();
    await videoEl.play();
    requestWakeLock();
    sendHello();
  } catch (err) {
    setStatus("err", "Camera Permission Denied");
    document.getElementById("infoBox").textContent =
      "Could not access camera: " + err.message + ". Please allow camera access in your browser.";
  }
}

function updateLensButtons() {
  const f = document.getElementById("btnLensFront");
  const r = document.getElementById("btnLensRear");
  if (f && r) {
    if (facingMode === "user") {
      f.className = "primary";
      r.className = "";
    } else {
      f.className = "";
      r.className = "primary";
    }
  }
}

function setCameraLens(mode) {
  if (facingMode === mode && stream) return;
  facingMode = mode;
  startCamera();
}

function toggleCameraLens() {
  setCameraLens((facingMode === "user") ? "environment" : "user");
}

function enableOledSaver() {
  document.getElementById("oledOverlay").style.display = "flex";
  if (previewWrap) previewWrap.style.opacity = "0.001";
}

function disableOledSaver() {
  document.getElementById("oledOverlay").style.display = "none";
  if (previewWrap) previewWrap.style.opacity = "1";
}

function stopCaptureLoop() {
  if (captureTimer) {
    clearTimeout(captureTimer);
    captureTimer = null;
  }
  encodingInProgress = false;
}

function shutdownSession(reasonText, isError) {
  manualDisconnect = true;
  streamingActive = false;
  stopCaptureLoop();
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
  if (hiddenShutdownTimer) {
    clearTimeout(hiddenShutdownTimer);
    hiddenShutdownTimer = null;
  }
  if (stream) {
    stream.getTracks().forEach(t => t.stop());
    stream = null;
  }
  videoEl.srcObject = null;
  if (wakeLock) {
    try { wakeLock.release(); } catch (e) {}
    wakeLock = null;
  }
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    try { ws.close(1000, "Client shutdown"); } catch (e) {}
  }
  setStatus(isError ? "err" : "warn", "Disconnected");
  statsPill.textContent = "Camera Off";
  if (reasonText) {
    document.getElementById("infoBox").textContent = reasonText;
  }
}

function computeScaledDimensions(vw, vh) {
  const maxTarget = Math.max(targetW, targetH);
  const maxSrc = Math.max(vw, vh);
  const scale = maxSrc > maxTarget ? (maxTarget / maxSrc) : 1.0;
  const outW = Math.max(2, Math.round((vw * scale) / 2) * 2);
  const outH = Math.max(2, Math.round((vh * scale) / 2) * 2);
  return [outW, outH];
}

function sendHello() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const vw = videoEl.videoWidth || targetW;
  const vh = videoEl.videoHeight || targetH;
  const [outW, outH] = computeScaledDimensions(vw, vh);
  ws.send(JSON.stringify({
    type: "hello",
    device: detectDeviceName(),
    lens: facingMode,
    width: outW,
    height: outH,
    fps: targetFps,
    processing_mode: processingMode,
    capabilities: ["pc_video", "phone_edge"]
  }));
}

// Future-ready hook: transmits pre-computed landmarks/joints/IMU when processingMode === "phone_edge"
function sendEdgeMetricsPacket(metricsPayload) {
  if (!ws || ws.readyState !== WebSocket.OPEN || ws.bufferedAmount > 65536) return;
  ws.send(JSON.stringify({
    type: "edge_metrics",
    ts_ms: Date.now(),
    ...metricsPayload
  }));
}

let encodingInProgress = false;
function scheduleNextCapture(delayMs) {
  stopCaptureLoop();
  if (!streamingActive || manualDisconnect || document.hidden) return;
  captureTimer = setTimeout(captureTick, Math.max(10, delayMs));
}

function captureTick() {
  captureTimer = null;
  if (manualDisconnect || document.hidden || !streamingActive) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (processingMode !== "pc_video") return;

  const targetInterval = Math.max(16, Math.floor(1000 / Math.max(15, targetFps)));
  if (encodingInProgress || ws.bufferedAmount > 0 || videoEl.readyState < 2 || !videoEl.videoWidth) {
    scheduleNextCapture(targetInterval);
    return;
  }

  const t0 = performance.now();
  const [outW, outH] = computeScaledDimensions(videoEl.videoWidth, videoEl.videoHeight);
  if (canvasEl.width !== outW || canvasEl.height !== outH) {
    canvasEl.width = outW;
    canvasEl.height = outH;
  }

  encodingInProgress = true;
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "low";
  ctx.drawImage(videoEl, 0, 0, outW, outH);
  canvasEl.toBlob(blob => {
    encodingInProgress = false;
    if (blob && streamingActive && !manualDisconnect && !document.hidden && ws && ws.readyState === WebSocket.OPEN && ws.bufferedAmount === 0) {
      ws.send(blob);
      sentFrames++;
      const now = performance.now();
      if (now - lastFpsTick >= 1000) {
        displayFps = Math.round((sentFrames * 1000) / (now - lastFpsTick));
        sentFrames = 0;
        lastFpsTick = now;
        statsPill.textContent = `${outW}x${outH} • ${displayFps} FPS`;
      }
    }
    const elapsed = performance.now() - t0;
    scheduleNextCapture(Math.max(10, targetInterval - elapsed));
  }, "image/jpeg", jpegQuality);
}

function updateStreamingState(active) {
  streamingActive = !!active;
  if (streamingActive) {
    setStatus("ok", "Streaming to PC");
    sentFrames = 0;
    lastFpsTick = performance.now();
    scheduleNextCapture(10);
  } else {
    stopCaptureLoop();
    if (ws && ws.readyState === WebSocket.OPEN) {
      setStatus("ok", "Ready (Standby)");
      statsPill.textContent = "Standby • Waiting for PC";
    }
  }
}

function startHeartbeat() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = setInterval(() => {
    if (!manualDisconnect && !document.hidden && ws && ws.readyState === WebSocket.OPEN && !streamingActive) {
      try { ws.send(JSON.stringify({ type: "ping", ts_ms: Date.now() })); } catch (e) {}
    }
  }, 2000);
}

function connectWebSocket() {
  if (manualDisconnect || document.hidden) return;
  const proto = (location.protocol === "https:") ? "wss:" : "ws:";
  const tokenQuery = sessionToken ? `?t=${encodeURIComponent(sessionToken)}` : "";
  ws = new WebSocket(`${proto}//${location.host}/ws${tokenQuery}`);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    reconnectAttempts = 0;
    sendHello();
    startHeartbeat();
    updateStreamingState(streamingActive);
  };

  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === "config") {
        let needRestartCam = false;
        if (msg.width && msg.height && (msg.width !== targetW || msg.height !== targetH)) {
          targetW = msg.width;
          targetH = msg.height;
          needRestartCam = true;
        }
        if (msg.fps && msg.fps !== targetFps) {
          targetFps = msg.fps;
          needRestartCam = true;
        }
        if (msg.lens && msg.lens !== facingMode) {
          facingMode = msg.lens;
          needRestartCam = true;
        }
        if (msg.processing_mode) {
          processingMode = msg.processing_mode;
        }
        if (typeof msg.active === "boolean") {
          updateStreamingState(msg.active);
        }
        if (needRestartCam) startCamera();
      } else if (msg.type === "disconnect") {
        shutdownSession("Disconnected by PC. Scan the new QR Code to connect again.", false);
      }
    } catch (e) {}
  };

  ws.onclose = (ev) => {
    stopCaptureLoop();
    if (manualDisconnect || ev.code === 1000 || ev.code === 4001) {
      shutdownSession("Session ended. Scan the current QR Code on PC to connect again.", false);
      return;
    }
    if (document.hidden || reconnectAttempts >= 3) {
      shutdownSession("Connection closed. Scan the QR Code on PC to reconnect.", true);
      return;
    }
    reconnectAttempts++;
    setStatus("warn", `Reconnecting (${reconnectAttempts}/3)...`);
    setTimeout(connectWebSocket, 2000);
  };

  ws.onerror = () => {
    if (!manualDisconnect) setStatus("err", "Connection Lost");
  };
}

// Immediately release camera & socket when closing tab or switching apps on iOS/Android
window.addEventListener("pagehide", () => {
  shutdownSession("", false);
});
window.addEventListener("beforeunload", () => {
  shutdownSession("", false);
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopCaptureLoop();
    if (hiddenShutdownTimer) clearTimeout(hiddenShutdownTimer);
    hiddenShutdownTimer = setTimeout(() => {
      if (document.hidden) {
        shutdownSession("Paused in background. Scan the QR Code to reconnect.", false);
      }
    }, 3000);
  } else {
    if (hiddenShutdownTimer) {
      clearTimeout(hiddenShutdownTimer);
      hiddenShutdownTimer = null;
    }
    if (!manualDisconnect && streamingActive && ws && ws.readyState === WebSocket.OPEN) {
      scheduleNextCapture(20);
    }
  }
});

document.getElementById("deviceLabel").textContent = detectDeviceName();
startCamera().then(() => { if (!manualDisconnect) connectWebSocket(); });
</script>
</body>
</html>
"""


# =============================================================================
# 4. PHONE CAMERA SERVER (AUTO HTTP/HTTPS + RFC 6455 WEBSOCKET + EDGE METRICS)
# =============================================================================

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class PhoneCameraServer:
    """
    Single-port auto-detecting HTTP/HTTPS & WebSocket daemon server for Smartphone Camera.
    - Serves the mobile WebApp HTML5 page at `GET /`.
    - Upgrades `/ws` to a low-latency RFC 6455 WebSocket stream.
    - Supports both Mode 1 (`pc_video`: binary JPEG frames decoded via OpenCV) and
      Mode 2 (`phone_edge`: structured JSON `edge_metrics` for future on-device inference).
    """

    def __init__(self, port: int = 8443) -> None:
        self.preferred_port = int(port)
        self.actual_port = int(port)
        self.running = False
        self._server_sock: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._ssl_ctx: Optional[ssl.SSLContext] = None
        self._lock = threading.Lock()

        # Connected smartphone client state
        self.session_token: str = secrets.token_urlsafe(6)
        self.streaming_active: bool = False
        self._client_sock: Optional[socket.socket] = None
        self.is_client_connected: bool = False
        self.client_ip: str = ""
        self.client_device_name: str = "Smartphone"
        self.client_lens: str = "user"  # "user" (Front) or "environment" (Rear)
        self.client_capabilities: List[str] = ["pc_video"]
        self.processing_mode: str = "pc_video"  # "pc_video" or "phone_edge"

        # Target configuration requested by PC UI
        self.target_w: int = 640
        self.target_h: int = 480
        self.target_fps: int = 30

        # Decoded video frame buffer (Mode 1: pc_video)
        self.latest_frame: Optional[np.ndarray] = None
        self.frame_seq: int = 0
        self.last_consumed_seq: int = 0
        self.actual_w: int = 640
        self.actual_h: int = 480
        self.measured_fps: float = 0.0
        self._fps_counter: int = 0
        self._fps_last_time: float = time.time()
        self.last_frame_time: float = 0.0

        # Pre-computed edge metrics buffer (Mode 2: phone_edge future-ready slot)
        self.latest_edge_metrics: Optional[Dict[str, Any]] = None
        self.edge_metrics_seq: int = 0
        self.last_consumed_edge_seq: int = 0

    @staticmethod
    def get_local_lan_ip() -> str:
        """Detects the primary outbound LAN IPv4 address of this PC."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(0.2)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                if ip and not ip.startswith("127."):
                    return ip
        except Exception:
            pass
        try:
            hostname = socket.gethostname()
            for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                ip = info[4][0]
                if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
                    return ip
        except Exception:
            pass
        return "127.0.0.1"

    def rotate_session_token(self) -> str:
        """Generates a fresh per-session pairing token, invalidating old QR/browser links."""
        with self._lock:
            self.session_token = secrets.token_urlsafe(6)
            return self.session_token

    def get_connect_url(self) -> str:
        ip = self.get_local_lan_ip()
        return f"https://{ip}:{self.actual_port}/?t={self.session_token}"

    def start(self, port: Optional[int] = None) -> bool:
        if port is not None:
            self.preferred_port = int(port)
        if self.running and self._server_sock is not None:
            return True
        self.rotate_session_token()

        lan_ip = self.get_local_lan_ip()
        try:
            self._ssl_ctx = SelfSignedTLSManager.create_ssl_context(lan_ip)
        except Exception as e:
            print(f"[WARN] PhoneCameraServer TLS init fallback: {e}")
            self._ssl_ctx = None

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        bound = False
        for candidate_port in (self.preferred_port, 8444, 8445, 0):
            try:
                sock.bind(("0.0.0.0", candidate_port))
                self.actual_port = sock.getsockname()[1]
                bound = True
                break
            except OSError:
                continue

        if not bound:
            sock.close()
            return False

        sock.listen(8)
        sock.settimeout(0.5)
        self._server_sock = sock
        self.running = True
        self._accept_thread = threading.Thread(
            target=self._accept_loop, daemon=True, name="PhoneCameraAcceptThread"
        )
        self._accept_thread.start()
        print(f"[PHONE-CAM] Server listening on {self.get_connect_url()}")
        return True

    def stop(self) -> None:
        self.running = False
        self.disconnect_client()
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except Exception:
                pass
            self._server_sock = None

    def disconnect_client(self, rotate_token: bool = True) -> None:
        with self._lock:
            sock = self._client_sock
            self._client_sock = None
            self.is_client_connected = False
            self.streaming_active = False
            self.measured_fps = 0.0
            if rotate_token:
                self.session_token = secrets.token_urlsafe(6)
        if sock is not None:
            try:
                self._ws_send_text(sock, json.dumps({"type": "disconnect"}))
            except Exception:
                pass
            try:
                # RFC 6455 Close Frame with custom code 4001 (explicitly disconnected by PC)
                self._ws_send_frame(sock, 0x08, struct.pack("!H", 4001))
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass

    def set_streaming_active(self, active: bool) -> None:
        """Toggles phone between active video streaming and cool low-power Standby mode."""
        self.configure_stream(streaming_active=bool(active))

    def configure_stream(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fps: Optional[int] = None,
        lens: Optional[str] = None,
        processing_mode: Optional[str] = None,
        streaming_active: Optional[bool] = None,
    ) -> None:
        """Updates target stream settings and pushes live command to connected smartphone."""
        if width is not None:
            self.target_w = int(width)
        if height is not None:
            self.target_h = int(height)
        if fps is not None:
            self.target_fps = int(fps)
        if lens in ("user", "environment"):
            self.client_lens = lens
        if processing_mode in ("pc_video", "phone_edge"):
            self.processing_mode = processing_mode
        if streaming_active is not None:
            self.streaming_active = bool(streaming_active)
            if not self.streaming_active:
                self.measured_fps = 0.0

        with self._lock:
            sock = self._client_sock
        if sock is not None and self.is_client_connected:
            msg = json.dumps({
                "type": "config",
                "width": self.target_w,
                "height": self.target_h,
                "fps": self.target_fps,
                "lens": self.client_lens,
                "processing_mode": self.processing_mode,
                "active": self.streaming_active,
            })
            try:
                self._ws_send_text(sock, msg)
            except Exception:
                pass

    def read_frame(self, only_new: bool = True) -> Optional[np.ndarray]:
        """Returns the latest decoded BGR frame from the connected smartphone."""
        with self._lock:
            if self.latest_frame is None:
                return None
            if only_new and self.frame_seq == self.last_consumed_seq:
                return None
            self.last_consumed_seq = self.frame_seq
            return self.latest_frame

    def read_edge_metrics(self, only_new: bool = True) -> Optional[Dict[str, Any]]:
        """
        Future-ready consumer for on-device smartphone edge processing (`phone_edge` mode).
        Returns pre-computed landmarks/joints/IMU metrics sent by the phone.
        """
        with self._lock:
            if self.latest_edge_metrics is None:
                return None
            if only_new and self.edge_metrics_seq == self.last_consumed_edge_seq:
                return None
            self.last_consumed_edge_seq = self.edge_metrics_seq
            return self.latest_edge_metrics

    def _accept_loop(self) -> None:
        while self.running and self._server_sock is not None:
            try:
                conn, addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=self._handle_connection,
                args=(conn, addr),
                daemon=True,
                name="PhoneCameraClientThread",
            ).start()

    def _handle_connection(self, raw_conn: socket.socket, addr: Tuple[str, int]) -> None:
        conn = raw_conn
        try:
            conn.settimeout(3.0)
            try:
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except Exception:
                pass

            # Auto-detect TLS ClientHello (first byte 0x16) vs plain HTTP on the same port
            first_byte = conn.recv(1, socket.MSG_PEEK)
            if not first_byte:
                conn.close()
                return

            if first_byte[0] == 0x16 and self._ssl_ctx is not None:
                conn = self._ssl_ctx.wrap_socket(conn, server_side=True)

            req_data = b""
            while b"\r\n\r\n" not in req_data and len(req_data) < 16384:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                req_data += chunk

            if not req_data:
                conn.close()
                return

            header_text = req_data.split(b"\r\n\r\n", 1)[0].decode("latin-1", errors="replace")
            lines = header_text.split("\r\n")
            req_line = lines[0].split()
            raw_path = req_line[1] if len(req_line) >= 2 else "/"
            parsed_url = urlsplit(raw_path)
            path = parsed_url.path or "/"
            qs = parse_qs(parsed_url.query)
            req_token = qs.get("t", [""])[0]
            token_valid = bool(req_token and secrets.compare_digest(req_token, self.session_token))

            headers: Dict[str, str] = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            if headers.get("upgrade", "").lower() == "websocket" or path.startswith("/ws"):
                if not token_valid:
                    resp = (
                        "HTTP/1.1 403 Forbidden\r\n"
                        "Content-Type: text/plain\r\n"
                        "Cache-Control: no-store\r\n"
                        "Connection: close\r\n\r\n"
                        "Invalid or expired pairing token"
                    )
                    conn.sendall(resp.encode("ascii"))
                    conn.close()
                    return
                ws_key = headers.get("sec-websocket-key", "")
                if not ws_key:
                    conn.close()
                    return
                accept_val = base64.b64encode(
                    hashlib.sha1((ws_key + _WS_GUID).encode("ascii")).digest()
                ).decode("ascii")
                resp = (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept_val}\r\n\r\n"
                )
                conn.sendall(resp.encode("ascii"))
                self._run_websocket_session(conn, addr[0])
            else:
                if not token_valid:
                    body = EXPIRED_SESSION_HTML.encode("utf-8")
                    status_line = "HTTP/1.1 403 Forbidden\r\n"
                else:
                    body = MOBILE_WEBAPP_HTML.encode("utf-8")
                    status_line = "HTTP/1.1 200 OK\r\n"
                resp_hdr = (
                    status_line
                    + "Content-Type: text/html; charset=utf-8\r\n"
                    + f"Content-Length: {len(body)}\r\n"
                    + "Cache-Control: no-cache, no-store, must-revalidate\r\n"
                    + "Pragma: no-cache\r\n"
                    + "Expires: 0\r\n"
                    + "Connection: close\r\n\r\n"
                ).encode("ascii")
                conn.sendall(resp_hdr + body)
                conn.close()
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

    @staticmethod
    def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)

    @staticmethod
    def _ws_send_frame(sock: socket.socket, opcode: int, payload: bytes) -> None:
        length = len(payload)
        if length < 126:
            hdr = struct.pack("!BB", 0x80 | opcode, length)
        elif length < 65536:
            hdr = struct.pack("!BBH", 0x80 | opcode, 126, length)
        else:
            hdr = struct.pack("!BBQ", 0x80 | opcode, 127, length)
        sock.sendall(hdr + payload)

    @classmethod
    def _ws_send_text(cls, sock: socket.socket, text: str) -> None:
        cls._ws_send_frame(sock, 0x01, text.encode("utf-8"))

    def _run_websocket_session(self, sock: socket.socket, client_ip: str) -> None:
        sock.settimeout(5.0)
        with self._lock:
            old_sock = self._client_sock
            self._client_sock = sock
            self.is_client_connected = True
            self.client_ip = client_ip
            self._fps_counter = 0
            self._fps_last_time = time.time()

        if old_sock is not None and old_sock is not sock:
            try:
                old_sock.close()
            except Exception:
                pass

        # Push current target configuration immediately upon WebSocket connect
        self.configure_stream()

        try:
            while self.running:
                hdr2 = self._recv_exact(sock, 2)
                if not hdr2:
                    break
                b0, b1 = hdr2[0], hdr2[1]
                opcode = b0 & 0x0F
                masked = bool(b1 & 0x80)
                length = b1 & 0x7F

                if length == 126:
                    ext = self._recv_exact(sock, 2)
                    if not ext:
                        break
                    length = struct.unpack("!H", ext)[0]
                elif length == 127:
                    ext = self._recv_exact(sock, 8)
                    if not ext:
                        break
                    length = struct.unpack("!Q", ext)[0]

                if length > 4 * 1024 * 1024:
                    break

                mask_key = self._recv_exact(sock, 4) if masked else None
                if masked and not mask_key:
                    break

                payload = self._recv_exact(sock, length) if length > 0 else b""
                if payload is None:
                    break

                if masked and mask_key and payload:
                    # Fast vectorized XOR unmasking via numpy
                    arr = np.frombuffer(payload, dtype=np.uint8).copy()
                    mk = np.frombuffer(mask_key, dtype=np.uint8)
                    arr ^= np.resize(mk, arr.shape)
                    payload = arr.tobytes()

                if opcode == 0x08:  # Close
                    break
                elif opcode == 0x09:  # Ping -> Pong
                    self._ws_send_frame(sock, 0x0A, payload)
                elif opcode == 0x01:  # Text JSON message (hello / edge_metrics)
                    self._handle_json_message(payload.decode("utf-8", errors="replace"))
                elif opcode == 0x02:  # Binary JPEG frame
                    self._handle_binary_frame(payload)
        except Exception:
            pass
        finally:
            with self._lock:
                if self._client_sock is sock:
                    self._client_sock = None
                    self.is_client_connected = False
                    self.measured_fps = 0.0
            try:
                sock.close()
            except Exception:
                pass

    def _handle_json_message(self, raw_json: str) -> None:
        try:
            msg = json.loads(raw_json)
        except Exception:
            return
        msg_type = msg.get("type")
        if msg_type == "hello":
            with self._lock:
                self.client_device_name = str(msg.get("device") or "Smartphone")
                lens = str(msg.get("lens") or "user")
                if lens in ("user", "environment"):
                    self.client_lens = lens
                if msg.get("width") and msg.get("height"):
                    self.actual_w = int(msg["width"])
                    self.actual_h = int(msg["height"])
                caps = msg.get("capabilities")
                if isinstance(caps, list):
                    self.client_capabilities = [str(c) for c in caps]
        elif msg_type == "edge_metrics":
            with self._lock:
                self.latest_edge_metrics = msg
                self.edge_metrics_seq += 1
                self._fps_counter += 1
                now = time.time()
                self.last_frame_time = now
                elapsed = now - self._fps_last_time
                if elapsed >= 1.0:
                    self.measured_fps = self._fps_counter / elapsed
                    self._fps_counter = 0
                    self._fps_last_time = now

    def _handle_binary_frame(self, payload: bytes) -> None:
        if len(payload) < 16:
            return
        # Optional 1-byte envelope header support: 0x01 + raw JPEG, or direct 0xFF 0xD8 JPEG
        jpeg_bytes = payload[1:] if (payload[0] == 0x01 and payload[1:3] == b"\xff\xd8") else payload
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None or frame.size == 0:
            return

        h, w = frame.shape[:2]
        now = time.time()
        with self._lock:
            self.latest_frame = frame
            self.frame_seq += 1
            self.actual_w = w
            self.actual_h = h
            self.last_frame_time = now
            self._fps_counter += 1
            elapsed = now - self._fps_last_time
            if elapsed >= 1.0:
                self.measured_fps = self._fps_counter / elapsed
                self._fps_counter = 0
                self._fps_last_time = now


_GLOBAL_PHONE_CAMERA_SERVER: Optional[PhoneCameraServer] = None
_GLOBAL_SERVER_LOCK = threading.Lock()


def get_phone_camera_server(port: int = 8443) -> PhoneCameraServer:
    """Returns the singleton PhoneCameraServer instance."""
    global _GLOBAL_PHONE_CAMERA_SERVER
    with _GLOBAL_SERVER_LOCK:
        if _GLOBAL_PHONE_CAMERA_SERVER is None:
            _GLOBAL_PHONE_CAMERA_SERVER = PhoneCameraServer(port=port)
        return _GLOBAL_PHONE_CAMERA_SERVER
