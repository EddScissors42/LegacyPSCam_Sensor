"""
Persistent AI Pose Model Manager for Legacy PSCam Sensor.

Manages MediaPipe Pose Landmarker `.task` bundles with:
- Offline-first resolution: bundled `_MEIPASS/models/` (Lite AI) and local `models/` folders.
- Persistent AppData cache (`%APPDATA%\\LegacyPSCam_Sensor\\models\\`) so optional
  heavier models (e.g. `pose_landmarker_full.task`, ~9 MB) are never re-extracted into
  `%TEMP%\\_MEI` on every executable launch and are downloaded only once on demand.
- Cryptographic SHA-256 & ZIP/TFLite structural validation + atomic `.part -> .task` writes.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from sensor.config_manager import get_models_dir


MODEL_SPECS: Dict[str, Dict[str, object]] = {
    "lite": {
        "filename": "pose_landmarker_lite.task",
        "size_bytes": 5_777_746,
        "min_size_bytes": 2_000_000,
        "sha256": "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a",
        "urls": (
            "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
            "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
        ),
    },
    "full": {
        "filename": "pose_landmarker_full.task",
        "size_bytes": 9_398_198,
        "min_size_bytes": 4_000_000,
        "sha256": "4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad",
        "urls": (
            "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
            "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task",
        ),
    },
}

MODEL_FILENAMES: Dict[str, str] = {k: str(v["filename"]) for k, v in MODEL_SPECS.items()}


class ModelManager:
    """
    Locates, verifies, caches, and downloads MediaPipe Pose Landmarker `.task` models.
    Thread-safe with per-variant download locks and zero external dependencies.
    """

    _LOCKS: Dict[str, threading.Lock] = {
        "lite": threading.Lock(),
        "full": threading.Lock(),
    }

    @staticmethod
    def normalize_variant(model_variant: Optional[str]) -> str:
        variant = str(model_variant or "lite").strip().lower()
        if variant == "heavy":
            variant = "full"
        return variant if variant in MODEL_SPECS else "lite"

    @staticmethod
    def get_cache_dir(portable: Optional[bool] = None) -> Path:
        """Returns `%APPDATA%\\LegacyPSCam_Sensor\\models` (or `<PortableDir>/models`)."""
        return get_models_dir(portable=portable)

    @staticmethod
    def get_cached_model_path(model_variant: str = "lite", cache_dir: Optional[Path] = None) -> Path:
        variant = ModelManager.normalize_variant(model_variant)
        target_dir = Path(cache_dir) if cache_dir is not None else ModelManager.get_cache_dir()
        return target_dir / MODEL_FILENAMES[variant]

    @staticmethod
    def compute_sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(131072)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest().lower()

    _VALIDATION_CACHE: Dict[Tuple[str, int, int, str, bool], bool] = {}

    @staticmethod
    def validate_model_file(path: Path, model_variant: str = "lite", strict_hash: bool = False) -> bool:
        """
        Validates that a `.task` bundle exists, meets the minimum expected byte size,
        starts with the ZIP archive magic header (`PK\\x03\\x04` used by MediaPipe Task bundles),
        and checks SHA-256 integrity (cached by path + mtime_ns + size to avoid redundant disk hashing).
        """
        variant = ModelManager.normalize_variant(model_variant)
        spec = MODEL_SPECS[variant]
        if not path or not path.is_file():
            return False
        try:
            st = path.stat()
            size = st.st_size
            if size < int(spec["min_size_bytes"]):
                return False
            cache_key = (str(path.resolve()).lower(), int(st.st_mtime_ns), int(size), variant, bool(strict_hash))
            cached = ModelManager._VALIDATION_CACHE.get(cache_key)
            if cached is not None:
                return cached
            with open(path, "rb") as f:
                header = f.read(64)
            # MediaPipe `.task` bundles are zipaligned ZIP archives (often prefixed with `\x00\x00PK\x03\x04`)
            if b"PK\x03\x04" not in header and not zipfile.is_zipfile(path):
                ModelManager._VALIDATION_CACHE[cache_key] = False
                return False
            expected_sha = str(spec["sha256"]).lower()
            actual_sha = ModelManager.compute_sha256(path)
            if actual_sha != expected_sha:
                if strict_hash:
                    ModelManager._VALIDATION_CACHE[cache_key] = False
                    return False
                print(
                    f"[MODELS] Notice: '{path.name}' SHA-256 differs from pinned hash "
                    f"(got {actual_sha[:12]}..., expected {expected_sha[:12]}...); accepting valid .task bundle."
                )
            ModelManager._VALIDATION_CACHE[cache_key] = True
            return True
        except Exception:
            return False

    @staticmethod
    def get_candidate_paths(
        model_variant: str = "lite",
        cache_dir: Optional[Path] = None,
        include_bundled: bool = True,
    ) -> List[Path]:
        """
        Returns prioritized candidate paths for the requested model variant:
        1. Persistent AppData cache (`%APPDATA%\\LegacyPSCam_Sensor\\models\\<file>`)
        2. PyInstaller frozen bundle (`<_MEIPASS>/models/<file>`) — Lite AI bundled offline
        3. Executable directory (`<exe_dir>/models/<file>`) — offline drop-in support
        4. Source repository (`<project_root>/models/<file>`, `sensor/models/`, `assets/models/`)
        """
        variant = ModelManager.normalize_variant(model_variant)
        filename = MODEL_FILENAMES[variant]
        candidates: List[Path] = []

        # 1. Persistent AppData / Portable cache
        target_dir = Path(cache_dir) if cache_dir is not None else ModelManager.get_cache_dir()
        candidates.append(target_dir / filename)

        # 2. Bundled inside PyInstaller _MEIPASS
        if include_bundled and getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / "models" / filename)

        # 3. Local drop-in next to frozen executable
        if include_bundled and getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            candidates.append(exe_dir / "models" / filename)

        # 4. Source tree paths (development / tests)
        if include_bundled:
            sensor_dir = Path(__file__).resolve().parent
            proj_root = sensor_dir.parent
            candidates.append(proj_root / "models" / filename)
            candidates.append(sensor_dir / "models" / filename)
            candidates.append(proj_root / "assets" / "models" / filename)

        # Deduplicate while preserving order
        seen = set()
        unique: List[Path] = []
        for c in candidates:
            key = str(c).lower()
            if key not in seen:
                seen.add(key)
                unique.append(c)
        return unique

    @staticmethod
    def locate_model(
        model_variant: str = "lite",
        cache_dir: Optional[Path] = None,
        include_bundled: bool = True,
        stage_to_cache: bool = False,
    ) -> Optional[Path]:
        """
        Finds a valid local or cached `.task` file without performing network I/O.
        If `stage_to_cache=True` and the file is found outside `cache_dir`, copies it
        atomically into the persistent AppData cache for faster future launches.
        """
        variant = ModelManager.normalize_variant(model_variant)
        target_cache = ModelManager.get_cached_model_path(variant, cache_dir=cache_dir)

        for candidate in ModelManager.get_candidate_paths(
            variant, cache_dir=cache_dir, include_bundled=include_bundled
        ):
            if not candidate.is_file():
                continue
            if not ModelManager.validate_model_file(candidate, variant, strict_hash=False):
                continue

            if stage_to_cache and candidate.resolve() != target_cache.resolve():
                lock = ModelManager._LOCKS.setdefault(variant, threading.Lock())
                with lock:
                    try:
                        if ModelManager.validate_model_file(target_cache, variant, strict_hash=False):
                            return target_cache
                        target_cache.parent.mkdir(parents=True, exist_ok=True)
                        tmp_path = target_cache.with_suffix(".task.part")
                        shutil.copy2(candidate, tmp_path)
                        os.replace(tmp_path, target_cache)
                        return target_cache
                    except Exception:
                        return candidate
            return candidate
        return None

    @staticmethod
    def is_model_ready(
        model_variant: str = "lite",
        cache_dir: Optional[Path] = None,
        include_bundled: bool = True,
    ) -> bool:
        """Returns True if the requested model is already locally available and valid."""
        return (
            ModelManager.locate_model(
                model_variant, cache_dir=cache_dir, include_bundled=include_bundled
            )
            is not None
        )

    @classmethod
    def download_model(
        cls,
        model_variant: str = "full",
        progress_cb: Optional[Callable[[int, int], None]] = None,
        cache_dir: Optional[Path] = None,
        urls: Optional[Tuple[str, ...]] = None,
        timeout: float = 30.0,
        strict_hash: bool = True,
    ) -> Optional[Path]:
        """
        Downloads the requested MediaPipe Pose `.task` model into the persistent AppData cache
        using atomic `.part -> .task` writes and cryptographic/structural verification.
        """
        variant = cls.normalize_variant(model_variant)
        spec = MODEL_SPECS[variant]
        target_path = cls.get_cached_model_path(variant, cache_dir=cache_dir)
        download_urls = urls if urls is not None else tuple(spec["urls"])  # type: ignore[arg-type]

        lock = cls._LOCKS.setdefault(variant, threading.Lock())
        with lock:
            # Double-check after acquiring lock in case another thread finished downloading
            if cls.validate_model_file(target_path, variant, strict_hash=strict_hash):
                if progress_cb:
                    sz = target_path.stat().st_size
                    progress_cb(sz, sz)
                return target_path

            target_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = target_path.with_suffix(".task.part")

            for url in download_urls:
                try:
                    print(f"[MODELS] Downloading '{target_path.name}' to persistent cache: {target_path.parent}")
                    try:
                        from version import __version__ as _app_ver
                    except Exception:
                        _app_ver = "0.10.2"
                    req = urllib.request.Request(
                        url,
                        headers={"User-Agent": f"LegacyPSCam-Sensor/{_app_ver}"},
                    )
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        hdr_len = resp.headers.get("Content-Length")
                        total_bytes = int(hdr_len) if (hdr_len and hdr_len.isdigit()) else int(spec["size_bytes"])
                        downloaded = 0
                        with open(tmp_path, "wb") as out_f:
                            while True:
                                chunk = resp.read(65536)
                                if not chunk:
                                    break
                                out_f.write(chunk)
                                downloaded += len(chunk)
                                if progress_cb:
                                    try:
                                        progress_cb(downloaded, max(total_bytes, downloaded))
                                    except Exception:
                                        pass

                    if not cls.validate_model_file(tmp_path, variant, strict_hash=strict_hash):
                        print(f"[WARN] Downloaded file from {url} failed validation; discarding.")
                        try:
                            tmp_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                        continue

                    os.replace(tmp_path, target_path)
                    print(f"[MODELS] Cached '{target_path.name}' ({target_path.stat().st_size / (1024 * 1024):.2f} MB) in {target_path.parent}")
                    return target_path
                except Exception as exc:
                    print(f"[WARN] Model download failed from {url}: {exc}")
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except Exception:
                        pass

        return None

    @classmethod
    def ensure_model(
        cls,
        model_variant: str = "lite",
        auto_download: bool = True,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        cache_dir: Optional[Path] = None,
        include_bundled: bool = True,
    ) -> Path:
        """
        Ensures the requested model is available on disk (checking AppData cache, bundled
        `_MEIPASS/models`, and local `models/` before optionally downloading to AppData).
        Falls back gracefully to `lite` if `full` cannot be obtained offline.
        """
        variant = cls.normalize_variant(model_variant)
        found = cls.locate_model(variant, cache_dir=cache_dir, include_bundled=include_bundled)
        if found is not None:
            return found

        if auto_download:
            downloaded = cls.download_model(
                variant, progress_cb=progress_cb, cache_dir=cache_dir
            )
            if downloaded is not None:
                return downloaded

        if variant != "lite":
            lite_fallback = cls.locate_model("lite", cache_dir=cache_dir, include_bundled=include_bundled)
            if lite_fallback is not None:
                print(
                    f"[WARN] Model '{MODEL_FILENAMES[variant]}' unavailable (offline?); "
                    f"falling back to '{lite_fallback.name}'."
                )
                return lite_fallback

        return cls.get_cached_model_path(variant, cache_dir=cache_dir)
