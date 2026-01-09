import os
import io
import re
import unicodedata
import logging
from typing import Tuple, Optional
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont
import requests

logger = logging.getLogger(__name__)

# Cache for pokemon-tcg-pocket-database cards
_CARD_DB_CACHE = None
# Cache for pokemon-tcg-pocket-database sets
_SET_DB_CACHE = None


def _remove_bold_unicode(text: str) -> str:
    """Convert bold Unicode characters to regular ASCII equivalents.
    Handles Mathematical Alphanumeric Symbols (e.g., 𝗔𝘂𝗿𝗼𝗿𝗮 -> Aurora).
    """
    if not text:
        return text
    
    # Mapping of common bold Unicode characters to regular ASCII
    bold_to_regular = {
        # Uppercase bold letters (U+1D5D0 to U+1D5E9)
        '𝗔': 'A', '𝗕': 'B', '𝗖': 'C', '𝗗': 'D', '𝗘': 'E', '𝗙': 'F',
        '𝗚': 'G', '𝗛': 'H', '𝗜': 'I', '𝗝': 'J', '𝗞': 'K', '𝗟': 'L',
        '𝗠': 'M', '𝗡': 'N', '𝗢': 'O', '𝗣': 'P', '𝗤': 'Q', '𝗥': 'R',
        '𝗦': 'S', '𝗧': 'T', '𝗨': 'U', '𝗩': 'V', '𝗪': 'W', '𝗫': 'X',
        '𝗬': 'Y', '𝗭': 'Z',
        # Lowercase bold letters (U+1D5EA to U+1D603)
        '𝗮': 'a', '𝗯': 'b', '𝗰': 'c', '𝗱': 'd', '𝗲': 'e', '𝗳': 'f',
        '𝗴': 'g', '𝗵': 'h', '𝗶': 'i', '𝗷': 'j', '𝗸': 'k', '𝗹': 'l',
        '𝗺': 'm', '𝗻': 'n', '𝗼': 'o', '𝗽': 'p', '𝗾': 'q', '𝗿': 'r',
        '𝘀': 's', '𝘁': 't', '𝘂': 'u', '𝘃': 'v', '𝘄': 'w', '𝘅': 'x',
        '𝘆': 'y', '𝘇': 'z',
    }
    
    result = ""
    for char in text:
        result += bold_to_regular.get(char, char)
    
    return result


def _get_latest_set_code() -> Optional[str]:
    """Return the latest set code from the pocket-database `sets.json`.
    If the latest set has 'PROMO' in its code, return the previous set's code.
    """
    global _SET_DB_CACHE
    try:
        if _SET_DB_CACHE is None:
            logger.info("Loading pokemon-tcg-pocket-database sets.json...")
            sets_url = "https://raw.githubusercontent.com/flibustier/pokemon-tcg-pocket-database/main/dist/sets.json"
            r = requests.get(sets_url, timeout=20)
            if r.status_code != 200:
                logger.warning(f"Failed to load sets.json: {r.status_code}")
                _SET_DB_CACHE = []
                return None
            _SET_DB_CACHE = r.json()
            logger.info(f"Loaded {len(_SET_DB_CACHE)} sets from pocket-database")

        if not isinstance(_SET_DB_CACHE, list) or len(_SET_DB_CACHE) == 0:
            return None

        last = _SET_DB_CACHE[-1]
        code = (last.get('code') or '').strip()
        if code and 'PROMO' in code.upper():
            # Use previous set if available
            if len(_SET_DB_CACHE) >= 2:
                prev = _SET_DB_CACHE[-2]
                return (prev.get('code') or '').strip().upper()
            return None
        return code.upper() if code else None
    except Exception as e:
        logger.error(f"Error fetching latest set code: {e}")
        _SET_DB_CACHE = []
        return None


def _fetch_set_logo_image(set_code: str) -> Optional[Image.Image]:
    """Fetch the set logo image from pokemon-tcg-exchange given a set code.
    Filename pattern: LOGO_expansion_<SETCODE>_en_US.webp
    Tries .webp first, then .png as fallback.
    """
    if not set_code:
        return None
    headers = {"User-Agent": "Mozilla/5.0"}
    base = "https://raw.githubusercontent.com/flibustier/pokemon-tcg-exchange/main/public/images/sets"
    fname_webp = f"LOGO_expansion_{set_code.upper()}_en_US.webp"
    url_webp = f"{base}/{fname_webp}"
    try:
        r = requests.get(url_webp, headers=headers, timeout=12)
        if r.status_code == 200 and r.content:
            return Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception:
        pass
    # fallback to png
    try:
        fname_png = f"LOGO_expansion_{set_code.upper()}_en_US.png"
        url_png = f"{base}/{fname_png}"
        r2 = requests.get(url_png, headers=headers, timeout=12)
        if r2.status_code == 200 and r2.content:
            return Image.open(io.BytesIO(r2.content)).convert("RGBA")
    except Exception:
        pass
    logger.warning(f"Set logo not found in exchange repo for set {set_code}")
    return None


def _get_card_from_pocket_db(set_code: str, card_number: int) -> Optional[dict]:
    """Fetch card from pokemon-tcg-pocket-database and return the card object."""
    global _CARD_DB_CACHE
    try:
        if _CARD_DB_CACHE is None:
            logger.info("Loading pokemon-tcg-pocket-database cards.json...")
            db_url = "https://raw.githubusercontent.com/flibustier/pokemon-tcg-pocket-database/main/dist/cards.json"
            r = requests.get(db_url, timeout=30)
            if r.status_code != 200:
                logger.warning(f"Failed to load pokemon-tcg-pocket-database: {r.status_code}")
                _CARD_DB_CACHE = {}
                return None
            _CARD_DB_CACHE = r.json()
            logger.info(f"Loaded {len(_CARD_DB_CACHE)} cards from pokemon-tcg-pocket-database")
        
        # Normalize set code to uppercase (database uses uppercase, e.g., "B1A", "A1")
        set_code_upper = set_code.upper()
        
        # Search for matching card
        for card in _CARD_DB_CACHE:
            if card.get("set") == set_code_upper and card.get("number") == card_number:
                return card
        
        logger.warning(f"Card not found in database: set={set_code_upper}, number={card_number}")
        return None
    except Exception as e:
        logger.error(f"Error loading pokemon-tcg-pocket-database: {e}")
        _CARD_DB_CACHE = {}
        return None


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
                    font = ImageFont.truetype(path, size=size)
                    logger.debug(f"Loaded font from {path} with size {size}")
                    return font
                except Exception as e:
                    logger.debug(f"Failed to load {path}: {e}")
                    continue

    if family:
        generic = f"{family}.ttf"
        path = os.path.join(fonts_dir, generic)
        if os.path.isfile(path):
            try:
                font = ImageFont.truetype(path, size=size)
                logger.debug(f"Loaded font from {path} with size {size}")
                return font
            except Exception as e:
                logger.debug(f"Failed to load {path}: {e}")
                pass

    # Try system fonts on Linux/Raspberry Pi
    system_font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "arial.ttf",
    ]
    
    for font_path in system_font_paths:
        if os.path.isfile(font_path):
            try:
                font = ImageFont.truetype(font_path, size=size)
                logger.debug(f"Loaded fallback font from {font_path} with size {size}")
                return font
            except Exception as e:
                logger.debug(f"Failed to load {font_path}: {e}")
                continue
    
    logger.warning(f"No TrueType font found, falling back to default bitmap font")
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


def _apply_branding(img: Image.Image) -> Image.Image:
    """Paste the small grafai logo in the bottom-right and draw @grafai_ai beneath it."""
    try:
        logo_path = os.path.join(os.path.dirname(__file__), "images", "grafai_logo.png")
        if not os.path.isfile(logo_path):
            return img

        # ensure image is RGBA for alpha compositing
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        logo = Image.open(logo_path).convert("RGBA")
        img_w, img_h = img.size

        # scale logo to ~10% of image width, min 24px, max 160px
        target_logo_w = max(24, min(160, int(img_w * 0.10)))
        lw, lh = logo.size
        scale = float(target_logo_w) / float(lw) if lw > 0 else 1.0
        new_lw = max(1, int(lw * scale))
        new_lh = max(1, int(lh * scale))
        logo = logo.resize((new_lw, new_lh), Image.LANCZOS)
        lw, lh = logo.size

        # create a circular mask and white circular background (with small padding)
        pad = max(4, int(lw * 0.12))
        final_w = lw + pad
        final_h = lh + pad

        # circular background (white)
        bg_circle = Image.new("RGBA", (final_w, final_h), (0, 0, 0, 0))
        bg_draw = ImageDraw.Draw(bg_circle)
        bg_draw.ellipse((0, 0, final_w - 1, final_h - 1), fill=(255, 255, 255, 255))

        # circular logo: apply circular alpha mask to resized logo
        mask = Image.new("L", (lw, lh), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, lw - 1, lh - 1), fill=255)
        circ_logo = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
        circ_logo.paste(logo, (0, 0), mask)

        # composite: paste circ_logo centered over bg_circle
        offset_x = (final_w - lw) // 2
        offset_y = (final_h - lh) // 2
        bg_circle.paste(circ_logo, (offset_x, offset_y), circ_logo)

        final_logo = bg_circle

        margin = max(8, int(img_w * 0.02))

        draw = ImageDraw.Draw(img)
        # choose font size relative to image width
        font_size = max(10, int(img_w * 0.012))
        font = _load_font(font_size)
        text = "@grafai_ai"
        text_w, text_h = _get_text_size(draw, text, font)

        total_h = final_h + 4 + text_h
        logo_x = img_w - final_w - margin
        logo_y = img_h - margin - total_h

        # Paste circular logo with white background
        img.paste(final_logo, (logo_x, logo_y), final_logo)

        # Draw text centered under logo with slight stroke for readability
        text_x = logo_x + max(0, (final_w - text_w) // 2)
        text_y = logo_y + final_h + 4
        draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255), stroke_width=1, stroke_fill=(0, 0, 0))

        return img
    except Exception as e:
        logger.debug(f"_apply_branding failed: {e}")
        return img


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
    
    # Try tcgdex API first
    try:
        api_url = f"https://api.tcgdex.net/v2/en/cards/{normalized_code}"
        r = requests.get(api_url, headers=headers, timeout=10)
        if r.status_code == 200:
            card_data = r.json()
            image_url = card_data.get("image")
            if image_url:
                img_response = requests.get(f"{image_url}/high.png", headers=headers, timeout=10)
                if img_response.status_code == 200 and img_response.content:
                    img = Image.open(io.BytesIO(img_response.content)).convert("RGBA")
                    return img
    except Exception as e:
        logger.debug(f"tcgdex fetch failed for {code}: {e}")
    
    # Fallback: try pokemon-tcg-pocket-database + pokemon-tcg-exchange
    try:
        # Parse set code and card number from normalized code
        parts = normalized_code.split("-")
        if len(parts) >= 2:
            set_code = "-".join(parts[:-1])
            try:
                card_number = int(parts[-1])
            except ValueError:
                logger.warning(f"Could not parse card number from {normalized_code}")
                return None
            
            # Fetch card from pokemon-tcg-pocket-database
            card = _get_card_from_pocket_db(set_code, card_number)
            if card:
                image_name = card.get("imageName")
                if image_name:
                    # Construct URL from pokemon-tcg-exchange
                    exchange_url = f"https://raw.githubusercontent.com/flibustier/pokemon-tcg-exchange/main/public/images/cards/{image_name}"
                    logger.info(f"Fetching {code} from pokemon-tcg-exchange: {exchange_url}")
                    img_response = requests.get(exchange_url, headers=headers, timeout=10)
                    if img_response.status_code == 200 and img_response.content:
                        img = Image.open(io.BytesIO(img_response.content)).convert("RGBA")
                        return img
                    else:
                        logger.warning(f"Failed to fetch image from pokemon-tcg-exchange: {exchange_url} (status: {img_response.status_code})")
    except Exception as e:
        logger.debug(f"Fallback fetch failed for {code}: {e}")
    
    logger.warning(f"Could not fetch image for card code {code}")
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
    # Increase date font size for better visibility
    date_font = _load_font(56, family="Rajdhani")
    title = "Best Decks"
    date_s = datetime.utcnow().strftime("%B %d, %Y")
    logo_img = None
    # Prefer to fetch the logo for the latest set from the pocket-database / exchange repo
    latest_set_code = _get_latest_set_code()
    if latest_set_code:
        try:
            logo_img = _fetch_set_logo_image(latest_set_code)
            if logo_img:
                # make cover logo a bit smaller
                max_logo_w = int(W * 0.45)
                max_logo_h = int(H * 0.35)
                lw, lh = logo_img.size
                if lw and lh:
                    scale = min(max_logo_w / lw, max_logo_h / lh)
                    new_w = max(1, int(lw * scale))
                    new_h = max(1, int(lh * scale))
                    if (new_w, new_h) != (lw, lh):
                        logo_img = logo_img.resize((new_w, new_h), Image.LANCZOS)
        except Exception:
            logo_img = None
    else:
        # Fallback: try any logo/url present in set_info
        logo_url = None
        if isinstance(set_info, dict):
            logo_url = set_info.get("logo") or set_info.get("symbol") or set_info.get("image")
        if logo_url:
            try:
                r = requests.get(logo_url + ("/high.png" if not logo_url.endswith((".png", ".jpg", ".jpeg")) else ""), timeout=8, headers={"User-Agent":"Mozilla/5.0"})
                if r.status_code == 200 and r.content:
                    logo_img = Image.open(io.BytesIO(r.content)).convert("RGBA")
                    # smaller fallback sizing for cover
                    max_logo_w = int(W * 0.45)
                    max_logo_h = int(H * 0.35)
                    lw, lh = logo_img.size
                    if lw and lh:
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
    # apply branding before saving
    try:
        bg = _apply_branding(bg)
    except Exception:
        pass
    bg.convert("RGB").save(buf, format="JPEG", quality=90)
    buf.seek(0)
    return buf.getvalue()


def _generate_listing_pages(decks: list, set_info: dict = None, per_page: int = 5) -> list:
    """Generate one or more listing images containing up to `per_page` decks each.
    Each page includes title, date, and for each deck: rank (medal for top3), name, stats,
    and up to 2 representative card images.
    Returns a list of JPEG bytes for each page.
    """
    pages = []
    if not decks:
        return pages

    W, H = 1400, 900
    title_font = _load_font(64, family="Montserrat")
    date_font = _load_font(28, family="Rajdhani")
    name_font = _load_font(32, family="Montserrat")
    stats_font = _load_font(20, family="Rajdhani")

    total = len(decks)
    for start in range(0, total, per_page):
        batch = decks[start:start+per_page]
        bg = _background_for_set(set_info.get("id") if isinstance(set_info, dict) else "", (W, H))
        draw = ImageDraw.Draw(bg)

        # Header (centered) with optional set logo on the left of the title/date stack
        title = "Best Decks"
        date_s = datetime.utcnow().strftime("%B %d, %Y").upper()
        title_cap = title.upper()

        # compute title/date sizes
        tw, th = _get_text_size(draw, title_cap, title_font)
        date_font_bigger = _load_font(36, family="Rajdhani")
        dtw, dth = _get_text_size(draw, date_s, date_font_bigger)

        # Try to load a set logo (prefer set_info id, else latest set)
        logo_img = None
        try:
            set_code = set_info.get("id") if isinstance(set_info, dict) else None
            if set_code:
                logo_img = _fetch_set_logo_image(set_code)
            if not logo_img:
                latest = _get_latest_set_code()
                if latest:
                    logo_img = _fetch_set_logo_image(latest)
            # fallback to explicit url fields in set_info
            if not logo_img and isinstance(set_info, dict):
                logo_url = set_info.get("logo") or set_info.get("symbol") or set_info.get("image")
                if logo_url:
                    try:
                        r = requests.get(logo_url + ("/high.png" if not logo_url.endswith((".png", ".jpg", ".jpeg")) else ""), timeout=8, headers={"User-Agent":"Mozilla/5.0"})
                        if r.status_code == 200 and r.content:
                            logo_img = Image.open(io.BytesIO(r.content)).convert("RGBA")
                    except Exception:
                        logo_img = None
        except Exception:
            logo_img = None

        logo_w = logo_h = 0
        if logo_img:
            # make logo a little bigger and constrain it to a larger portion of header
            max_logo_h = max(1, int((th + 12 + dth) * 1.9))
            max_logo_w = int(W * 0.44)
            lw, lh = logo_img.size
            if lw and lh:
                scale = min(max_logo_w / lw, max_logo_h / lh)
                new_w = max(1, int(lw * scale))
                new_h = max(1, int(lh * scale))
                if (new_w, new_h) != (lw, lh):
                    logo_img = logo_img.resize((new_w, new_h), Image.LANCZOS)
            logo_w, logo_h = logo_img.size

        # increase separation between title/date and logo and place logo to the right
        padding_between = 120
        stack_w = max(tw, dtw)
        content_w = (stack_w + padding_between + logo_w) if logo_img else stack_w
        start_x = (W - content_w) // 2

        # draw title/date on the left of the header block
        text_x = start_x
        draw.text((text_x + (stack_w - tw) // 2, 40), title_cap, font=title_font, fill=_hex_to_rgb('#eb1c24'), stroke_width=6, stroke_fill=(255,255,255))
        draw.text((text_x + (stack_w - dtw) // 2, 40 + th + 12), date_s, font=date_font_bigger, fill=_hex_to_rgb('#3367b0'), stroke_width=3, stroke_fill=(255,255,255))

        # paste logo to the right of title/date if present and vertically center it with the text stack
        if logo_img:
            logo_x = text_x + stack_w + padding_between
            stack_top = 40
            stack_height = th + 12 + dth
            text_center_y = stack_top + (stack_height // 2)
            logo_y = (text_center_y // 2) - (stack_height // 2) + 12
            bg.paste(logo_img, (logo_x, logo_y), logo_img)

        # header height should accommodate taller logo if present
        header_h = max(stack_top + stack_height + 20, stack_top + logo_h + 20)

        # Grid layout: 3 on top row, 2 on bottom row, centered horizontally
        card_w, card_h = 160, 240
        card_gap = 10
        item_w = card_w * 2 + card_gap
        item_h = card_h + 72  # space for rank icon/number above
        top_cols = 3
        bottom_cols = 2
        row_gap = 22

        top_total_w = top_cols * item_w + (top_cols - 1) * 40
        bottom_total_w = bottom_cols * item_w + (bottom_cols - 1) * 40

        top_start_x = (W - top_total_w) // 2
        bottom_start_x = (W - bottom_total_w) // 2

        # move items slightly down to add more space beneath header
        vertical_offset = -30
        top_y = header_h + vertical_offset
        bottom_y = header_h + vertical_offset + item_h + row_gap

        for idx, deck in enumerate(batch):
            pos = start + idx + 1
            # determine row/col
            if idx < 3:
                row_x = top_start_x
                col = idx
                y0 = top_y
            else:
                row_x = bottom_start_x
                col = idx - 3
                y0 = bottom_y

            x0 = row_x + col * (item_w + 40)
            # draw rank (medal or number) centered at top of item
            try:
                if pos <= 3:
                    medal_path = os.path.join(os.path.dirname(__file__), "images", f"medal_{pos}.png")
                    if os.path.exists(medal_path):
                        medal_img = Image.open(medal_path).convert("RGBA")
                        medal_img.thumbnail((64, 64))
                        mx = x0 + (item_w - medal_img.size[0]) // 2
                        my = y0
                        bg.paste(medal_img, (mx, my), medal_img)
                    else:
                        # show numeric rank with '#' prefix when icon missing
                        rtext = f"#{pos}"
                        rfont = _load_font(36, family="Rajdhani")
                        rtw, rth = _get_text_size(draw, rtext, rfont)
                        rx = x0 + (item_w - rtw) // 2
                        ry = y0 + 8
                        draw.text((rx, ry), rtext, font=rfont, fill=_hex_to_rgb('#3367b0'), stroke_width=3, stroke_fill=(255,255,255))
                else:
                    # positions without medal: prefix with '#'
                    rtext = f"#{pos}"
                    rfont = _load_font(36, family="Rajdhani")
                    rtw, rth = _get_text_size(draw, rtext, rfont)
                    rx = x0 + (item_w - rtw) // 2
                    ry = y0 + 8
                    draw.text((rx, ry), rtext, font=rfont, fill=_hex_to_rgb('#3367b0'), stroke_width=3, stroke_fill=(255,255,255))
            except Exception:
                rfont = _load_font(36, family="Rajdhani")
                rtw, rth = _get_text_size(draw, str(pos), rfont)
                rx = x0 + (item_w - rtw) // 2
                ry = y0 + 8
                draw.text((rx, ry), str(pos), font=rfont, fill=_hex_to_rgb('#3367b0'), stroke_width=3, stroke_fill=(255,255,255))

            # draw two representative cards centered in item below the rank
            reps = _select_representative_cards(deck.get('name',''), deck.get('cards',[]) or [], limit=2)
            cards_x = x0
            cards_y = y0 + 56
            for ci in range(2):
                cx = cards_x + ci * (card_w + card_gap)
                if ci < len(reps):
                    code = reps[ci].get('code','')
                    try:
                        img = _fetch_card_image(code)
                    except Exception:
                        img = None
                    if img:
                        thumb = img.copy()
                        thumb.thumbnail((card_w, card_h))
                        tw, th = thumb.size
                        x_center = cx + (card_w - tw) // 2
                        y_center = cards_y + (card_h - th) // 2
                        bg.paste(thumb, (x_center, y_center), thumb)
                    else:
                        ph = Image.new('RGBA', (card_w, card_h), (40,40,40))
                        pd = ImageDraw.Draw(ph)
                        pd.text((8, 8), reps[ci].get('name',''), font=_load_font(16), fill=(255,255,255))
                        bg.paste(ph, (cx, cards_y))
                else:
                    ph = Image.new('RGBA', (card_w, card_h), (40,40,40))
                    bg.paste(ph, (cx, cards_y))

        try:
            bg = _apply_branding(bg)
        except Exception:
            pass

        buf = io.BytesIO()
        bg.convert('RGB').save(buf, format='JPEG', quality=90)
        buf.seek(0)
        pages.append(buf.getvalue())

    return pages


def _generate_back_cover(set_info: dict = None) -> Optional[bytes]:
    """Generate a simple back cover image that says 'Follow for Meta Updates'."""
    W, H = 1400, 900
    set_code = set_info.get("id") if isinstance(set_info, dict) else ""
    bg = _background_for_set(set_code, (W, H))
    draw = ImageDraw.Draw(bg)

    # Render the main phrase in two centered lines, large and auto-fitting
    lines = ["Follow for", "Meta Updates"]
    # attempt a large starting size then decrease until both lines fit within margins
    max_font_size = int(W * 0.14)
    min_font_size = 28
    margin_x = int(W * 0.08)
    chosen_font = _load_font(72, family="Montserrat")
    for fs in range(max_font_size, min_font_size, -2):
        f = _load_font(fs, family="Montserrat")
        fits = True
        widths = []
        heights = []
        for ln in lines:
            w, h = _get_text_size(draw, ln.upper(), f)
            widths.append(w)
            heights.append(h)
            if w > (W - margin_x * 2):
                fits = False
                break
        if fits:
            chosen_font = f
            break

    # compute total height and draw each line centered
    upper_lines = [ln.upper() for ln in lines]
    line_sizes = [_get_text_size(draw, ln, chosen_font) for ln in upper_lines]
    total_h = sum(h for w, h in line_sizes) + (len(lines) - 1) * 12
    start_y = (H - total_h) // 2
    for idx, ln in enumerate(upper_lines):
        w, h = line_sizes[idx]
        x = (W - w) // 2
        y = start_y + sum(line_sizes[i][1] for i in range(idx)) + idx * 12
        draw.text((x, y), ln, font=chosen_font, fill=_hex_to_rgb('#ffffff'), stroke_width=6, stroke_fill=(0, 0, 0))

    # Apply branding
    try:
        bg = _apply_branding(bg)
    except Exception:
        pass

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
    try:
        bg = _apply_branding(bg)
    except Exception:
        pass
    bg.convert("RGB").save(buf1, format="JPEG", quality=90)
    buf1.seek(0)
    # Create the grid (secondary) image via helper so callers can request only grid image
    buf2_bytes = _generate_deck_grid_image(cards, position, name_cap, set_code)
    return buf1.getvalue(), buf2_bytes


def _generate_deck_grid_image(cards: list, position: int, name_cap: str, set_code: str, win_pct=None, share_pct=None, place=None, score=None) -> bytes:
    """Generate only the deck grid image (title + stats + grid of cards).
    Designed to use more width and 5 columns per row.
    """
    W2 = 1400
    cols = 5
    card_spacing = 6
    thumb_target = (160, 160)
    total_grid_width = cols * thumb_target[0] + (cols - 1) * card_spacing
    count = len(cards)

    if count == 0:
        buf2 = io.BytesIO()
        deck_img = _background_for_set(set_code, (W2, 700))
        d2 = ImageDraw.Draw(deck_img)
        # Sanitize title to remove problematic control/special characters and bold Unicode
        try:
            title_safe = _remove_bold_unicode(name_cap)
            title_safe = re.sub(r"[\x00-\x1F\x7F\|\[\]<>]", "", title_safe)
        except Exception:
            title_safe = name_cap
        title2_cap = f"{position}. {title_safe}".upper()
        title2_font = _load_font(48, family="Montserrat")
        title2_color = _hex_to_rgb('#eb1c24')
        title_w, title_h = _get_text_size(d2, title2_cap, title2_font)
        title_x = (W2 - title_w) // 2
        d2.text((title_x, 30), title2_cap, font=title2_font, fill=title2_color, stroke_width=6, stroke_fill=(255,255,255))
        # Stats: prefer place/score if provided
        stats_text = None
        if place or score:
            parts = []
            if place:
                parts.append(f"Place: {place}")
            if score:
                parts.append(f"Score: {score}")
            stats_text = " • ".join(parts).upper()
            try:
                stats_font = _load_font(28, family='Rajdhani')
                stw, sth = _get_text_size(d2, stats_text, stats_font)
                d2.text(((W2 - stw) // 2, 30 + title_h + 12), stats_text, font=stats_font, fill=_hex_to_rgb('#3367b0'), stroke_width=3, stroke_fill=(255,255,255))
                y0 = 30 + title_h + 12 + sth + 12
            except Exception:
                y0 = 30 + title_h + 12 + 20
        else:
            y0 = 30 + title_h + 12 + 20
        try:
            deck_img = _apply_branding(deck_img)
        except Exception:
            pass
        deck_img.convert("RGB").save(buf2, format="JPEG", quality=90)
        buf2.seek(0)
        return buf2.getvalue()

    rows = (count + cols - 1) // cols
    card_row_height = thumb_target[1] + card_spacing
    H2 = max(420, 140 + rows * card_row_height + 40)
    deck_img = _background_for_set(set_code, (W2, H2))
    d2 = ImageDraw.Draw(deck_img)

    # Title (sanitize name to avoid unsupported glyphs and bold Unicode)
    try:
        title_safe = _remove_bold_unicode(name_cap)
        title_safe = re.sub(r"[\x00-\x1F\x7F\|\[\]<>]", "", title_safe)
    except Exception:
        title_safe = name_cap
    title2_cap = f"{position}. {title_safe}".upper()
    title2_font = _load_font(48, family="Montserrat")
    title2_color = _hex_to_rgb('#eb1c24')
    title_w, title_h = _get_text_size(d2, title2_cap, title2_font)
    title_x = (W2 - title_w) // 2
    d2.text((title_x, 16), title2_cap, font=title2_font, fill=title2_color, stroke_width=6, stroke_fill=(255,255,255))

    # Stats line centered below title
    # Expect deck dict info to be passed separately; name_cap includes position and name
    # We'll attempt to read win/share from a card in context is not available here, so caller should pass stats via cards attr or change signature
    # As a compromise, if the first card dict has 'deck_stats' key we use it; otherwise caller should use _generate_images_for_deck which still does older behaviour.
    # For compatibility, we try to read stats from a sentinel in cards list (not present normally). If not found, skip stats.
    stats_text = None
    # add stats line centered below title if provided
    extra_top_padding = 24
    title_stats_gap = 24
    # Stats line: prefer place/score if provided, otherwise fallback to win/share
    if place or score:
        parts = []
        if place:
            parts.append(f"Place: {place}")
        if score:
            parts.append(f"Score: {score}")
        stats_text = " • ".join(parts).upper()
        stats_font = _load_font(28, family='Rajdhani')
        stw, sth = _get_text_size(d2, stats_text, stats_font)
        d2.text(((W2 - stw) // 2, 16 + title_h + title_stats_gap), stats_text, font=stats_font, fill=_hex_to_rgb('#3367b0'), stroke_width=3, stroke_fill=(255,255,255))
        y0 = 16 + title_h + title_stats_gap + sth + 12 + extra_top_padding
    elif win_pct is not None or share_pct is not None:
        stats_text = f"Win: {win_pct or 0}% • Share: {share_pct or 0}%".upper()
        stats_font = _load_font(28, family='Rajdhani')
        stw, sth = _get_text_size(d2, stats_text, stats_font)
        d2.text(((W2 - stw) // 2, 16 + title_h + title_stats_gap), stats_text, font=stats_font, fill=_hex_to_rgb('#3367b0'), stroke_width=3, stroke_fill=(255,255,255))
        y0 = 16 + title_h + title_stats_gap + sth + 12 + extra_top_padding
    else:
        y0 = 16 + title_h + title_stats_gap + 20 + extra_top_padding

    # Draw grid of cards centered
    x_base = (W2 - total_grid_width) // 2
    for idx, c in enumerate(cards):
        r = idx // cols
        col = idx % cols
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
        # render qty as larger text with semi-thick black outline (no black rectangle)
        qty_font = _load_font(24)
        qtext = f"x{qty}"
        text_w, text_h = _get_text_size(d2, qtext, qty_font)
        tx = x_centered + tw - text_w - 8
        ty = y + th - text_h - 8
        d2.text((tx, ty), qtext, font=qty_font, fill=(255,255,255), stroke_width=3, stroke_fill=(0,0,0))

    buf2 = io.BytesIO()
    try:
        deck_img = _apply_branding(deck_img)
    except Exception:
        pass
    deck_img.convert("RGB").save(buf2, format="JPEG", quality=90)
    buf2.seek(0)
    return buf2.getvalue()

def _generate_deck_info_image(name: str, position: int, win_pct: float, share_pct: float, cards: list, set_code: str) -> bytes:
    """
    Generate a deck info image (cover) with:
    - Medal image (for 1-3) or number (for others) at top, centered
    - Deck name (bold, centered)
    - 2 most representative cards (bottom, reduced spacing)
    Uses same styling as listing pages.
    """
    W, H = 1000, 900
    bg = _background_for_set(set_code, (W, H))
    draw = ImageDraw.Draw(bg)
    
    # Medal image for position 1-3, otherwise numeric rank
    medal_img = None
    medal_size = 80
    medal_y = 30
    
    if position <= 3:
        try:
            medal_path = os.path.join(os.path.dirname(__file__), "images", f"medal_{position}.png")
            if os.path.exists(medal_path):
                medal_img = Image.open(medal_path).convert("RGBA")
                medal_img.thumbnail((medal_size, medal_size))
        except Exception:
            pass
    
    # If no medal image, draw number with # prefix
    if medal_img:
        medal_x = (W - medal_img.size[0]) // 2
        bg.paste(medal_img, (medal_x, medal_y), medal_img)
        name_start_y = medal_y + medal_size + 15
    else:
        # Draw numeric position like listing pages
        pos_font = _load_font(60, family="Rajdhani")
        pos_text = f"#{position}"
        pos_w, pos_h = _get_text_size(draw, pos_text, pos_font)
        draw.text(
            ((W - pos_w) // 2, medal_y + 8),
            pos_text,
            font=pos_font,
            fill=_hex_to_rgb('#3367b0'),
            stroke_width=3,
            stroke_fill=(255, 255, 255)
        )
        name_start_y = medal_y + 80 + 15
    
    # Deck name (large, bold, centered) - use same style as listing pages
    name_font = _load_font(52, family="Montserrat")
    name_w, name_h = _get_text_size(draw, name, name_font)
    draw.text(
        ((W - name_w) // 2, name_start_y),
        name,
        font=name_font,
        fill=(255, 255, 255),
        stroke_width=4,
        stroke_fill=(0, 0, 0)
    )
    
    # Get 2 representative cards
    representative_cards = _select_representative_cards(name, cards, limit=2)
    
    if representative_cards:
        # Card size and positioning - reduced spacing between name and cards
        card_width = 230
        card_height = 330
        card_y = name_start_y + name_h + 30  # Reduced spacing
        
        if len(representative_cards) == 1:
            # Center single card
            card_x = (W - card_width) // 2
            card_urls = [representative_cards[0].get('code', '')]
            positions = [(card_x, card_y)]
        else:
            # Two cards side by side
            spacing = 50
            total_width = 2 * card_width + spacing
            start_x = (W - total_width) // 2
            card_urls = [representative_cards[0].get('code', ''), representative_cards[1].get('code', '')]
            positions = [(start_x, card_y), (start_x + card_width + spacing, card_y)]
        
        # Fetch and draw card images
        for card_code, (card_x, card_y) in zip(card_urls, positions):
            try:
                card_img = _fetch_card_image(card_code)
                if card_img:
                    # Resize card to fit
                    card_img.thumbnail((card_width, card_height), Image.LANCZOS)
                    cw, ch = card_img.size
                    # Center it in the allocated space
                    paste_x = card_x + (card_width - cw) // 2
                    paste_y = card_y + (card_height - ch) // 2
                    if card_img.mode == 'RGBA':
                        bg.paste(card_img, (paste_x, paste_y), card_img)
                    else:
                        bg.paste(card_img, (paste_x, paste_y))
            except Exception:
                pass
    
    # Convert to JPEG and return
    buf = io.BytesIO()
    try:
        bg = _apply_branding(bg)
    except Exception:
        pass
    bg.convert("RGB").save(buf, format="JPEG", quality=90)
    buf.seek(0)
    return buf.getvalue()