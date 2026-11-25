"""
Self-Signed X.509v3 TLS Certificate Generator (Pure-Python ASN.1 DER)
for Legacy PSCam Sensor.

Generates dynamic RSA-2048 X.509v3 certificates with SubjectAltName (LAN IPv4)
using only the Python standard library so mobile browsers grant Secure Context
access to `navigator.mediaDevices.getUserMedia` over `https://<LAN_IP>:<PORT>`.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import socket
import ssl
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

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
    def build_self_signed_pem(
        lan_ip: str = "127.0.0.1",
        extra_ips: Optional[Iterable[str]] = None,
    ) -> Tuple[str, str]:
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
        alg_sha256_rsa = _asn1_seq(_asn1_oid((1, 2, 840, 113549, 1, 1, 11)), _asn1_tag(0x05, b""))
        alg_rsa = _asn1_seq(_asn1_oid((1, 2, 840, 113549, 1, 1, 1)), _asn1_tag(0x05, b""))

        cn_attr = _asn1_seq(_asn1_oid((2, 5, 4, 3)), _asn1_utf8("Legacy PSCam Sensor"))
        name_dn = _asn1_seq(_asn1_set(cn_attr))

        validity = _asn1_seq(_asn1_utctime("240101000000Z"), _asn1_utctime("361231235959Z"))

        pub_key_der = _asn1_seq(_asn1_int(n), _asn1_int(e))
        spki = _asn1_seq(alg_rsa, _asn1_bitstring(pub_key_der))

        # SubjectAltName: DNS:localhost, IP:127.0.0.1, plus all unique local LAN IPv4 addresses
        san_items = [
            _asn1_tag(0x82, b"localhost"),
            _asn1_tag(0x87, socket.inet_aton("127.0.0.1")),
        ]
        unique_ips: List[str] = []
        candidates = [lan_ip]
        if extra_ips:
            candidates.extend(extra_ips)
        for cand_ip in candidates:
            ip_str = str(cand_ip or "").strip()
            if not ip_str or ip_str == "127.0.0.1" or ip_str in unique_ips:
                continue
            try:
                ip_bytes = ipaddress.IPv4Address(ip_str).packed
                san_items.append(_asn1_tag(0x87, ip_bytes))
                unique_ips.append(ip_str)
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

        serial_seed = "|".join([lan_ip] + sorted(unique_ips))
        serial_num = int(hashlib.sha256(serial_seed.encode("utf-8")).hexdigest()[:15], 16) | 1
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
    def create_ssl_context(
        cls,
        lan_ip: str = "127.0.0.1",
        extra_ips: Optional[Iterable[str]] = None,
    ) -> ssl.SSLContext:
        cert_pem, key_pem = cls.build_self_signed_pem(lan_ip, extra_ips=extra_ips)
        tmp_dir = Path(tempfile.gettempdir()) / "legacy_pscam_tls"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        cert_path = tmp_dir / "phone_cam_cert.pem"
        key_path = tmp_dir / "phone_cam_key.pem"
        cert_path.write_text(cert_pem, encoding="ascii")
        key_path.write_text(key_pem, encoding="ascii")

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
        return ctx


__all__ = ["SelfSignedTLSManager"]
