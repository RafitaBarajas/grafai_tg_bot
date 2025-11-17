# ...existing code...
import requests
import json
import re
import html as _html
from bs4 import BeautifulSoup
from typing import Any, Dict, List, Optional


def _find_decks_in_obj(obj: Any, game_key: str = "pocket") -> Optional[List[Dict]]:
    """
    Recursively search a deserialized JSON-like object for a list of deck dicts
    that look like decks (contain 'name' and 'cards') and optionally match game_key.
    """
    if isinstance(obj, dict):
        # Common shape: { 'game': 'pocket', 'decks': [...] }
        if "decks" in obj and isinstance(obj["decks"], list):
            decks = obj["decks"]
            # If there's an associated game key, prefer items that match it
            if any(isinstance(obj.get("game"), str) and obj.get("game").lower() == game_key for _ in [0]):
                return decks
            # Otherwise return if items look like decks
            if all(isinstance(d, dict) and "name" in d and "cards" in d for d in decks):
                return decks
        # Recurse
        for v in obj.values():
            found = _find_decks_in_obj(v, game_key)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_decks_in_obj(item, game_key)
            if found:
                return found
    return None


def _extract_json_candidates(html: str) -> List[str]:
    """
    Return likely JSON string candidates embedded in the page for further parsing.
    """
    candidates: List[str] = []

    # Next.js common embed (very useful if present)
    m = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(\{.*\})</script>', html, re.S | re.I)
    if m:
        candidates.append(m.group(1))

    # Any <script type="application/json">...</script> blocks (often used for preloaded props)
    for mm in re.finditer(r'<script[^>]+type=["\']application/json["\'][^>]*>(\{.*?\})</script>', html, re.S | re.I):
        candidates.append(mm.group(1))

    # Generic window.<ANY> = {...}; or var NAME = {...};
    for name in ("__INITIAL_STATE__", "__PRELOADED_STATE__", "window.__INITIAL_STATE__", "window.__PRELOADED_STATE__"):
        pattern = re.compile(re.escape(name) + r"\s*=\s*(\{.*?\});", re.S)
        for mm in pattern.finditer(html):
            candidates.append(mm.group(1))

    # Generic var/const assignment patterns that look JSON-like (heuristic)
    for mm in re.finditer(r'(?:var|let|const)\s+[A-Za-z0-9_]+\s*=\s*(\{\s*\"?decks\"?.*?\});', html, re.S):
        candidates.append(mm.group(1))

    # Inline JSON arrays/objects labeled "decks"
    for mm in re.finditer(r'("decks"\s*:\s*)(\[\s*\{.*?\}\s*\])', html, re.S):
        candidates.append(mm.group(2))

    # As a last-ditch: look for large JSON-like blocks inside any <script> tag and include if they mention 'decks'
    for mm in re.finditer(r'<script[^>]*>(\{[\s\S]{50,50000}?\})</script>', html, re.S | re.I):
        body = mm.group(1)
        if 'decks' in body:
            candidates.append(body)

    # de-duplicate while preserving order
    seen = set()
    out = []
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def _find_api_endpoints(html: str, base_url: str = "https://play.limitlesstcg.com") -> List[str]:
    """Look for fetch()/axios XHR endpoints in scripts that contain 'deck' or 'decks'. Return absolute URLs where possible."""
    urls: List[str] = []
    # fetch('...') or fetch("...")
    for m in re.finditer(r"fetch\(\s*([\'\"])(.*?)\1", html, re.S | re.I):
        u = m.group(2)
        if 'deck' in u.lower():
            if u.startswith('http'):
                urls.append(u)
            else:
                urls.append(base_url.rstrip('/') + '/' + u.lstrip('/'))

    # axios.get('...') or axios.post('...')
    for m in re.finditer(r"axios\.(?:get|post)\(\s*([\'\"])(.*?)\1", html, re.S | re.I):
        u = m.group(2)
        if 'deck' in u.lower():
            if u.startswith('http'):
                urls.append(u)
            else:
                urls.append(base_url.rstrip('/') + '/' + u.lstrip('/'))

    # look for plain API-like paths in the page: "/api/decks" or "/decks/api"
    for m in re.finditer(r"([\"'])(/api/[^\"']*decks[^\"']*)\1", html, re.I):
        urls.append(base_url.rstrip('/') + m.group(2))

    # dedupe preserving order
    out = []
    seen = set()
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _normalize_deck(d: Dict) -> Dict:
    """
    Normalize a raw deck dict to required output fields.
    """
    name = d.get("name") or d.get("title") or d.get("deckName") or ""
    # win_pct and share may be strings like "52.34%" or numbers
    def parse_pct(x):
        if x is None:
            return 0.0
        if isinstance(x, str):
            x = x.strip().rstrip("%")
            try:
                return round(float(x), 2)
            except Exception:
                return 0.0
        try:
            return round(float(x), 2)
        except Exception:
            return 0.0

    win_pct = parse_pct(d.get("win_pct") or d.get("winPercent") or d.get("win") or d.get("winrate"))
    share = parse_pct(d.get("share") or d.get("metaShare") or d.get("percentage") or d.get("usage"))

    cards_raw = d.get("cards") or d.get("list") or d.get("cardsList") or []
    cards_out = []
    for c in cards_raw:
        if isinstance(c, dict):
            cname = c.get("name") or c.get("cardName") or ""
            code = c.get("code") or c.get("id") or c.get("cardId") or ""
            qty = c.get("qty") or c.get("quantity") or c.get("count") or 0
            try:
                qty = int(qty)
            except Exception:
                qty = 0
            cards_out.append({"name": cname, "code": code, "qty": qty})
        elif isinstance(c, (list, tuple)) and len(c) >= 2:
            # maybe [qty, "Card Name (CODE)"]
            try:
                qty = int(c[0])
            except Exception:
                qty = 0
            cards_out.append({"name": str(c[1]), "code": "", "qty": qty})
        else:
            # unknown shape, skip
            continue

    return {"name": name, "win_pct": round(win_pct, 2), "share": round(share, 2), "cards": cards_out}


def get_top_10_decks() -> Dict:
    """
    Fetch https://play.limitlesstcg.com/decks?game=pocket and return top 10 decks
    in the format:
    { 'set': string, 'decks': [ { 'name': string, 'win_pct': 2-decimal float,
      'share': 2-decimal float, 'cards': [ { 'name': string, 'code': string, 'qty': int }, ... ] }, ... ] }
    """
    url = "https://play.limitlesstcg.com/decks?game=pocket"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    html = resp.text

    # Attempt 1: parse embedded JSON candidates
    candidates = _extract_json_candidates(html)
    decks_found = None
    # ensure meta_set always exists (may be filled from parsed JSON or later enrichment)
    meta_set = ""
    for cand in candidates:
        try:
            parsed = json.loads(cand)
        except Exception:
            # try to find a JSON substring (sometimes trailing semicolons or JS comments exist)
            try:
                parsed = json.loads(re.sub(r'//.*?\n', '', cand))
            except Exception:
                parsed = None
        if parsed is None:
            continue
        decks = _find_decks_in_obj(parsed, game_key="pocket")
        if decks:
            decks_found = decks
            # try to extract set metadata if present
            meta_set = parsed.get("set") if isinstance(parsed, dict) else None
            break

    # Attempt 2: try to parse HTML for deck items (fallback)
    if decks_found is None:
        soup = BeautifulSoup(html, "html.parser")
        # try common item selectors
        items = soup.select(".deck-card, .deck, .deck-item, .deck-row")
        parsed_decks = []
        for it in items:
            # Extract name
            name_tag = it.select_one(".deck-title, .title, .name")
            name = name_tag.get_text(strip=True) if name_tag else it.get("data-name") or it.get("title") or ""
            # win% and share
            def find_pct(sel):
                t = it.select_one(sel)
                if not t:
                    return None
                txt = t.get_text(strip=True).strip().rstrip("%")
                try:
                    return float(txt)
                except Exception:
                    return None
            win_pct = find_pct(".win, .win-rate, .win_pct")
            share = find_pct(".share, .meta-share, .usage")
            # cards - try list elements
            cards = []
            for li in it.select("li.card, .card-row, .deck-card-row"):
                text = li.get_text(" ", strip=True)
                # try "3x Pikachu (SM1 35)" or "Pikachu (SM1 35) x3"
                m = re.match(r"(\d+)\s*[xX]\s*(.+)", text)
                if m:
                    qty = int(m.group(1))
                    rest = m.group(2)
                    code_m = re.search(r"\(([^)]+)\)\s*$", rest)
                    code = code_m.group(1) if code_m else ""
                    name = re.sub(r"\s*\([^)]+\)\s*$", "", rest).strip()
                    cards.append({"name": name, "code": code, "qty": qty})
                else:
                    # fallback: try quantity at end
                    m2 = re.match(r"(.+?)\s+(\d+)$", text)
                    if m2:
                        name = m2.group(1).strip()
                        qty = int(m2.group(2))
                        cards.append({"name": name, "code": "", "qty": qty})
            parsed_decks.append({"name": name, "win_pct": round(win_pct or 0.0, 2), "share": round(share or 0.0, 2), "cards": cards})
        if parsed_decks:
            decks_found = parsed_decks
            meta_set = None

    # Additional HTML fallback: the page may render a table of decks where each <tr>
    # contains data-share and data-winrate attributes and a link to the deck detail.
    if decks_found is None:
        # Look for rows that include deck links and data attributes
        rows = soup.select("tr[data-share], tr[data-winrate]")
        table_decks = []
        base = "https://play.limitlesstcg.com"
        for r in rows:
            a = r.select_one("a[href^='/decks/']")
            if not a:
                continue
            href = a.get('href')
            deck_name = a.get_text(strip=True)
            # read data attributes first
            try:
                win_pct = float(r.get('data-winrate') or r.get('data-win') or 0.0) * 100.0
            except Exception:
                win_pct = None
            try:
                share = float(r.get('data-share') or r.get('data-usage') or 0.0) * 100.0
            except Exception:
                share = None

            # Try to fetch the deck detail page and extract cards
            cards = []
            try:
                dr = requests.get(base.rstrip('/') + href, headers=headers, timeout=10)
                if dr.status_code == 200:
                    dsoup = BeautifulSoup(dr.text, 'html.parser')
                    # common selectors for deck detail lists
                    card_nodes = dsoup.select('li.card, .card-row, .deck-card-row, .deck-list li, .deck-cards li')
                    for cn in card_nodes:
                        text = cn.get_text(' ', strip=True)
                        m = re.match(r"(\d+)\s*[xX]?\s*(.+)", text)
                        if m:
                            qty = int(m.group(1))
                            rest = m.group(2)
                            code_m = re.search(r"\(([^)]+)\)\s*$", rest)
                            code = code_m.group(1) if code_m else ""
                            name_only = re.sub(r"\s*\([^)]*\)\s*$", '', rest).strip()
                            cards.append({'name': name_only, 'code': code, 'qty': qty})
                    # as fallback, look for pre or code blocks with card lists
                    if not cards:
                        for pre in dsoup.select('pre, code'):
                            txt = pre.get_text('\n')
                            for line in txt.splitlines():
                                line = line.strip()
                                mm = re.match(r"(\d+)\s*[xX]?\s*(.+)", line)
                                if mm:
                                    try:
                                        q = int(mm.group(1))
                                    except Exception:
                                        q = 0
                                    rest = mm.group(2)
                                    code_m = re.search(r"\(([^)]+)\)\s*$", rest)
                                    code = code_m.group(1) if code_m else ""
                                    name_only = re.sub(r"\s*\([^)]*\)\s*$", '', rest).strip()
                                    cards.append({'name': name_only, 'code': code, 'qty': q})
                    # If still empty, the deck detail page often links to tournament-specific
                    # decklist pages (e.g. /tournament/<id>/player/<name>/decklist). Follow the
                    # first such link and try to extract the card list there.
                    if not cards:
                        dl_link = None
                        for a in dsoup.select("a[href*='/tournament/'][href$='/decklist']"):
                            href2 = a.get('href')
                            if href2:
                                dl_link = href2
                                break
                        if dl_link:
                            try:
                                r2 = requests.get(base.rstrip('/') + dl_link, headers=headers, timeout=10)
                                if r2.status_code == 200:
                                    dlsoup = BeautifulSoup(r2.text, 'html.parser')
                                    # Preferred: the hidden input[name='input'] contains a JSON array
                                    # with count/name/set/number entries (HTML-escaped). Use that.
                                    inp = dlsoup.select_one("input[name='input']")
                                    parsed_cards = []
                                    if inp and inp.has_attr('value'):
                                        raw = inp['value']
                                        try:
                                            raw_unescaped = _html.unescape(raw)
                                            parsed = json.loads(raw_unescaped)
                                            for itc in parsed:
                                                try:
                                                    qty = int(itc.get('count', 0))
                                                except Exception:
                                                    qty = 0
                                                name = itc.get('name', '')
                                                set_code = itc.get('set', '')
                                                number = itc.get('number', '')
                                                code = f"{set_code}-{number}" if set_code or number else ''
                                                parsed_cards.append({'name': name, 'code': code, 'qty': qty})
                                        except Exception:
                                            parsed_cards = []
                                    # Fallback: some decklist pages define a JS string 'decklist' with lines
                                    if not parsed_cards:
                                        scr = dlsoup.find('script', string=re.compile(r'const\s+decklist\s*=', re.I))
                                        if scr and scr.string:
                                            s = scr.string
                                            m = re.search(r'const\s+decklist\s*=\s*`([^`]*)`', s, re.S)
                                            if m:
                                                text_blob = m.group(1)
                                                for line in text_blob.splitlines():
                                                    line = line.strip()
                                                    if not line:
                                                        continue
                                                    mm = re.match(r"(\d+)\s+(.*)\s+([A-Za-z0-9-]+)\s+([0-9]+)$", line)
                                                    if mm:
                                                        qty = int(mm.group(1))
                                                        name = mm.group(2).strip()
                                                        set_code = mm.group(3).strip()
                                                        number = mm.group(4).strip()
                                                        code = f"{set_code}-{number}"
                                                        parsed_cards.append({'name': name, 'code': code, 'qty': qty})
                                    # Use parsed_cards if found
                                    if parsed_cards:
                                        cards = parsed_cards
                            except Exception:
                                pass
            except Exception:
                # ignore and keep an empty card list
                pass

            table_decks.append({
                'name': deck_name,
                'win_pct': round(win_pct or 0.0, 2),
                'share': round(share or 0.0, 2),
                'cards': cards
            })
            if len(table_decks) >= 10:
                break

        if table_decks:
            decks_found = table_decks
            meta_set = None

    # Attempt 3: If still not found, discover XHR/API endpoints referenced in scripts and try them
    if decks_found is None:
        endpoints = _find_api_endpoints(html)
        for ep in endpoints:
            try:
                r = requests.get(ep, headers=headers, timeout=12)
                r.raise_for_status()
                try:
                    parsed = r.json()
                except Exception:
                    # sometimes API returns { data: '...json...' }
                    try:
                        parsed = json.loads(r.text)
                    except Exception:
                        parsed = None
                if parsed:
                    decks = _find_decks_in_obj(parsed, game_key="pocket")
                    if decks:
                        decks_found = decks
                        meta_set = parsed.get("set") if isinstance(parsed, dict) else None
                        break
            except Exception:
                # ignore and try the next endpoint
                continue

    if decks_found is None:
        raise RuntimeError("Could not find deck data on the page. Page structure may have changed or data is loaded dynamically via JS.")

    # Normalize and pick top 10
    normalized = []
    for d in decks_found[:10]:
        # if raw dict try normalization, otherwise assume already normalized-ish
        if isinstance(d, dict) and ("cards" in d and "name" in d):
            normalized.append(_normalize_deck(d))
        else:
            # skip invalid shapes
            continue

    # Attempt to enrich 'set' with the latest series info from tcgdex (tcgp series)
    try:
        series_url = "https://api.tcgdex.net/v2/en/series/tcgp"
        sr = requests.get(series_url, headers=headers, timeout=8)
        if sr.status_code == 200:
            series = sr.json()
            # series may be a dict with keys like 'lastSet' and 'sets'
            if isinstance(series, dict):
                last_set = series.get("lastSet") or None
                if last_set:
                    meta_set = last_set
                else:
                    # fallback: if 'sets' array exists, take its last element
                    sets = series.get("sets")
                    if isinstance(sets, list) and len(sets) > 0:
                        meta_set = sets[-1]
            elif isinstance(series, list) and len(series) > 0:
                latest = series[-1]
                meta_set = latest
    except Exception:
        # ignore enrichment failures and keep existing meta_set
        pass

    # Normalize meta_set into a stable dict shape: {id,name,logo}
    set_out = {}
    if isinstance(meta_set, dict):
        set_out = {
            "id": meta_set.get("id") or meta_set.get("code") or meta_set.get("name") or "",
            "name": meta_set.get("name") or meta_set.get("id") or "",
            "logo": f"{meta_set.get('logo')}.png" or f"{meta_set.get('symbol')}.png" or meta_set.get("image") or "",
        }
    elif isinstance(meta_set, str) and meta_set:
        set_out = {"id": meta_set, "name": meta_set, "logo": ""}
    else:
        set_out = {"id": "", "name": "", "logo": ""}

    result = {"set": set_out, "decks": normalized[:10]}
    return result


if __name__ == "__main__":
    import pprint
    try:
        out = get_top_10_decks()
        pprint.pprint(out)
    except Exception as e:
        print("Error:", e)
# ...existing code...