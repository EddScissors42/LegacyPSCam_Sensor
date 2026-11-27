"""
High-Resolution Anti-Aliased Icon and Pill Generators for Legacy PSCam Sensor UI.
Renders supersampled Pillow graphics for sidebar navigation, top tabs, and rounded buttons
for Qt 6 / PySide6.
Loads custom user SVG icons for 'settings' (Video Settings) and 'trackingicon' (Tracking) with vector fallback.
"""
import math
from pathlib import Path
from PIL import Image, ImageDraw


def make_pill_image(w: int, h: int, fill, outline=None, radius: int = 12):
    """Generates an anti-aliased rounded rectangle pill PIL.Image."""
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
    return img.resize((w, h), Image.Resampling.LANCZOS)


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


def load_ds4_file_icon(img_path: Path, target_box=(38, 26), color=(255, 255, 255), scale: int = 4):
    """
    Loads officialdualshock.png (or dualshock4.jpg), isolates graphic to transparent alpha,
    recolors the controller graphic to target color, and scales it into target_box * scale.
    """
    if not img_path or not Path(img_path).exists():
        return None
    try:
        import numpy as np
        im = Image.open(img_path).convert("RGBA")
        arr = np.array(im)
        corner_lum = 0.299 * arr[0, 0, 0] + 0.587 * arr[0, 0, 1] + 0.114 * arr[0, 0, 2]
        if corner_lum < 100:
            # Dark background (officialdualshock.png)
            lum = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
            alpha = np.clip((lum - 15) / (180 - 15) * 255, 0, 255).astype(np.uint8)
        else:
            # Light background (dualshock4.jpg)
            gray = np.array(im.convert("L"))
            inv = 255 - gray
            alpha = np.clip((inv.astype(float) - 15) / (180 - 15) * 255, 0, 255).astype(np.uint8)

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

        bw, bh = target_box[0] * scale, target_box[1] * scale
        fit_scale = min(bw / cropped.width, bh / cropped.height) * 0.78
        new_w = max(1, int(cropped.width * fit_scale))
        new_h = max(1, int(cropped.height * fit_scale))
        resized = cropped.resize((new_w, new_h), Image.Resampling.LANCZOS)

        canvas = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        canvas.paste(resized, ((bw - new_w) // 2, (bh - new_h) // 2))
        return canvas
    except Exception as e:
        print(f"[WARN] Failed to process {img_path}: {e}")
        return None


def generate_ds4_icons_pil(target_box=(38, 26), scale: int = 4):
    """
    Renders supersampled PIL.Image RGBA icons for the DualShock 4 sidebar navigation card.
    Loads officialdualshock.png with vector/jpg fallback.
    Returns (pil_ds4_act, pil_ds4_inact) rendered at target_box * scale.
    """
    base_dir = Path(__file__).resolve().parent
    candidates = [
        base_dir.parent / "assets" / "icons" / "officialdualshock.png",
        base_dir.parent / "assets" / "officialdualshock.png",
        base_dir / "assets" / "icons" / "officialdualshock.png",
        base_dir / "assets" / "officialdualshock.png",
    ]
    img_path = next((p for p in candidates if p.exists()), None)

    ds4_act = load_ds4_file_icon(img_path, target_box=target_box, color=(255, 255, 255), scale=scale)
    ds4_inact = load_ds4_file_icon(img_path, target_box=target_box, color=(0, 67, 156), scale=scale)

    if ds4_act is None or ds4_inact is None:
        w, h = target_box[0] * scale, target_box[1] * scale

        def make_gamepad(col):
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            # Controller body pill
            d.rounded_rectangle([int(w * 0.16), int(h * 0.24), int(w * 0.84), int(h * 0.72)],
                                radius=int(5 * scale), fill=col)
            # Left grip
            d.rounded_rectangle([int(w * 0.16), int(h * 0.42), int(w * 0.36), int(h * 0.88)],
                                radius=int(3 * scale), fill=col)
            # Right grip
            d.rounded_rectangle([int(w * 0.64), int(h * 0.42), int(w * 0.84), int(h * 0.88)],
                                radius=int(3 * scale), fill=col)
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

    # 2. Webcam Icon from webcam.svg (with vector fallback)
    webcam_svg_candidates = [
        base_dir.parent / "assets" / "icons" / "webcam.svg",
        base_dir.parent / "assets" / "webcam.svg",
        base_dir / "assets" / "icons" / "webcam.svg",
        base_dir / "assets" / "webcam.svg",
    ]
    webcam_svg_path = next((p for p in webcam_svg_candidates if p.exists()), None)

    web_act_pil = render_svg_icon_pil(webcam_svg_path, size=target_box, color_hex="#FFFFFF", scale=scale) if webcam_svg_path else None
    web_inact_pil = render_svg_icon_pil(webcam_svg_path, size=target_box, color_hex="#00439C", scale=scale) if webcam_svg_path else None

    if web_act_pil is None or web_inact_pil is None:
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


def generate_icons(target_box=(38, 26), scale: int = 4):
    """Alias for generate_icons_pil returning supersampled PIL.Image icons."""
    return generate_icons_pil(target_box=target_box, scale=scale)


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

        from PySide6.QtCore import QRectF
        d_size = ren.defaultSize()
        if d_size.isValid() and d_size.width() > 0 and d_size.height() > 0:
            scale_fit = min(pw / d_size.width(), ph / d_size.height()) * 0.85
            draw_w = d_size.width() * scale_fit
            draw_h = d_size.height() * scale_fit
            draw_x = (pw - draw_w) / 2.0
            draw_y = (ph - draw_h) / 2.0
            ren.render(p, QRectF(draw_x, draw_y, draw_w, draw_h))
        else:
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
    2. Tracking SVG icon for 'Tracking' (active, inactive, & disabled)
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

    tracking_candidates = [
        base_dir.parent / "assets" / "icons" / "trackingicon.svg",
        base_dir.parent / "assets" / "trackingicon.svg",
        base_dir / "assets" / "icons" / "trackingicon.svg",
        base_dir / "assets" / "trackingicon.svg",
    ]
    tracking_path = next((p for p in tracking_candidates if p.exists()), None)

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
    slid_act = render_svg_icon_pil(tracking_path, size=size, color_hex=col_act, scale=scale)
    slid_inact = render_svg_icon_pil(tracking_path, size=size, color_hex=col_inact, scale=scale)
    slid_dis = render_svg_icon_pil(tracking_path, size=size, color_hex=col_disabled, scale=scale)
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

        def make_tracking_target(color):
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            lw = max(2, int(1.8 * scale))
            # 4 Corners for tracking viewfinder target
            m = int(2.5 * scale)
            corner_len = int(4.5 * scale)
            # Top-left
            d.line([(m, m), (m + corner_len, m)], fill=color, width=lw)
            d.line([(m, m), (m, m + corner_len)], fill=color, width=lw)
            # Top-right
            d.line([(w - m, m), (w - m - corner_len, m)], fill=color, width=lw)
            d.line([(w - m, m), (w - m, m + corner_len)], fill=color, width=lw)
            # Bottom-left
            d.line([(m, h - m), (m + corner_len, h - m)], fill=color, width=lw)
            d.line([(m, h - m), (m, h - m - corner_len)], fill=color, width=lw)
            # Bottom-right
            d.line([(w - m, h - m), (w - m - corner_len, h - m)], fill=color, width=lw)
            d.line([(w - m, h - m), (w - m, h - m - corner_len)], fill=color, width=lw)
            # Center crosshair
            cx, cy = w // 2, h // 2
            ch_len = int(3.5 * scale)
            d.line([(cx - ch_len, cy), (cx + ch_len, cy)], fill=color, width=lw)
            d.line([(cx, cy - ch_len), (cx, cy + ch_len)], fill=color, width=lw)
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
            slid_act = make_tracking_target(col_act_tuple)
        if slid_inact is None:
            slid_inact = make_tracking_target(col_inact_tuple)
        if slid_dis is None:
            slid_dis = make_tracking_target(col_dis_tuple)
        if lab_act is None:
            lab_act = make_lab(col_act_tuple)
        if lab_inact is None:
            lab_inact = make_lab(col_inact_tuple)

    return set_act, set_inact, slid_act, slid_inact, slid_dis, lab_act, lab_inact


def generate_tab_icons(size=(18, 18), scale: int = 4):
    """Alias for generate_tab_icons_pil returning supersampled PIL.Image tab icons."""
    return generate_tab_icons_pil(size=size, scale=scale)


def generate_mode_icons_pil(size=(15, 15), scale: int = 4):
    """
    Renders supersampled PIL.Image RGBA icons strictly from SVG assets present in `assets/icons/`:
    - performance (and legacy 'competitive' alias): mode_competitive.svg
    - balanced: mode_balanced.svg
    - high: mode_high.svg (returns (None, None) when absent — no invented fallback)
    - custom: mode_custom.svg (returns (None, None) when absent — no invented fallback)
    Returns dict: {pid: (pil_act_or_None, pil_inact_or_None)} rendered at size * scale.
    """
    base_dir = Path(__file__).resolve().parent

    def find_icon(name_candidates):
        for name in name_candidates:
            for parent in [base_dir.parent / "assets" / "icons", base_dir.parent / "assets", base_dir / "assets" / "icons", base_dir / "assets"]:
                p = parent / name
                if p.exists():
                    return p
        return None

    col_act = "#00439C"
    col_inact = "#64748B"

    def load_pair(name_candidates):
        svg_path = find_icon(name_candidates)
        if svg_path is None:
            return None, None
        return (
            render_svg_icon_pil(svg_path, size=size, color_hex=col_act, scale=scale),
            render_svg_icon_pil(svg_path, size=size, color_hex=col_inact, scale=scale),
        )

    perf_pair = load_pair(["mode_performance.svg", "mode_competitive.svg"])
    bal_pair = load_pair(["mode_balanced.svg"])
    high_pair = load_pair(["mode_high.svg"])
    custom_pair = load_pair(["mode_custom.svg"])

    return {
        "performance": perf_pair,
        "balanced": bal_pair,
        "high": high_pair,
        "custom": custom_pair,
        "competitive": perf_pair,
    }


def generate_mode_icons(size=(15, 15), scale: int = 4):
    """Alias for generate_mode_icons_pil returning {pid: (pil_act, pil_inact)}."""
    return generate_mode_icons_pil(size=size, scale=scale)


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


def generate_phone_cam_icons_pil(target_box=(38, 26), scale: int = 4):
    """
    Renders supersampled PIL.Image RGBA icons for the 'Phone Camera' sidebar navigation card.
    Loads assets/icons/phone.svg using render_svg_icon_pil with crisp supersampling,
    falling back to procedural vector smartphone silhouette if the SVG cannot be rendered.
    Returns (pil_phone_act, pil_phone_inact) rendered at target_box * scale.
    """
    base_dir = Path(__file__).resolve().parent
    phone_svg_candidates = [
        base_dir.parent / "assets" / "icons" / "phone.svg",
        base_dir.parent / "assets" / "phone.svg",
        base_dir / "assets" / "icons" / "phone.svg",
        base_dir / "assets" / "phone.svg",
    ]
    phone_svg_path = next((p for p in phone_svg_candidates if p.exists()), None)

    phone_act = render_svg_icon_pil(phone_svg_path, size=target_box, color_hex="#FFFFFF", scale=scale) if phone_svg_path else None
    phone_inact = render_svg_icon_pil(phone_svg_path, size=target_box, color_hex="#00439C", scale=scale) if phone_svg_path else None

    if phone_act is None or phone_inact is None:
        w, h = target_box[0] * scale, target_box[1] * scale

        def make_phone_icon(fg_col, cutout_col):
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            # Smartphone vertical body
            px0, py0 = int(w * 0.24), int(h * 0.06)
            px1, py1 = int(w * 0.64), int(h * 0.94)
            d.rounded_rectangle([px0, py0, px1, py1], radius=int(3.2 * scale), fill=fg_col)

            # Screen / camera lens aperture
            cx = (px0 + px1) // 2
            cy = int(h * 0.46)
            r_outer = int(4.2 * scale)
            r_inner = int(2.0 * scale)
            d.ellipse([cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer], fill=cutout_col)
            d.ellipse([cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner], fill=fg_col)

            # Bottom home bar indicator
            hb_w = int(3.5 * scale)
            hb_y = int(h * 0.82)
            d.line([(cx - hb_w, hb_y), (cx + hb_w, hb_y)], fill=cutout_col, width=max(1, int(1.3 * scale)))

            # Wireless signal arcs on the right side of the phone
            wx = int(w * 0.66)
            wy = int(h * 0.50)
            lw = max(1, int(1.6 * scale))
            for r_arc in (int(4.5 * scale), int(8.0 * scale)):
                bbox = [wx - r_arc, wy - r_arc, wx + r_arc, wy + r_arc]
                d.arc(bbox, start=-42, end=42, fill=fg_col, width=lw)
            return img

        if phone_act is None:
            phone_act = make_phone_icon((255, 255, 255, 255), (0, 67, 156, 255))
        if phone_inact is None:
            phone_inact = make_phone_icon((0, 67, 156, 255), (221, 240, 247, 255))

    return phone_act, phone_inact


def generate_reload_icon_pil(size=(15, 15), scale: int = 4):
    """
    Renders supersampled PIL.Image RGBA icons for reload/refresh buttons across the UI.
    Loads assets/icons/reload.svg tinted in PlayStation Blue (active) and Muted Slate (disabled),
    with a crisp vector arc fallback if the SVG cannot be rendered.
    Returns (pil_reload_act, pil_reload_disabled) rendered at size * scale.
    """
    base_dir = Path(__file__).resolve().parent
    svg_candidates = [
        base_dir.parent / "assets" / "icons" / "reload.svg",
        base_dir.parent / "assets" / "reload.svg",
        base_dir / "assets" / "icons" / "reload.svg",
        base_dir / "assets" / "reload.svg",
    ]
    svg_path = next((p for p in svg_candidates if p.exists()), None)

    reload_act = render_svg_icon_pil(svg_path, size=size, color_hex="#00439C", scale=scale) if svg_path else None
    reload_dis = render_svg_icon_pil(svg_path, size=size, color_hex="#94A3B8", scale=scale) if svg_path else None

    if reload_act is None or reload_dis is None:
        w, h = size[0] * scale, size[1] * scale

        def make_reload(col):
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            pad = int(w * 0.16)
            lw = max(2, int(2.0 * scale))
            d.arc([pad, pad, w - pad, h - pad], start=35, end=330, fill=col, width=lw)
            return img

        if reload_act is None:
            reload_act = make_reload((0, 67, 156, 255))
        if reload_dis is None:
            reload_dis = make_reload((148, 163, 184, 255))

    return reload_act, reload_dis


def generate_status_icons(size=(38, 38), scale: int = 4):
    """Alias for generate_status_icons_pil returning supersampled PIL.Image status badges."""
    return generate_status_icons_pil(size=size, scale=scale)
