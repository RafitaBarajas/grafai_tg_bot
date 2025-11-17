import os
import io
import re
import logging
from typing import Tuple, Optional
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont
import requests

logger = logging.getLogger(__name__)


def _load_font(size: int = 24, family: Optional[str] = None) -> ImageFont.ImageFont:
    fonts_dir = os.path.join(os.path.dirname(__file__), "fonts")
    family_map = {
        "Montserrat": [
            "Montserrat-BlackItalic.ttf",
            "Montserrat-Black.ttf",
            "Montserrat-Bold.ttf",
            "Montserrat-Regular.ttf",
        ],
        "Rajdhani": [
            "Rajdhani-Bold.ttf",
            "Rajdhani-Regular.ttf",
        ],
    }

    if family and family in family_map:
        for fname in family_map[family]:
            path = os.path.join(fonts_dir, fname)
            if os.path.isfile(path):
                try:
                    return ImageFont.truetype(path, size=size)
                except Exception:
                    continue

    if family:
        generic = f"{family}.ttf"
        path = os.path.join(fonts_dir, generic)
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                pass

    try:
        return ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", size=size)
    except Exception:
        try:
            return ImageFont.truetype("arial.ttf", size=size)
        except Exception:
            return ImageFont.load_default()


def _get_text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> Tuple[int, int]:
    try:
        return font.getsize(text)
    except Exception:
        pass
    try:
        return draw.textsize(text, font=font)
    except Exception:
        pass
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])
    except Exception:
        return (len(text) * 6, 12)


def _normalize_card_code(code: str) -> Optional[str]:
    if not code:
        return None
    parts = code.split("-")
    if len(parts) < 2:
        return None
    if len(parts) == 2:
        set_id, local_id = parts[0], parts[1]
    elif len(parts) == 3:
        set_id = f"{parts[0]}-{parts[1]}"
        local_id = parts[2]
    else:
        return None
    try:
        local_id_padded = str(int(local_id)).zfill(3)
        return f"{set_id}-{local_id_padded}"
    except ValueError:
        logger.warning(f"Could not parse local ID from code: {code}")
        return None


def _fetch_card_image(code: str) -> Optional[Image.Image]:
    if not code:
        return None
    normalized_code = _normalize_card_code(code)
    if not normalized_code:
        logger.warning(f"Could not normalize card code: {code}")
        return None
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        api_url = f"https://api.tcgdex.net/v2/en/cards/{normalized_code}"
        r = requests.get(api_url, headers=headers, timeout=10)
        if r.status_code != 200:
            logger.warning(f"tcgdex API returned {r.status_code} for card code {code} (normalized: {normalized_code})")
            return None
        card_data = r.json()
        image_url = card_data.get("image")
        if not image_url:
            logger.warning(f"No image URL found for card code {code}")
            return None
        img_response = requests.get(f"{image_url}/high.png", headers=headers, timeout=10)
        if img_response.status_code == 200 and img_response.content:
            img = Image.open(io.BytesIO(img_response.content)).convert("RGBA")
            return img
        logger.warning(f"Failed to fetch image for {code} from {image_url}")
        return None
    except Exception as e:
        logger.error(f"Error fetching card image for code {code}: {e}")
        return None


def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _create_diagonal_gradient(size: Tuple[int, int], hex_colors: list) -> Image.Image:
    W, H = size
    L = W + H - 1
    stops = [_hex_to_rgb(c) for c in hex_colors]
    n = len(stops)
    positions = [int(i * (L - 1) / (n - 1)) for i in range(n)]
    gradient = [None] * L
    for si in range(n - 1):
        a_pos = positions[si]
        b_pos = positions[si+1]
        a_col = stops[si]
        b_col = stops[si+1]
        span = max(1, b_pos - a_pos)
        for i in range(span + 1):
            t = i / span
            r = int(a_col[0] + (b_col[0] - a_col[0]) * t)
            g = int(a_col[1] + (b_col[1] - a_col[1]) * t)
            b = int(a_col[2] + (b_col[2] - a_col[2]) * t)
            idx = a_pos + i
            if 0 <= idx < L:
                gradient[idx] = (r, g, b)
    last = stops[-1]
    for i in range(L):
        if gradient[i] is None:
            gradient[i] = last
    data = []
    for y in range(H):
        row_offset = y
        for x in range(W):
            idx = x + row_offset
            data.append(gradient[idx])
    img = Image.new("RGB", (W, H))
    img.putdata(data)
    return img.convert("RGBA")


def _background_for_set(set_code: str, size: Tuple[int, int]) -> Image.Image:
    gradient_hex = [
        "#fbe8ee",
        "#f6e0f7",
        "#e8defa",
        "#caecf6",
        "#caf4dc",
    ]
    return _create_diagonal_gradient(size, gradient_hex)


def _compute_primary_color_from_image_url(url: str) -> Optional[Tuple[int, int, int]]:
    if not url:
        return None
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url + ("/high.png" if not url.endswith(".png") and not url.endswith(".jpg") else ""), headers=headers, timeout=8)
        if r.status_code != 200:
            r = requests.get(url, headers=headers, timeout=8)
        if r.status_code != 200:
            return None
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        small = img.resize((1, 1))
        color = small.getpixel((0, 0))
        return (int(color[0]), int(color[1]), int(color[2]))
    except Exception as e:
        logger.warning(f"Could not compute color from image {url}: {e}")
        return None


def _select_representative_cards(deck_name: str, cards: list, limit: int = 2) -> list:
    if not cards:
        return []
    name = (deck_name or "").lower()
    raw_tokens = re.split(r"[^a-z0-9]+", name)
    tokens = [t for t in (tok.strip() for tok in raw_tokens) if len(t) >= 3]
    tokens_set = set(tokens)
    scored = []
    for c in cards:
        cname = (c.get("name", "") or "").lower()
        card_tokens = [t for t in re.split(r"[^a-z0-9]+", cname) if len(t) >= 3]
        score = 0
        if cname and cname in name:
            score += 5
        for t in card_tokens:
            if t in tokens_set:
                score += 1
        scored.append((score, int(c.get("qty", 0) or 0), c))
    scored_sorted = sorted(scored, key=lambda x: (x[0], x[1]), reverse=True)
    selected = [c for s, q, c in scored_sorted if s > 0][:limit]
    if len(selected) >= limit:
        return selected[:limit]
    remaining = [c for s, q, c in scored_sorted if c not in selected]
    for c in remaining:
        selected.append(c)
        if len(selected) >= limit:
            break
    return selected[:limit]


def _generate_front_page(set_info: dict) -> Optional[bytes]:
    W, H = 1400, 900
    bg = _background_for_set(set_info.get("id") if isinstance(set_info, dict) else "", (W, H))
    draw = ImageDraw.Draw(bg)
    title_font = _load_font(110, family="Montserrat")
    date_font = _load_font(44, family="Rajdhani")
    title = "Best Decks"
    date_s = datetime.utcnow().strftime("%B %d, %Y")
    logo_img = None
    logo_url = None
    if isinstance(set_info, dict):
        logo_url = set_info.get("logo") or set_info.get("symbol") or set_info.get("image")
    if logo_url:
        try:
            r = requests.get(logo_url + ("/high.png" if not logo_url.endswith((".png", ".jpg", ".jpeg")) else ""), timeout=8, headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code == 200 and r.content:
                logo_img = Image.open(io.BytesIO(r.content)).convert("RGBA")
                max_logo_w = int(W * 0.6)
                max_logo_h = int(H * 0.45)
                lw, lh = logo_img.size
                if lw == 0 or lh == 0:
                    pass
                else:
                    scale = min(max_logo_w / lw, max_logo_h / lh)
                    new_w = max(1, int(lw * scale))
                    new_h = max(1, int(lh * scale))
                    if (new_w, new_h) != (lw, lh):
                        logo_img = logo_img.resize((new_w, new_h), Image.LANCZOS)
        except Exception:
            logo_img = None
    title_cap = title.upper()
    date_cap = date_s.upper()
    tw, th = _get_text_size(draw, title_cap, title_font)
    dtw, dth = _get_text_size(draw, date_cap, date_font)
    lw = lh = 0
    if logo_img:
        lw, lh = logo_img.size
    spacing = 40
    logo_spacing = 36
    total_h = th + spacing + dth + (logo_spacing + lh if logo_img else 0)
    start_y = (H - total_h) // 2
    title_color = _hex_to_rgb('#eb1c24')
    draw.text(((W - tw) // 2, start_y), title_cap, font=title_font, fill=title_color, stroke_width=8, stroke_fill=(255,255,255))
    date_color = _hex_to_rgb('#3367b0')
    draw.text(((W - dtw) // 2, start_y + th + spacing), date_cap, font=date_font, fill=date_color, stroke_width=6, stroke_fill=(255,255,255))
    if logo_img:
        logo_x = (W - lw) // 2
        logo_y = start_y + th + spacing + dth + logo_spacing
        bg.paste(logo_img, (logo_x, logo_y), logo_img)
    buf = io.BytesIO()
    bg.convert("RGB").save(buf, format="JPEG", quality=90)
    buf.seek(0)
    return buf.getvalue()


def _generate_images_for_deck(deck: dict, position: int, set_code: str) -> Tuple[bytes, bytes]:
    W1, H1 = 1200, 700
    bg = _background_for_set(set_code, (W1, H1))
    draw = ImageDraw.Draw(bg)
    title_font = _load_font(48)
    big_font = _load_font(140)
    small_font = _load_font(22)
    if position <= 3:
        medal_path = f"images/medal_{position}.png"
        try:
            if os.path.exists(medal_path):
                medal_img = Image.open(medal_path).convert("RGBA")
                medal_img.thumbnail((120, 120))
                bg.paste(medal_img, (40, 30), medal_img)
            else:
                rank_text = str(position)
                draw.text((40, 30), rank_text, font=big_font, fill=(255, 255, 255))
        except Exception:
            rank_text = str(position)
            draw.text((40, 30), rank_text, font=big_font, fill=(255, 255, 255))
    else:
        rank_text = str(position)
        rank_font_styled = _load_font(120, family="Rajdhani")
        rank_color = _hex_to_rgb('#3367b0')
        left_margin = 40
        title_start_x = 220
        tw, th = _get_text_size(draw, rank_text, rank_font_styled)
        available_w = max(0, title_start_x - left_margin)
        x_pos = left_margin + max(0, (available_w - tw) // 2)
        y_pos = 30
        draw.text((x_pos, y_pos), rank_text, font=rank_font_styled, fill=rank_color, stroke_width=6, stroke_fill=(255,255,255))
    name = deck.get("name", "Unknown Deck")
    name_cap = name.upper()
    title_font_deck = _load_font(56, family="Montserrat")
    name_color = _hex_to_rgb('#eb1c24')
    draw.text((220, 60), name_cap, font=title_font_deck, fill=name_color, stroke_width=6, stroke_fill=(255,255,255))
    stats_text = f"Win Rate: {deck.get('win_pct', 0)}% • Share: {deck.get('share', 0)}%"
    stats_cap = stats_text.upper()
    stats_font = _load_font(32, family="Rajdhani")
    stats_color = _hex_to_rgb('#3367b0')
    draw.text((220, 130), stats_cap, font=stats_font, fill=stats_color, stroke_width=5, stroke_fill=(255,255,255))
    cards = deck.get("cards", []) or []
    reps = _select_representative_cards(name, cards, limit=2)
    x_offset = 220
    y_offset = 180
    for i, c in enumerate(reps):
        code = c.get("code", "")
        img = _fetch_card_image(code)
        if img:
            img_thumb = img.copy()
            img_thumb.thumbnail((320, 460))
            bg.paste(img_thumb, (x_offset + i * 360, y_offset), img_thumb)
        else:
            ph = Image.new("RGBA", (320, 460), (40, 40, 40))
            pd = ImageDraw.Draw(ph)
            pd.text((20, 20), c.get("name", ""), font=small_font, fill=(255, 255, 255))
            bg.paste(ph, (x_offset + i * 360, y_offset))
    buf1 = io.BytesIO()
    bg.convert("RGB").save(buf1, format="JPEG", quality=90)
    buf1.seek(0)
    W2 = 1200
    cols = 4
    card_spacing = 5
    thumb_target = (160, 160)
    total_grid_width = cols * thumb_target[0] + (cols - 1) * card_spacing
    count = len(cards)
    if count == 0:
        buf2 = io.BytesIO()
        deck_img = _background_for_set(set_code, (W2, 700))
        d2 = ImageDraw.Draw(deck_img)
        title2_cap = f"{position}. {name_cap}".upper()
        title2_font = _load_font(56, family="Montserrat")
        title2_color = _hex_to_rgb('#eb1c24')
        title_w, title_h = _get_text_size(d2, title2_cap, title2_font)
        title_x = (W2 - title_w) // 2
        d2.text((title_x, 30), title2_cap, font=title2_font, fill=title2_color, stroke_width=6, stroke_fill=(255,255,255))
        deck_img.convert("RGB").save(buf2, format="JPEG", quality=90)
        buf2.seek(0)
        return buf1.getvalue(), buf2.getvalue()
    rows = (count + cols - 1) // cols
    card_row_height = thumb_target[1] + card_spacing
    H2 = max(400, 120 + rows * card_row_height + 20)
    deck_img = _background_for_set(set_code, (W2, H2))
    d2 = ImageDraw.Draw(deck_img)
    title2_cap = f"{position}. {name_cap}".upper()
    title2_font = _load_font(56, family="Montserrat")
    title2_color = _hex_to_rgb('#eb1c24')
    title_w, title_h = _get_text_size(d2, title2_cap, title2_font)
    title_x = (W2 - title_w) // 2
    d2.text((title_x, 30), title2_cap, font=title2_font, fill=title2_color, stroke_width=6, stroke_fill=(255,255,255))
    y0 = 120
    for idx, c in enumerate(cards):
        r = idx // cols
        col = idx % cols
        x_base = (W2 - total_grid_width) // 2
        x = x_base + col * (thumb_target[0] + card_spacing)
        y = y0 + r * card_row_height
        code = c.get("code", "")
        img = _fetch_card_image(code)
        tw, th = thumb_target
        if img:
            thumb = img.copy()
            thumb.thumbnail(thumb_target)
            tw, th = thumb.size
            x_centered = x + (thumb_target[0] - tw) // 2
            deck_img.paste(thumb, (x_centered, y), thumb)
        else:
            ph = Image.new("RGBA", thumb_target, (40, 40, 40))
            x_centered = x + (thumb_target[0] - tw) // 2
            deck_img.paste(ph, (x_centered, y))
        qty = str(c.get("qty", 0))
        overlay_w, overlay_h = 54, 28
        ox = x_centered + tw - overlay_w - 6
        oy = y + th - overlay_h - 6
        d2.rectangle([ox, oy, ox + overlay_w, oy + overlay_h], fill=(0, 0, 0, 180))
        qty_font = _load_font(20)
        text_w, text_h = _get_text_size(d2, f"x{qty}", qty_font)
        tx = ox + (overlay_w - text_w) // 2
        ty = oy + (overlay_h - text_h) // 2 - 1
        d2.text((tx, ty), f"x{qty}", font=qty_font, fill=(255, 255, 255))
    buf2 = io.BytesIO()
    deck_img.convert("RGB").save(buf2, format="JPEG", quality=90)
    buf2.seek(0)
    return buf1.getvalue(), buf2.getvalue()
