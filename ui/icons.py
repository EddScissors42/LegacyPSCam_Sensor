"""
High-Resolution Anti-Aliased Icon and Pill Generators for Legacy PSCam Sensor UI.
Renders supersampled Pillow graphics for sidebar navigation, top tabs, and rounded buttons.
"""
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageTk


def make_pill_image(w: int, h: int, fill, outline=None, radius: int = 12):
    """Generates an anti-aliased rounded rectangle pill image."""
    scale = 4
    img = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        [2 * scale, 2 * scale, w * scale - 3 * scale, h * scale - 3 * scale],
        radius=radius * scale,
        fill=fill,
        outline=outline,
        width=1 * scale
    )
    return ImageTk.PhotoImage(img.resize((w, h), Image.Resampling.LANCZOS))


def load_pscam_file_icon(png_path: Path, target_box=(38, 26), color=(255, 255, 255)):
    """
    Loads user-provided IconePSCAMERA.png, converts dark background to transparent alpha,
    recolors the icon graphic to the target color, and scales it into target_box.
    """
    if not png_path.exists():
        return None
    try:
        import numpy as np
        im = Image.open(png_path).convert("RGBA")
        arr = np.array(im)
        # Compute luminance of RGB to isolate the white camera graphic from the dark background
        lum = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
        # Smooth alpha mapping (threshold dark noise at 15, full opacity at 180)
        alpha = np.clip((lum - 15) / (180 - 15) * 255, 0, 255).astype(np.uint8)

        out_arr = np.zeros_like(arr)
        out_arr[:, :, 0] = color[0]
        out_arr[:, :, 1] = color[1]
        out_arr[:, :, 2] = color[2]
        out_arr[:, :, 3] = alpha

        colored_im = Image.fromarray(out_arr, "RGBA")
        bbox = colored_im.getbbox()
        if not bbox:
            return None
        cropped = colored_im.crop(bbox)

        # Scale proportionally to fit within target_box
        bw, bh = target_box
        scale = min(bw / cropped.width, bh / cropped.height)
        new_w = max(1, int(cropped.width * scale))
        new_h = max(1, int(cropped.height * scale))
        resized = cropped.resize((new_w, new_h), Image.Resampling.LANCZOS)

        canvas = Image.new("RGBA", target_box, (0, 0, 0, 0))
        canvas.paste(resized, ((bw - new_w) // 2, (bh - new_h) // 2))
        return canvas
    except Exception as e:
        print(f"[WARN] Failed to process IconePSCAMERA.png: {e}")
        return None


def generate_icons():
    """
    Renders supersampled icons for the sidebar navigation:
    1. PlayStation 4 Camera (loaded from IconePSCAMERA.png with vector fallback).
    2. Generic round Webcam (circular head with lens aperture and stand, perfectly centered with no clipping).
    Returns active (white) and inactive (dark blue) ImageTk.PhotoImage variants.
    """
    target_box = (38, 26)
    base_dir = Path(__file__).resolve().parent
    png_candidates = [
        base_dir.parent / "assets" / "IconePSCAMERA.png",
        base_dir / "assets" / "IconePSCAMERA.png",
        base_dir.parent / "IconePSCAMERA.png",
        base_dir / "IconePSCAMERA.png"
    ]
    png_path = next((p for p in png_candidates if p.exists()), base_dir.parent / "assets" / "IconePSCAMERA.png")

    # 1. PS4 Camera Icon (from file or vector fallback)
    ps_file_act = load_pscam_file_icon(png_path, target_box=target_box, color=(255, 255, 255))
    ps_file_inact = load_pscam_file_icon(png_path, target_box=target_box, color=(0, 67, 156))

    if ps_file_act is not None and ps_file_inact is not None:
        p_ps_act = ImageTk.PhotoImage(ps_file_act)
        p_ps_inact = ImageTk.PhotoImage(ps_file_inact)
    else:
        # Fallback vector icon
        scale = 4
        w, h = target_box[0] * scale, target_box[1] * scale
        img_ps_act = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img_ps_act)
        d.rounded_rectangle([int(w * 0.08), int(h * 0.28), int(w * 0.92), int(h * 0.54)],
                            radius=int(5 * scale), fill=(255, 255, 255, 255))
        lr = int(3.8 * scale)
        cy = int(h * 0.41)
        d.ellipse([int(w * 0.30) - lr, cy - lr, int(w * 0.30) + lr, cy + lr], fill=(0, 67, 156, 255))
        d.ellipse([int(w * 0.70) - lr, cy - lr, int(w * 0.70) + lr, cy + lr], fill=(0, 67, 156, 255))
        d.rectangle([int(w * 0.44), int(h * 0.54), int(w * 0.56), int(h * 0.76)], fill=(255, 255, 255, 255))
        d.rounded_rectangle([int(w * 0.25), int(h * 0.76), int(w * 0.75), int(h * 0.86)],
                            radius=int(2 * scale), fill=(255, 255, 255, 255))
        p_ps_act = ImageTk.PhotoImage(img_ps_act.resize(target_box, Image.Resampling.LANCZOS))

        img_ps_inact = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img_ps_inact)
        d.rounded_rectangle([int(w * 0.08), int(h * 0.28), int(w * 0.92), int(h * 0.54)],
                            radius=int(5 * scale), fill=(0, 67, 156, 255))
        d.ellipse([int(w * 0.30) - lr, cy - lr, int(w * 0.30) + lr, cy + lr], fill=(221, 240, 247, 255))
        d.ellipse([int(w * 0.70) - lr, cy - lr, int(w * 0.70) + lr, cy + lr], fill=(221, 240, 247, 255))
        d.rectangle([int(w * 0.44), int(h * 0.54), int(w * 0.56), int(h * 0.76)], fill=(0, 67, 156, 255))
        d.rounded_rectangle([int(w * 0.25), int(h * 0.76), int(w * 0.75), int(h * 0.86)],
                            radius=int(2 * scale), fill=(0, 67, 156, 255))
        p_ps_inact = ImageTk.PhotoImage(img_ps_inact.resize(target_box, Image.Resampling.LANCZOS))

    # 2. Webcam Icon (Properly padded with zero clipping at the top or bottom)
    scale = 4
    w, h = target_box[0] * scale, target_box[1] * scale
    cr = int(7 * scale)          # Radius 28
    ccx = w // 2                 # 76
    ccy = int(h * 0.38)          # 39 -> top of head is 11 > 0 (plenty of room)

    # 2.1 Active Webcam Icon (White on PlayStation Blue)
    img_web_act = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img_web_act)
    # Head circle
    d.ellipse([ccx - cr, ccy - cr, ccx + cr, ccy + cr], fill=(255, 255, 255, 255))
    # Outer lens ring
    d.ellipse([ccx - int(5 * scale), ccy - int(5 * scale), ccx + int(5 * scale), ccy + int(5 * scale)],
              fill=(221, 240, 247, 255))
    # Inner lens aperture
    d.ellipse([ccx - int(3 * scale), ccy - int(3 * scale), ccx + int(3 * scale), ccy + int(3 * scale)],
              fill=(0, 67, 156, 255))
    # Glint highlight
    d.ellipse([ccx - int(2 * scale), ccy - int(2 * scale), ccx - int(0.5 * scale), ccy - int(0.5 * scale)],
              fill=(255, 255, 255, 255))
    # Stand stem
    stem_top = ccy + cr - int(1 * scale)
    stem_bottom = int(h * 0.80)
    d.rectangle([int(w * 0.45), stem_top, int(w * 0.55), stem_bottom], fill=(255, 255, 255, 255))
    # Stand base
    d.rounded_rectangle([int(w * 0.24), stem_bottom, int(w * 0.76), int(h * 0.92)],
                        radius=int(2 * scale), fill=(255, 255, 255, 255))
    p_web_act = ImageTk.PhotoImage(img_web_act.resize(target_box, Image.Resampling.LANCZOS))

    # 2.2 Inactive Webcam Icon (PlayStation Blue on light background)
    img_web_inact = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img_web_inact)
    d.ellipse([ccx - cr, ccy - cr, ccx + cr, ccy + cr], fill=(0, 67, 156, 255))
    d.ellipse([ccx - int(5 * scale), ccy - int(5 * scale), ccx + int(5 * scale), ccy + int(5 * scale)],
              fill=(221, 240, 247, 255))
    d.ellipse([ccx - int(3 * scale), ccy - int(3 * scale), ccx + int(3 * scale), ccy + int(3 * scale)],
              fill=(0, 67, 156, 255))
    d.ellipse([ccx - int(2 * scale), ccy - int(2 * scale), ccx - int(0.5 * scale), ccy - int(0.5 * scale)],
              fill=(255, 255, 255, 255))
    d.rectangle([int(w * 0.45), stem_top, int(w * 0.55), stem_bottom], fill=(0, 67, 156, 255))
    d.rounded_rectangle([int(w * 0.24), stem_bottom, int(w * 0.76), int(h * 0.92)],
                        radius=int(2 * scale), fill=(0, 67, 156, 255))
    p_web_inact = ImageTk.PhotoImage(img_web_inact.resize(target_box, Image.Resampling.LANCZOS))

    return p_ps_act, p_ps_inact, p_web_act, p_web_inact


def generate_tab_icons():
    """
    Renders supersampled icons for the top navigation tabs:
    1. Gear icon for 'Configuração de Vídeo'
    2. Sliders icon (3 horizontal lines with adjustment knobs) for 'Calibração'
    Returns active (dark #0F172A) and inactive (muted #64748B) PhotoImage pairs.
    """
    size = (18, 18)
    scale = 4
    w, h = size[0] * scale, size[1] * scale

    def make_gear(color):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        cx, cy = w / 2, h / 2
        r_outer = w * 0.44
        r_inner = w * 0.30
        r_hole = w * 0.15
        teeth = 8
        for i in range(teeth):
            angle = (2 * math.pi / teeth) * i
            tw = 0.22
            pts = [
                (cx + r_inner * math.cos(angle - tw), cy + r_inner * math.sin(angle - tw)),
                (cx + r_outer * math.cos(angle - tw * 0.65), cy + r_outer * math.sin(angle - tw * 0.65)),
                (cx + r_outer * math.cos(angle + tw * 0.65), cy + r_outer * math.sin(angle + tw * 0.65)),
                (cx + r_inner * math.cos(angle + tw), cy + r_inner * math.sin(angle + tw)),
            ]
            d.polygon(pts, fill=color)
        d.ellipse([cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner], fill=color)
        d.ellipse([cx - r_hole, cy - r_hole, cx + r_hole, cy + r_hole], fill=(0, 0, 0, 0))
        return ImageTk.PhotoImage(img.resize(size, Image.Resampling.LANCZOS))

    def make_sliders(color):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        line_w = int(2.2 * scale)
        knob_r = int(3.5 * scale)
        y_coords = [int(h * 0.23), int(h * 0.50), int(h * 0.77)]
        knob_xs = [int(w * 0.34), int(w * 0.68), int(w * 0.44)]
        x_left = int(w * 0.10)
        x_right = int(w * 0.90)
        for y, kx in zip(y_coords, knob_xs):
            d.line([(x_left, y), (x_right, y)], fill=color, width=line_w)
            d.ellipse([kx - knob_r, y - knob_r, kx + knob_r, y + knob_r], fill=color)
            hole_r = int(1.6 * scale)
            d.ellipse([kx - hole_r, y - hole_r, kx + hole_r, y + hole_r], fill=(226, 232, 240, 255))
        return ImageTk.PhotoImage(img.resize(size, Image.Resampling.LANCZOS))

    col_act = (15, 23, 42, 255)       # Dark charcoal
    col_inact = (100, 116, 139, 255)  # Muted slate
    return make_gear(col_act), make_gear(col_inact), make_sliders(col_act), make_sliders(col_inact)


def generate_status_icons(size=(38, 38)):
    """
    Renders supersampled status badges for device connection status:
    1. Error: Red circular badge with a large, crisp X.
    2. OK: Green circular badge with a crisp checkmark.
    3. Warn: Amber circular badge with an exclamation mark.
    """
    scale = 4
    w, h = size[0] * scale, size[1] * scale
    pad = int(1.5 * scale)

    # 1. Error (Large X badge)
    img_err = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d_err = ImageDraw.Draw(img_err)
    d_err.ellipse([pad, pad, w - pad, h - pad], fill=(254, 226, 226, 255), outline=(252, 165, 165, 255), width=int(1.2 * scale))
    cx, cy = w / 2, h / 2
    r = int(7.5 * scale)
    lw = int(3.2 * scale)
    d_err.line([(cx - r, cy - r), (cx + r, cy + r)], fill=(220, 38, 38, 255), width=lw)
    d_err.line([(cx - r, cy + r), (cx + r, cy - r)], fill=(220, 38, 38, 255), width=lw)
    cr = lw / 2.0
    for px, py in [(cx - r, cy - r), (cx + r, cy + r), (cx - r, cy + r), (cx + r, cy - r)]:
        d_err.ellipse([px - cr, py - cr, px + cr, py + cr], fill=(220, 38, 38, 255))
    icon_err = ImageTk.PhotoImage(img_err.resize(size, Image.Resampling.LANCZOS))

    # 2. OK (Checkmark badge)
    img_ok = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d_ok = ImageDraw.Draw(img_ok)
    d_ok.ellipse([pad, pad, w - pad, h - pad], fill=(209, 250, 229, 255), outline=(134, 239, 172, 255), width=int(1.2 * scale))
    lw = int(3.2 * scale)
    pts = [
        (cx - int(7 * scale), cy + int(0.5 * scale)),
        (cx - int(2 * scale), cy + int(5.5 * scale)),
        (cx + int(7.5 * scale), cy - int(4.5 * scale))
    ]
    d_ok.line(pts, fill=(5, 150, 105, 255), width=lw, joint="curve")
    cr = lw / 2.0
    d_ok.ellipse([pts[0][0] - cr, pts[0][1] - cr, pts[0][0] + cr, pts[0][1] + cr], fill=(5, 150, 105, 255))
    d_ok.ellipse([pts[2][0] - cr, pts[2][1] - cr, pts[2][0] + cr, pts[2][1] + cr], fill=(5, 150, 105, 255))
    icon_ok = ImageTk.PhotoImage(img_ok.resize(size, Image.Resampling.LANCZOS))

    # 3. Warn (! badge)
    img_warn = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d_warn = ImageDraw.Draw(img_warn)
    d_warn.ellipse([pad, pad, w - pad, h - pad], fill=(254, 243, 199, 255), outline=(252, 211, 77, 255), width=int(1.2 * scale))
    lw = int(3.2 * scale)
    d_warn.line([(cx, cy - int(7 * scale)), (cx, cy + int(1.5 * scale))], fill=(217, 119, 6, 255), width=lw)
    cr = lw / 2.0
    d_warn.ellipse([cx - cr, cy - int(7 * scale) - cr, cx + cr, cy - int(7 * scale) + cr], fill=(217, 119, 6, 255))
    d_warn.ellipse([cx - cr, cy + int(1.5 * scale) - cr, cx + cr, cy + int(1.5 * scale) + cr], fill=(217, 119, 6, 255))
    d_warn.ellipse([cx - cr, cy + int(4.5 * scale) - cr, cx + cr, cy + int(4.5 * scale) + cr], fill=(217, 119, 6, 255))
    icon_warn = ImageTk.PhotoImage(img_warn.resize(size, Image.Resampling.LANCZOS))

    return icon_err, icon_ok, icon_warn
