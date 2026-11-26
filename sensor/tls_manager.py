"""
Self-Signed X.509v3 TLS Certificate Generator (Pure-Python ASN.1 DER)
for Legacy PSCam Sensor.

Generates a unique per-installation RSA-2048 private key (persisted locally in
AppData/tls with atomic writes) and signs dynamic X.509v3 certificates with
SubjectAltName (LAN IPv4), 365-day validity (iOS/Chrome compliant), KeyUsage,
and ExtendedKeyUsage (serverAuth) using only the Python standard library.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import math
import os
import secrets
import socket
import ssl
import tempfile
import threading
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

# Small prime sieve for fast candidate filtering during RSA-2048 key generation
def _build_small_primes(limit: int = 1500) -> Tuple[int, ...]:
    sieve = bytearray([1]) * (limit + 1)
    sieve[0:2] = b"\x00\x00"
    for p in range(2, int(limit ** 0.5) + 1):
        if sieve[p]:
            sieve[p * p : limit + 1 : p] = b"\x00" * (((limit - p * p) // p) + 1)
    return tuple(i for i in range(3, limit + 1) if sieve[i])


_SMALL_PRIMES: Tuple[int, ...] = _build_small_primes(1500)
_RSA_KEY_LOCK = threading.Lock()
_CACHED_RSA_KEY: Optional[Tuple[int, int, int, int, int, int, int, int]] = None


def _is_probable_prime(n: int, rounds: int = 24) -> bool:
    if n < 2:
        return False
    for p in _SMALL_PRIMES:
        if n == p:
            return True
        if n % p == 0:
            return False

    # Write n - 1 = d * 2^s
    d = n - 1
    s = 0
    while (d & 1) == 0:
        d >>= 1
        s += 1

    for _ in range(rounds):
        a = secrets.randbelow(n - 3) + 2
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _generate_prime(bits: int) -> int:
    top_mask = (1 << (bits - 1)) | (1 << (bits - 2)) | 1
    while True:
        cand = secrets.randbits(bits) | top_mask
        # Fast small-prime filter before Miller-Rabin
        divisible = False
        for p in _SMALL_PRIMES:
            if cand % p == 0:
                divisible = True
                break
        if divisible:
            continue
        if _is_probable_prime(cand, rounds=24):
            return cand


def _generate_rsa_2048_params() -> Tuple[int, int, int, int, int, int, int, int]:
    """Generates fresh cryptographically random RSA-2048 parameters (p, q, n, e, d, dp, dq, qi)."""
    e = 65537
    while True:
        p = _generate_prime(1024)
        q = _generate_prime(1024)
        if p == q:
            continue
        n = p * q
        if n.bit_length() != 2048:
            continue
        phi = (p - 1) * (q - 1)
        if math.gcd(e, phi) != 1:
            continue
        d = pow(e, -1, phi)
        dp = d % (p - 1)
        dq = d % (q - 1)
        qi = pow(q, -1, p)
        return (p, q, n, e, d, dp, dq, qi)


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


def _asn1_bool(val: bool) -> bytes:
    return _asn1_tag(0x01, b"\xFF" if val else b"\x00")


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


def _asn1_bitstring(data: bytes, unused_bits: int = 0) -> bytes:
    return _asn1_tag(0x03, bytes([unused_bits]) + data)


def _asn1_octetstring(data: bytes) -> bytes:
    return _asn1_tag(0x04, data)


def _pem_encode(label: str, der_bytes: bytes) -> str:
    b64 = base64.b64encode(der_bytes).decode("ascii")
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    return f"-----BEGIN {label}-----\n" + "\n".join(lines) + f"\n-----END {label}-----\n"


def _parse_pkcs1_rsa_pem(pem_text: str) -> Optional[Tuple[int, int, int, int, int, int, int, int]]:
    """Parses a PKCS#1 RSAPrivateKey PEM back into (p, q, n, e, d, dp, dq, qi)."""
    try:
        b64_lines = [
            ln.strip()
            for ln in pem_text.splitlines()
            if ln.strip() and not ln.strip().startswith("-----")
        ]
        der = base64.b64decode("".join(b64_lines))
        pos = 0

        def read_tlv() -> Tuple[int, bytes]:
            nonlocal pos
            tag = der[pos]
            pos += 1
            ln = der[pos]
            pos += 1
            if ln & 0x80:
                n_oct = ln & 0x7F
                ln = int.from_bytes(der[pos : pos + n_oct], "big")
                pos += n_oct
            val = der[pos : pos + ln]
            pos += ln
            return tag, val

        tag, seq_body = read_tlv()
        if tag != 0x30:
            return None
        # Parse 9 ASN.1 integers inside sequence: version, n, e, d, p, q, dp, dq, qi
        inner_pos = 0
        ints: List[int] = []
        while inner_pos < len(seq_body) and len(ints) < 9:
            if seq_body[inner_pos] != 0x02:
                return None
            inner_pos += 1
            ln = seq_body[inner_pos]
            inner_pos += 1
            if ln & 0x80:
                n_oct = ln & 0x7F
                ln = int.from_bytes(seq_body[inner_pos : inner_pos + n_oct], "big")
                inner_pos += n_oct
            val_bytes = seq_body[inner_pos : inner_pos + ln]
            inner_pos += ln
            ints.append(int.from_bytes(val_bytes, "big"))
        if len(ints) != 9 or ints[0] != 0:
            return None
        _, n, e, d, p, q, dp, dq, qi = ints
        if n != p * q or n.bit_length() < 2048 or (e * d) % ((p - 1) * (q - 1)) != 1:
            return None
        return (p, q, n, e, d, dp, dq, qi)
    except Exception:
        return None


def _get_tls_storage_dir() -> Path:
    try:
        from sensor.config_manager import get_app_data_dir
        tls_dir = get_app_data_dir() / "tls"
        tls_dir.mkdir(parents=True, exist_ok=True)
        return tls_dir
    except Exception:
        fallback = Path(tempfile.gettempdir()) / "legacy_pscam_tls"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    tmp_path.write_text(content, encoding="ascii")
    os.replace(tmp_path, path)


def _encode_pkcs1_rsa_pem(params: Tuple[int, int, int, int, int, int, int, int]) -> str:
    p, q, n, e, d, dp, dq, qi = params
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
    return _pem_encode("RSA PRIVATE KEY", priv_der)


def _get_or_create_installation_rsa_key() -> Tuple[int, int, int, int, int, int, int, int]:
    """
    Loads the per-installation RSA-2048 key from AppData/tls/device_key.pem, or generates
    and persists a fresh unique key atomically on first run (never uses hardcoded repo primes).
    """
    global _CACHED_RSA_KEY
    with _RSA_KEY_LOCK:
        if _CACHED_RSA_KEY is not None:
            return _CACHED_RSA_KEY

        key_path = _get_tls_storage_dir() / "device_key.pem"
        if key_path.is_file():
            try:
                parsed = _parse_pkcs1_rsa_pem(key_path.read_text(encoding="ascii"))
                if parsed is not None:
                    _CACHED_RSA_KEY = parsed
                    return parsed
            except Exception:
                pass

        params = _generate_rsa_2048_params()
        try:
            _atomic_write_text(key_path, _encode_pkcs1_rsa_pem(params))
        except Exception:
            pass
        _CACHED_RSA_KEY = params
        return params


class SelfSignedTLSManager:
    """
    Generates a per-installation RSA-2048 Private Key & X.509v3 Self-Signed Certificate
    with the current PC's LAN IPv4 addresses in SubjectAltName (SAN) using pure Python.
    """

    @staticmethod
    def build_self_signed_pem(
        lan_ip: str = "127.0.0.1",
        extra_ips: Optional[Iterable[str]] = None,
        validity_days: int = 365,
    ) -> Tuple[str, str]:
        params = _get_or_create_installation_rsa_key()
        p, q, n, e, d, dp, dq, qi = params
        key_pem = _encode_pkcs1_rsa_pem(params)

        # 2. X.509v3 TBSCertificate DER
        alg_sha256_rsa = _asn1_seq(_asn1_oid((1, 2, 840, 113549, 1, 1, 11)), _asn1_tag(0x05, b""))
        alg_rsa = _asn1_seq(_asn1_oid((1, 2, 840, 113549, 1, 1, 1)), _asn1_tag(0x05, b""))

        cn_attr = _asn1_seq(_asn1_oid((2, 5, 4, 3)), _asn1_utf8("Legacy PSCam Sensor"))
        name_dn = _asn1_seq(_asn1_set(cn_attr))

        # Dynamic validity capped <= 397 days for modern iOS Safari & Chrome leaf cert compliance
        safe_days = max(1, min(397, int(validity_days)))
        now_utc = datetime.now(timezone.utc)
        not_before = (now_utc - timedelta(days=1)).strftime("%y%m%d%H%M%SZ")
        not_after = (now_utc + timedelta(days=safe_days)).strftime("%y%m%d%H%M%SZ")
        validity = _asn1_seq(_asn1_utctime(not_before), _asn1_utctime(not_after))

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
            _asn1_bool(True),
            _asn1_octetstring(_asn1_seq()),
        )
        # KeyUsage (2.5.29.15, critical): digitalSignature (bit 0) + keyEncipherment (bit 2) = 0xA0, 5 unused bits
        ku_ext = _asn1_seq(
            _asn1_oid((2, 5, 29, 15)),
            _asn1_bool(True),
            _asn1_octetstring(_asn1_bitstring(b"\xA0", unused_bits=5)),
        )
        # ExtendedKeyUsage (2.5.29.37): id-kp-serverAuth (1.3.6.1.5.5.7.3.1)
        eku_ext = _asn1_seq(
            _asn1_oid((2, 5, 29, 37)),
            _asn1_octetstring(_asn1_seq(_asn1_oid((1, 3, 6, 1, 5, 5, 7, 3, 1)))),
        )
        extensions = _asn1_tag(0xA3, _asn1_seq(bc_ext, ku_ext, eku_ext, san_ext))

        serial_seed = "|".join([lan_ip, not_before] + sorted(unique_ips))
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
        tls_dir = _get_tls_storage_dir()
        cert_path = tls_dir / "phone_cam_cert.pem"
        key_path = tls_dir / "phone_cam_key.pem"
        with _RSA_KEY_LOCK:
            _atomic_write_text(cert_path, cert_pem)
            _atomic_write_text(key_path, key_pem)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
        return ctx


__all__ = ["SelfSignedTLSManager"]
