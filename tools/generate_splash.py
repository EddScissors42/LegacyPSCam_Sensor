"""
Generates the PyInstaller native boot splash screen (assets/icons/splash.png)
dynamically synchronized with `version.py` (`APP_NAME` and `VERSION_STRING`).
Called automatically during PyInstaller builds (`legacy_pscam_sensor.spec`)
so the splash screen version never drifts out of sync with releases.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


def generate_splash(
    output_path: Optional[Path] = None,
    app_name: Optional[str] = None,
    version_text: Optional[str] = None,
) -> Path:
    """Renders the 480x200 Crisp White + PlayStation Blue splash screen PNG."""
    base_dir = Path(__file__).resolve().parent.parent
    if str(base_dir) not in sys.path:
        sys.path.insert(0, str(base_dir))

    import version as ver_mod

    title_str = app_name or ver_mod.APP_NAME
    ver_str = version_text or ver_mod.VERSION_STRING
    subtitle_str = "Hold on... and warm up!"
    out_file = Path(output_path) if output_path is not None else (base_dir / "assets" / "icons" / "splash.png")
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # 2x supersampling for crisp anti-aliased typography
    scale = 2
    w, h = 480 * scale, 200 * scale
    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Crisp outer border (#E2E8F0)
    border_w = 1 * scale
    draw.rectangle([0, 0, w - 1, h - 1], outline=(226, 232, 240), width=border_w)

    # Top PlayStation Blue accent bar (#00439C)
    bar_h = 4 * scale
    draw.rectangle([0, 0, w - 1, bar_h - 1], fill=(0, 67, 156))

    fonts_dir = base_dir / "assets" / "fonts"
    kanit_path = fonts_dir / "Kanit-Bold.ttf"
    dm_sans_path = fonts_dir / "DMSans.ttf"
    inter_path = fonts_dir / "InterTight-VariableFont_wght.ttf"

    def _load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
        if inter_path.is_file():
            return ImageFont.truetype(str(inter_path), size)
        return ImageFont.load_default()

    font_title = _load_font(kanit_path, 32 * scale)
    font_sub = _load_font(dm_sans_path, 15 * scale)
    font_ver = _load_font(dm_sans_path, 12 * scale)

    # Center title ("Legacy PSCam Sensor") in PlayStation Blue (#00439C)
    tb = draw.textbbox((0, 0), title_str, font=font_title)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    title_x = (w - tw) // 2 - tb[0]
    title_y = int(66 * scale) - tb[1]
    draw.text((title_x, title_y), title_str, font=font_title, fill=(0, 67, 156))

    # Center subtitle ("Hold on... and warm up!") in slate muted (#64748B)
    sb = draw.textbbox((0, 0), subtitle_str, font=font_sub)
    sw = sb[2] - sb[0]
    sub_x = (w - sw) // 2 - sb[0]
    sub_y = int(106 * scale) - sb[1]
    draw.text((sub_x, sub_y), subtitle_str, font=font_sub, fill=(100, 116, 139))

    # Bottom-right version badge in DM Sans (#94A3B8)
    vb = draw.textbbox((0, 0), ver_str, font=font_ver)
    vw, vh = vb[2] - vb[0], vb[3] - vb[1]
    ver_x = w - vw - int(16 * scale) - vb[0]
    ver_y = h - vh - int(14 * scale) - vb[1]
    draw.text((ver_x, ver_y), ver_str, font=font_ver, fill=(148, 163, 184))

    final_img = img.resize((480, 200), Image.Resampling.LANCZOS)
    final_img.save(str(out_file), format="PNG", optimize=True)
    return out_file


if __name__ == "__main__":
    p = generate_splash()
    print(f"[SPLASH] Generated {p}")
