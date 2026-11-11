"""
Legacy PSCam Sensor — Telemetry Benchmark & Calibration Comparator
Compares 3D acceleration telemetry streams between Camera (Virtual Phone) and
DualShock 4 physical hardware IMU for the same Just Dance song to benchmark
accuracy, peak G-forces, time latency, and determine the optimal sensitivity gain.
"""

from __future__ import annotations

import csv
import math
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


def parse_telemetry_csv(file_path: str | Path) -> Dict[str, Any]:
    """
    Parses a Legacy PSCam Sensor accelerometer telemetry CSV file.
    Supports both legacy 10-column and extended 13-column schemas.
    """
    p = Path(file_path)
    if not p.is_file():
        raise FileNotFoundError(f"Telemetry log not found: {file_path}")

    timestamps_ms: List[int] = []
    ax_list: List[float] = []
    ay_list: List[float] = []
    az_list: List[float] = []
    mag_list: List[float] = []
    speed_list: List[float] = []
    feedback_list: List[Tuple[int, str]] = []

    detected_source = "unknown"
    detected_map = ""

    # Infer from filename if available: e.g. Levitating_camera_1700000000.csv
    fn_lower = p.name.lower()
    if "_camera_" in fn_lower or fn_lower.endswith("_camera.csv") or "cam" in fn_lower:
        detected_source = "camera"
    elif "_ds4_" in fn_lower or fn_lower.endswith("_ds4.csv") or "ds4" in fn_lower:
        detected_source = "ds4"

    # Extract map name from filename prefix
    parts = p.stem.split("_")
    if len(parts) >= 2 and parts[1] in ("camera", "ds4", "vphone"):
        detected_map = parts[0]

    with open(p, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader, None)

        for row in reader:
            if not row or len(row) < 4:
                continue
            try:
                ts = int(float(row[0]))
                ax = float(row[1])
                ay = float(row[2])
                az = float(row[3])
                mag = math.sqrt(ax * ax + ay * ay + az * az)

                spd = float(row[4]) if len(row) > 4 and row[4].strip() else 0.0

                timestamps_ms.append(ts)
                ax_list.append(ax)
                ay_list.append(ay)
                az_list.append(az)
                mag_list.append(mag)
                speed_list.append(spd)

                # Extended columns if present
                if len(row) >= 11 and row[10].strip():
                    detected_source = row[10].strip().lower()
                if len(row) >= 12 and row[11].strip():
                    detected_map = row[11].strip()
                if len(row) >= 13 and row[12].strip():
                    feedback_list.append((ts, row[12].strip().upper()))

            except (ValueError, IndexError):
                continue

    if not timestamps_ms:
        raise ValueError(f"Telemetry log '{p.name}' contains no valid data rows.")

    ts_arr = np.array(timestamps_ms, dtype=np.int64)
    mag_arr = np.array(mag_list, dtype=np.float32)
    speed_arr = np.array(speed_list, dtype=np.float32)

    # Normalize relative time to start at 0.0 seconds
    time_s = (ts_arr - ts_arr[0]) / 1000.0
    duration_s = float(time_s[-1]) if len(time_s) > 0 else 0.0
    hz = float(len(time_s) / duration_s) if duration_s > 0.1 else 0.0

    peak_g = float(np.max(mag_arr)) if len(mag_arr) > 0 else 1.0
    p95_g = float(np.percentile(mag_arr, 95)) if len(mag_arr) > 0 else 1.0
    p99_g = float(np.percentile(mag_arr, 99)) if len(mag_arr) > 0 else 1.0
    mean_g = float(np.mean(mag_arr)) if len(mag_arr) > 0 else 1.0

    return {
        "file_path": str(p.resolve()),
        "file_name": p.name,
        "source": detected_source,
        "map_name": detected_map or "UnknownSong",
        "sample_count": len(timestamps_ms),
        "duration_s": round(duration_s, 2),
        "sample_rate_hz": round(hz, 1),
        "peak_g": round(peak_g, 3),
        "p95_g": round(p95_g, 3),
        "p99_g": round(p99_g, 3),
        "mean_g": round(mean_g, 3),
        "time_s": time_s,
        "mag_g": mag_arr,
        "ax": np.array(ax_list, dtype=np.float32),
        "ay": np.array(ay_list, dtype=np.float32),
        "az": np.array(az_list, dtype=np.float32),
        "speed": speed_arr,
        "feedbacks": feedback_list,
    }


def compare_telemetries(
    camera_data: Dict[str, Any] | str | Path,
    ds4_data: Dict[str, Any] | str | Path,
    current_sensitivity: float = 1.2,
    target_hz: float = 60.0,
) -> Dict[str, Any]:
    """
    Compares two telemetry runs of the same song (Camera vs DualShock 4),
    performing dynamic time alignment (cross-correlation), peak matching,
    latency calculation, and optimal sensitivity suggestion.
    """
    if not isinstance(camera_data, dict):
        camera_data = parse_telemetry_csv(camera_data)
    if not isinstance(ds4_data, dict):
        ds4_data = parse_telemetry_csv(ds4_data)

    cam_time = camera_data["time_s"]
    cam_mag = camera_data["mag_g"]
    ds4_time = ds4_data["time_s"]
    ds4_mag = ds4_data["mag_g"]

    # Common duration
    common_duration = min(camera_data["duration_s"], ds4_data["duration_s"])
    if common_duration < 2.0:
        raise ValueError("Logs are too short for meaningful benchmark (< 2.0s).")

    # Uniform resampling grid at target_hz (default 60 FPS)
    dt = 1.0 / target_hz
    grid_t = np.arange(0.0, common_duration, dt)

    cam_interp = np.interp(grid_t, cam_time, cam_mag)
    ds4_interp = np.interp(grid_t, ds4_time, ds4_mag)

    # Center curves by removing mean gravity baseline (~1.0G)
    cam_centered = cam_interp - np.mean(cam_interp)
    ds4_centered = ds4_interp - np.mean(ds4_interp)

    # Cross-correlation to find optimal alignment lag within +- 5.0 seconds
    max_lag_samples = int(5.0 * target_hz)
    correlation = np.correlate(ds4_centered, cam_centered, mode="full")
    lags = np.arange(-len(cam_centered) + 1, len(ds4_centered))

    # Restrict search within [-max_lag_samples, +max_lag_samples]
    valid_mask = (lags >= -max_lag_samples) & (lags <= max_lag_samples)
    lags_window = lags[valid_mask]
    corr_window = correlation[valid_mask]

    best_idx = np.argmax(corr_window)
    best_lag_samples = lags_window[best_idx]
    lag_ms = round(float(best_lag_samples * dt * 1000.0), 1)

    # Shift camera curve according to best lag
    if best_lag_samples > 0:
        aligned_ds4 = ds4_interp[best_lag_samples:]
        aligned_cam = cam_interp[: len(aligned_ds4)]
        aligned_t = grid_t[: len(aligned_ds4)]
    elif best_lag_samples < 0:
        shift = abs(best_lag_samples)
        aligned_cam = cam_interp[shift:]
        aligned_ds4 = ds4_interp[: len(aligned_cam)]
        aligned_t = grid_t[: len(aligned_cam)]
    else:
        aligned_cam = cam_interp
        aligned_ds4 = ds4_interp
        aligned_t = grid_t

    # Compute Pearson correlation coefficient R on aligned segment
    c_norm_cam = aligned_cam - np.mean(aligned_cam)
    c_norm_ds4 = aligned_ds4 - np.mean(aligned_ds4)
    denom = np.sqrt(np.sum(c_norm_cam**2) * np.sum(c_norm_ds4**2))
    pearson_r = float(np.sum(c_norm_cam * c_norm_ds4) / denom) if denom > 1e-6 else 0.0

    # Dynamic peak analysis (acceleration peaks above 1.4G)
    cam_peaks = aligned_cam[aligned_cam > 1.4]
    ds4_peaks = aligned_ds4[aligned_ds4 > 1.4]

    cam_peak_val = float(np.percentile(cam_peaks, 90)) if len(cam_peaks) > 5 else float(np.percentile(aligned_cam, 95))
    ds4_peak_val = float(np.percentile(ds4_peaks, 90)) if len(ds4_peaks) > 5 else float(np.percentile(aligned_ds4, 95))

    # Base gravity subtraction for ratio calculation: G_dynamic = G_peak - 1.0G
    dyn_cam = max(0.2, cam_peak_val - 1.0)
    dyn_ds4 = max(0.2, ds4_peak_val - 1.0)
    gain_ratio = dyn_ds4 / dyn_cam

    suggested_sensitivity = round(float(current_sensitivity * gain_ratio), 2)
    suggested_sensitivity = max(0.5, min(3.5, suggested_sensitivity))

    # Subsample aligned preview points for UI charting (up to 300 points)
    step = max(1, len(aligned_t) // 250)
    chart_t = [round(float(v), 2) for v in aligned_t[::step]]
    chart_cam = [round(float(v), 2) for v in aligned_cam[::step]]
    chart_ds4 = [round(float(v), 2) for v in aligned_ds4[::step]]

    return {
        "map_name": camera_data.get("map_name") or ds4_data.get("map_name") or "UnknownSong",
        "camera_file": camera_data["file_name"],
        "ds4_file": ds4_data["file_name"],
        "aligned_duration_s": round(float(aligned_t[-1] if len(aligned_t) else 0.0), 1),
        "correlation_pct": round(float(pearson_r * 100.0), 1),
        "lag_ms": lag_ms,
        "cam_max_g": camera_data["peak_g"],
        "ds4_max_g": ds4_data["peak_g"],
        "cam_p95_g": camera_data["p95_g"],
        "ds4_p95_g": ds4_data["p95_g"],
        "cam_sample_rate": camera_data["sample_rate_hz"],
        "ds4_sample_rate": ds4_data["sample_rate_hz"],
        "current_sensitivity": round(float(current_sensitivity), 2),
        "gain_ratio": round(float(gain_ratio), 3),
        "suggested_sensitivity": suggested_sensitivity,
        "chart_t": chart_t,
        "chart_cam": chart_cam,
        "chart_ds4": chart_ds4,
    }


def find_available_benchmarks(logs_dir: str | Path) -> List[Dict[str, Any]]:
    """
    Scans the logs folder and identifies songs that have both a Camera log
    and a DualShock 4 log, ready for 1-click comparison.
    """
    p = Path(logs_dir)
    if not p.is_dir():
        return []

    csv_files = list(p.glob("*.csv"))
    groups: Dict[str, Dict[str, Path]] = {}

    for f in csv_files:
        name_lower = f.stem.lower()
        parts = f.stem.split("_")
        if len(parts) >= 2:
            map_name = parts[0]
            tag = parts[1].lower()
            if tag in ("camera", "ds4", "vphone"):
                resolved_tag = "camera" if tag in ("camera", "vphone") else "ds4"
                if map_name not in groups:
                    groups[map_name] = {}
                # Keep latest file per tag
                if resolved_tag not in groups[map_name] or f.stat().st_mtime > groups[map_name][resolved_tag].stat().st_mtime:
                    groups[map_name][resolved_tag] = f

    benchmarks = []
    for map_name, data in groups.items():
        benchmarks.append({
            "map_name": map_name,
            "has_camera": "camera" in data,
            "has_ds4": "ds4" in data,
            "is_ready": ("camera" in data and "ds4" in data),
            "camera_path": str(data["camera"].resolve()) if "camera" in data else "",
            "ds4_path": str(data["ds4"].resolve()) if "ds4" in data else "",
        })

    # Sort ready benchmarks first, then alphabetically
    benchmarks.sort(key=lambda b: (not b["is_ready"], b["map_name"]))
    return benchmarks
