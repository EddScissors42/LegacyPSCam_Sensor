"""
High-Resolution Anti-Aliased Icon and Pill Generators for Legacy PSCam Sensor UI.
Renders supersampled Pillow graphics for sidebar navigation, top tabs, and rounded buttons.
Supports both pure PIL.Image outputs (for Qt6 / PySide6) and ImageTk.PhotoImage outputs (for Tkinter).
Loads custom user SVG icons for 'settings' (Video Settings) and 'sliders' (Calibration) with vector fallback.
"""
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageTk


def make_pill_image(w: int, h: int, fill, outline=None, radius: int = 12):
    """Generates an anti-aliased rounded rectangle pill image for Tkinter."""
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


def load_pscam_file_icon(png_path: Path, target_box=(38, 26), color=(255, 255, 255), scale: int = 4):
    """
    Loads user-provided IconePSCAMERA.png, converts dark background to transparent alpha,
    recolors the icon graphic to the target color, and scales it into target_box * scale.
    """
    if not png_path or not png_path.exists():
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

        # Scale proportionally to fit within scaled target box
        bw, bh = target_box[0] * scale, target_box[1] * scale
        fit_scale = min(bw / cropped.width, bh / cropped.height)
        new_w = max(1, int(cropped.width * fit_scale))
        new_h = max(1, int(cropped.height * fit_scale))
        resized = cropped.resize((new_w, new_h), Image.Resampling.LANCZOS)

        canvas = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        canvas.paste(resized, ((bw - new_w) // 2, (bh - new_h) // 2))
        return canvas
    except Exception as e:
        print(f"[WARN] Failed to process IconePSCAMERA.png: {e}")
        return None


def load_ds4_file_icon(jpg_path: Path, target_box=(38, 26), color=(255, 255, 255), scale: int = 4):
    """
    Loads user-provided dualshock4.jpg, inverts the white background into transparent alpha,
    recolors the controller graphic to target color, and scales it into target_box * scale.
    """
    if not jpg_path or not Path(jpg_path).exists():
        return None
    try:
        import numpy as np
        im = Image.open(jpg_path).convert("L")
        arr = np.array(im)
        inv = 255 - arr
        alpha = np.clip((inv.astype(float) - 15) / (180 - 15) * 255, 0, 255).astype(np.uint8)

        out_arr = np.zeros((arr.shape[0], arr.shape[1], 4), dtype=np.uint8)
        out_arr[:, :, 0] = color[0]
        out_arr[:, :, 1] = color[1]
        out_arr[:, :, 2] = color[2]
        out_arr[:, :, 3] = alpha

        colored_im = Image.fromarray(out_arr, "RGBA")
        bbox = colored_im.getbbox()
        if not bbox:
            return None
        cropped = colored_im.crop(bbox)

        bw, bh = target_box[0] * scale, target_box[1] * scale
        fit_scale = min(bw / cropped.width, bh / cropped.height)
        new_w = max(1, int(cropped.width * fit_scale))
        new_h = max(1, int(cropped.height * fit_scale))
        resized = cropped.resize((new_w, new_h), Image.Resampling.LANCZOS)

        canvas = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        canvas.paste(resized, ((bw - new_w) // 2, (bh - new_h) // 2))
        return canvas
    except Exception as e:
        print(f"[WARN] Failed to process dualshock4.jpg: {e}")
        return None


def generate_ds4_icons_pil(target_box=(38, 26), scale: int = 4):
    """
    Renders supersampled PIL.Image RGBA icons for the DualShock 4 sidebar navigation card.
    Returns (pil_ds4_act, pil_ds4_inact) rendered at target_box * scale.
    """
    base_dir = Path(__file__).resolve().parent
    jpg_candidates = [
        base_dir.parent / "assets" / "dualshock4.jpg",
        base_dir.parent / "assets" / "icons" / "dualshock4.jpg",
        base_dir / "assets" / "dualshock4.jpg",
        base_dir / "assets" / "icons" / "dualshock4.jpg",
    ]
    jpg_path = next((p for p in jpg_candidates if p.exists()), None)

    ds4_act = load_ds4_file_icon(jpg_path, target_box=target_box, color=(255, 255, 255), scale=scale)
    ds4_inact = load_ds4_file_icon(jpg_path, target_box=target_box, color=(0, 67, 156), scale=scale)

    if ds4_act is None or ds4_inact is None:
        w, h = target_box[0] * scale, target_box[1] * scale

        def make_gamepad(col):
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            # Controller body pill
            d.rounded_rectangle([int(w * 0.12), int(h * 0.20), int(w * 0.88), int(h * 0.75)],
                                radius=int(6 * scale), fill=col)
            # Left grip
            d.rounded_rectangle([int(w * 0.12), int(h * 0.40), int(w * 0.35), int(h * 0.92)],
                                radius=int(4 * scale), fill=col)
            # Right grip
            d.rounded_rectangle([int(w * 0.65), int(h * 0.40), int(w * 0.88), int(h * 0.92)],
                                radius=int(4 * scale), fill=col)
            return img

        if ds4_act is None:
            ds4_act = make_gamepad((255, 255, 255, 255))
        if ds4_inact is None:
            ds4_inact = make_gamepad((0, 67, 156, 255))

    return ds4_act, ds4_inact


def generate_controller_tab_icon_pil(size=(18, 18), scale: int = 4):
    """
    Renders supersampled PIL.Image RGBA icons for the 'Controller Settings' top navigation tab.
    Loads controller.svg with vector fallback.
    Returns (ctrl_act, ctrl_inact).
    """
    base_dir = Path(__file__).resolve().parent
    svg_candidates = [
        base_dir.parent / "assets" / "controller.svg",
        base_dir.parent / "assets" / "icons" / "controller.svg",
        base_dir / "assets" / "controller.svg",
        base_dir / "assets" / "icons" / "controller.svg",
    ]
    svg_path = next((p for p in svg_candidates if p.exists()), None)

    ctrl_act = render_svg_icon_pil(svg_path, size=size, color_hex="#0F172A", scale=scale)
    ctrl_inact = render_svg_icon_pil(svg_path, size=size, color_hex="#64748B", scale=scale)

    if ctrl_act is None or ctrl_inact is None:
        w, h = size[0] * scale, size[1] * scale

        def make_tab_gamepad(col):
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle([int(w * 0.08), int(h * 0.22), int(w * 0.92), int(h * 0.78)],
                                radius=int(3 * scale), fill=col)
            return img

        if ctrl_act is None:
            ctrl_act = make_tab_gamepad((15, 23, 42, 255))
        if ctrl_inact is None:
            ctrl_inact = make_tab_gamepad((100, 116, 139, 255))

    return ctrl_act, ctrl_inact


def generate_icons_pil(target_box=(38, 26), scale: int = 4):
    """
    Renders supersampled PIL.Image RGBA icons for the sidebar navigation:
    1. PlayStation 4 Camera (loaded from assets/icons/IconePSCAMERA.png with vector fallback).
    2. Generic round Webcam (circular head with lens aperture and stand).
    Returns (pil_ps_act, pil_ps_inact, pil_web_act, pil_web_inact) rendered at target_box * scale.
    """
    base_dir = Path(__file__).resolve().parent
    png_candidates = [
        base_dir.parent / "assets" / "icons" / "IconePSCAMERA.png",
        base_dir.parent / "assets" / "IconePSCAMERA.png",
        base_dir / "assets" / "icons" / "IconePSCAMERA.png",
        base_dir / "assets" / "IconePSCAMERA.png",
        base_dir.parent / "IconePSCAMERA.png",
        base_dir / "IconePSCAMERA.png"
    ]
    png_path = next((p for p in png_candidates if p.exists()), base_dir.parent / "assets" / "icons" / "IconePSCAMERA.png")

    # 1. PS4 Camera Icon (from file or vector fallback)
    ps_file_act = load_pscam_file_icon(png_path, target_box=target_box, color=(255, 255, 255), scale=scale)
    ps_file_inact = load_pscam_file_icon(png_path, target_box=target_box, color=(0, 67, 156), scale=scale)

    w, h = target_box[0] * scale, target_box[1] * scale

    if ps_file_act is None or ps_file_inact is None:
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
        ps_file_act = img_ps_act if scale > 1 else img_ps_act.resize(target_box, Image.Resampling.LANCZOS)

        img_ps_inact = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img_ps_inact)
        d.rounded_rectangle([int(w * 0.08), int(h * 0.28), int(w * 0.92), int(h * 0.54)],
                            radius=int(5 * scale), fill=(0, 67, 156, 255))
        d.ellipse([int(w * 0.30) - lr, cy - lr, int(w * 0.30) + lr, cy + lr], fill=(221, 240, 247, 255))
        d.ellipse([int(w * 0.70) - lr, cy - lr, int(w * 0.70) + lr, cy + lr], fill=(221, 240, 247, 255))
        d.rectangle([int(w * 0.44), int(h * 0.54), int(w * 0.56), int(h * 0.76)], fill=(0, 67, 156, 255))
        d.rounded_rectangle([int(w * 0.25), int(h * 0.76), int(w * 0.75), int(h * 0.86)],
                            radius=int(2 * scale), fill=(0, 67, 156, 255))
        ps_file_inact = img_ps_inact if scale > 1 else img_ps_inact.resize(target_box, Image.Resampling.LANCZOS)

    # 2. Webcam Icon (Properly padded with zero clipping at the top or bottom)
    cr = int(7 * scale)
    ccx = w // 2
    ccy = int(h * 0.38)
    stem_top = ccy + cr - int(1 * scale)
    stem_bottom = int(h * 0.80)

    # 2.1 Active Webcam Icon (White on PlayStation Blue)
    img_web_act = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img_web_act)
    d.ellipse([ccx - cr, ccy - cr, ccx + cr, ccy + cr], fill=(255, 255, 255, 255))
    d.ellipse([ccx - int(5 * scale), ccy - int(5 * scale), ccx + int(5 * scale), ccy + int(5 * scale)],
              fill=(221, 240, 247, 255))
    d.ellipse([ccx - int(3 * scale), ccy - int(3 * scale), ccx + int(3 * scale), ccy + int(3 * scale)],
              fill=(0, 67, 156, 255))
    d.ellipse([ccx - int(2 * scale), ccy - int(2 * scale), ccx - int(0.5 * scale), ccy - int(0.5 * scale)],
              fill=(255, 255, 255, 255))
    d.rectangle([int(w * 0.45), stem_top, int(w * 0.55), stem_bottom], fill=(255, 255, 255, 255))
    d.rounded_rectangle([int(w * 0.24), stem_bottom, int(w * 0.76), int(h * 0.92)],
                        radius=int(2 * scale), fill=(255, 255, 255, 255))
    web_act_pil = img_web_act if scale > 1 else img_web_act.resize(target_box, Image.Resampling.LANCZOS)

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
    web_inact_pil = img_web_inact if scale > 1 else img_web_inact.resize(target_box, Image.Resampling.LANCZOS)

    return ps_file_act, ps_file_inact, web_act_pil, web_inact_pil


def generate_icons():
    """Returns ImageTk.PhotoImage variants for Tkinter sidebar navigation."""
    ps_act, ps_inact, web_act, web_inact = generate_icons_pil(scale=1)
    return (
        ImageTk.PhotoImage(ps_act),
        ImageTk.PhotoImage(ps_inact),
        ImageTk.PhotoImage(web_act),
        ImageTk.PhotoImage(web_inact),
    )


def render_svg_icon_pil(svg_path: Path, size: tuple = (18, 18), color_hex: str = "#0F172A", scale: int = 4):
    """
    Renders an SVG file to a transparent, tinted PIL RGBA Image.
    Uses Qt's QSvgRenderer with Antialiasing and SmoothPixmapTransform.
    Returns (w*scale, h*scale) supersampled image for crisp Retina/High-DPI rendering.
    """
    if not svg_path or not Path(svg_path).exists():
        return None
    try:
        from PySide6.QtGui import QImage, QPainter, QColor
        from PySide6.QtCore import Qt
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            QApplication([])

        ren = QSvgRenderer(str(svg_path))
        if not ren.isValid():
            return None

        w, h = size
        pw, ph = w * scale, h * scale
        qimg = QImage(pw, ph, QImage.Format.Format_RGBA8888)
        qimg.fill(Qt.GlobalColor.transparent)
        p = QPainter(qimg)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        ren.render(p)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        p.fillRect(qimg.rect(), QColor(color_hex))
        p.end()

        pil_raw = Image.frombytes("RGBA", (pw, ph), qimg.bits().tobytes())
        return pil_raw
    except Exception:
        return None


def generate_tab_icons_pil(size=(18, 18), scale: int = 4):
    """
    Renders supersampled PIL.Image RGBA icons for the top navigation tabs:
    1. Settings SVG icon for 'Video Settings' (active & inactive)
    2. Sliders SVG icon for 'Calibration' (active, inactive, & disabled)
    3. Lab SVG icon for 'Experimental' (active & inactive)
    Returns (settings_act, settings_inact, sliders_act, sliders_inact, sliders_disabled, lab_act, lab_inact).
    """
    base_dir = Path(__file__).resolve().parent
    settings_candidates = [
        base_dir.parent / "assets" / "icons" / "settings.svg",
        base_dir.parent / "assets" / "settings.svg",
        base_dir / "assets" / "icons" / "settings.svg",
        base_dir / "assets" / "settings.svg",
    ]
    settings_path = next((p for p in settings_candidates if p.exists()), None)

    sliders_candidates = [
        base_dir.parent / "assets" / "icons" / "sliders.svg",
        base_dir.parent / "assets" / "sliders.svg",
        base_dir / "assets" / "icons" / "sliders.svg",
        base_dir / "assets" / "sliders.svg",
    ]
    sliders_path = next((p for p in sliders_candidates if p.exists()), None)

    lab_candidates = [
        base_dir.parent / "assets" / "icons" / "lab.svg",
        base_dir.parent / "assets" / "lab.svg",
        base_dir / "assets" / "icons" / "lab.svg",
        base_dir / "assets" / "lab.svg",
    ]
    lab_path = next((p for p in lab_candidates if p.exists()), None)

    col_act = "#0F172A"
    col_inact = "#64748B"
    col_disabled = "#94A3B8"

    set_act = render_svg_icon_pil(settings_path, size=size, color_hex=col_act, scale=scale)
    set_inact = render_svg_icon_pil(settings_path, size=size, color_hex=col_inact, scale=scale)
    slid_act = render_svg_icon_pil(sliders_path, size=size, color_hex=col_act, scale=scale)
    slid_inact = render_svg_icon_pil(sliders_path, size=size, color_hex=col_inact, scale=scale)
    slid_dis = render_svg_icon_pil(sliders_path, size=size, color_hex=col_disabled, scale=scale)
    lab_act = render_svg_icon_pil(lab_path, size=size, color_hex=col_act, scale=scale)
    lab_inact = render_svg_icon_pil(lab_path, size=size, color_hex=col_inact, scale=scale)

    # Procedural vector fallbacks if SVGs cannot be loaded/rendered
    if (
        set_act is None
        or set_inact is None
        or slid_act is None
        or slid_inact is None
        or slid_dis is None
        or lab_act is None
        or lab_inact is None
    ):
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
            return img

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
                d.ellipse([kx - hole_r, y - hole_r, kx + hole_r, y + hole_r], fill=(0, 0, 0, 0))
            return img

        def make_lab(color):
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            cx = w // 2
            top_y = int(h * 0.12)
            neck_bottom = int(h * 0.42)
            neck_w = int(w * 0.20)
            rim_w = int(w * 0.32)
            bot_y = int(h * 0.88)
            bot_w = int(w * 0.72)
            d.rounded_rectangle(
                [cx - rim_w // 2, top_y - int(1.5 * scale), cx + rim_w // 2, top_y + int(1.5 * scale)],
                radius=int(1 * scale), fill=color
            )
            d.rectangle([cx - neck_w // 2, top_y, cx + neck_w // 2, neck_bottom], fill=color)
            pts = [
                (cx - neck_w // 2, neck_bottom),
                (cx + neck_w // 2, neck_bottom),
                (cx + bot_w // 2, bot_y),
                (cx - bot_w // 2, bot_y),
            ]
            d.polygon(pts, fill=color)
            return img

        col_act_tuple = (15, 23, 42, 255)
        col_inact_tuple = (100, 116, 139, 255)
        col_dis_tuple = (148, 163, 184, 255)
        if set_act is None:
            set_act = make_gear(col_act_tuple)
        if set_inact is None:
            set_inact = make_gear(col_inact_tuple)
        if slid_act is None:
            slid_act = make_sliders(col_act_tuple)
        if slid_inact is None:
            slid_inact = make_sliders(col_inact_tuple)
        if slid_dis is None:
            slid_dis = make_sliders(col_dis_tuple)
        if lab_act is None:
            lab_act = make_lab(col_act_tuple)
        if lab_inact is None:
            lab_inact = make_lab(col_inact_tuple)

    return set_act, set_inact, slid_act, slid_inact, slid_dis, lab_act, lab_inact


def generate_tab_icons():
    """Returns ImageTk.PhotoImage pairs for Tkinter top navigation tabs."""
    g_act, g_inact, s_act, s_inact, _, l_act, l_inact = generate_tab_icons_pil(scale=1)
    return (
        ImageTk.PhotoImage(g_act),
        ImageTk.PhotoImage(g_inact),
        ImageTk.PhotoImage(s_act),
        ImageTk.PhotoImage(s_inact),
        ImageTk.PhotoImage(l_act),
        ImageTk.PhotoImage(l_inact),
    )


def generate_mode_icons_pil(size=(15, 15), scale: int = 4):
    """
    Renders supersampled PIL.Image RGBA icons for the calibration mode preset cards:
    - balanced: mode_balanced.svg (active: PlayStation Blue #00439C, inactive: Slate #64748B)
    - competitive: mode_competitive.svg (active: PlayStation Blue #00439C, inactive: Slate #64748B)
    - stable: mode_stable.svg / mode_.svg (active: PlayStation Blue #00439C, inactive: Slate #64748B)
    Returns dict: {pid: (pil_act, pil_inact)} rendered at size * scale.
    """
    base_dir = Path(__file__).resolve().parent

    def find_icon(name_candidates):
        for name in name_candidates:
            for parent in [base_dir.parent / "assets" / "icons", base_dir.parent / "assets", base_dir / "assets" / "icons", base_dir / "assets"]:
                p = parent / name
                if p.exists():
                    return p
        return None

    path_bal = find_icon(["mode_balanced.svg"])
    path_comp = find_icon(["mode_competitive.svg"])
    path_stable = find_icon(["mode_stable.svg", "mode_.svg"])

    col_act = "#00439C"
    col_inact = "#64748B"

    bal_act = render_svg_icon_pil(path_bal, size=size, color_hex=col_act, scale=scale)
    bal_inact = render_svg_icon_pil(path_bal, size=size, color_hex=col_inact, scale=scale)
    comp_act = render_svg_icon_pil(path_comp, size=size, color_hex=col_act, scale=scale)
    comp_inact = render_svg_icon_pil(path_comp, size=size, color_hex=col_inact, scale=scale)
    stab_act = render_svg_icon_pil(path_stable, size=size, color_hex=col_act, scale=scale)
    stab_inact = render_svg_icon_pil(path_stable, size=size, color_hex=col_inact, scale=scale)

    # Procedural fallbacks if SVGs are missing or fail to render
    w, h = size[0] * scale, size[1] * scale

    def make_fallback_star(col_tuple):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        cx, cy = w / 2, h / 2
        pts = [
            (cx, cy - h * 0.45),
            (cx + w * 0.12, cy - h * 0.12),
            (cx + w * 0.45, cy),
            (cx + w * 0.12, cy + h * 0.12),
            (cx, cy + h * 0.45),
            (cx - w * 0.12, cy + h * 0.12),
            (cx - w * 0.45, cy),
            (cx - w * 0.12, cy - h * 0.12),
        ]
        d.polygon(pts, fill=col_tuple)
        return img

    def make_fallback_lightning(col_tuple):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        pts = [
            (w * 0.55, h * 0.05),
            (w * 0.20, h * 0.52),
            (w * 0.48, h * 0.52),
            (w * 0.42, h * 0.95),
            (w * 0.80, h * 0.42),
            (w * 0.52, h * 0.42),
        ]
        d.polygon(pts, fill=col_tuple)
        return img

    def make_fallback_shield(col_tuple):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        pts = [
            (w * 0.50, h * 0.08),
            (w * 0.85, h * 0.22),
            (w * 0.85, h * 0.55),
            (w * 0.50, h * 0.92),
            (w * 0.15, h * 0.55),
            (w * 0.15, h * 0.22),
        ]
        d.polygon(pts, fill=col_tuple)
        return img

    col_act_tuple = (0, 67, 156, 255)
    col_inact_tuple = (100, 116, 139, 255)

    if bal_act is None:
        bal_act = make_fallback_star(col_act_tuple)
    if bal_inact is None:
        bal_inact = make_fallback_star(col_inact_tuple)
    if comp_act is None:
        comp_act = make_fallback_lightning(col_act_tuple)
    if comp_inact is None:
        comp_inact = make_fallback_lightning(col_inact_tuple)
    if stab_act is None:
        stab_act = make_fallback_shield(col_act_tuple)
    if stab_inact is None:
        stab_inact = make_fallback_shield(col_inact_tuple)

    return {
        "balanced": (bal_act, bal_inact),
        "competitive": (comp_act, comp_inact),
        "stable": (stab_act, stab_inact),
    }


def generate_mode_icons(size=(15, 15)):
    """Returns {pid: (act_photo, inact_photo)} for Tkinter."""
    pil_dict = generate_mode_icons_pil(size=size, scale=1)
    return {
        pid: (ImageTk.PhotoImage(act), ImageTk.PhotoImage(inact))
        for pid, (act, inact) in pil_dict.items()
    }


def generate_status_icons_pil(size=(38, 38), scale: int = 4):
    """
    Renders supersampled PIL.Image RGBA status badges for device connection status:
    1. Error: Red circular badge with a large, crisp X.
    2. OK: Green circular badge with a crisp checkmark.
    3. Warn: Amber circular badge with an exclamation mark.
    Returns (pil_err, pil_ok, pil_warn) rendered at size * scale.
    """
    w, h = size[0] * scale, size[1] * scale
    pad = int(1.5 * scale)
    cx, cy = w / 2, h / 2

    # 1. Error (Large X badge)
    img_err = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d_err = ImageDraw.Draw(img_err)
    d_err.ellipse([pad, pad, w - pad, h - pad], fill=(254, 226, 226, 255), outline=(252, 165, 165, 255), width=int(1.2 * scale))
    r = int(7.5 * scale)
    lw = int(3.2 * scale)
    d_err.line([(cx - r, cy - r), (cx + r, cy + r)], fill=(220, 38, 38, 255), width=lw)
    d_err.line([(cx - r, cy + r), (cx + r, cy - r)], fill=(220, 38, 38, 255), width=lw)
    cr = lw / 2.0
    for px, py in [(cx - r, cy - r), (cx + r, cy + r), (cx - r, cy + r), (cx + r, cy - r)]:
        d_err.ellipse([px - cr, py - cr, px + cr, py + cr], fill=(220, 38, 38, 255))
    pil_err = img_err if scale > 1 else img_err.resize(size, Image.Resampling.LANCZOS)

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
    pil_ok = img_ok if scale > 1 else img_ok.resize(size, Image.Resampling.LANCZOS)

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
    pil_warn = img_warn if scale > 1 else img_warn.resize(size, Image.Resampling.LANCZOS)

    return pil_err, pil_ok, pil_warn


def generate_status_icons(size=(38, 38)):
    """Returns ImageTk.PhotoImage status badges for Tkinter."""
    p_err, p_ok, p_warn = generate_status_icons_pil(size=size, scale=1)
    return (
        ImageTk.PhotoImage(p_err),
        ImageTk.PhotoImage(p_ok),
        ImageTk.PhotoImage(p_warn),
    )
