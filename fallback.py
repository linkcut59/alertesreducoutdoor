"""Repli de lecture pour les pages sans données structurées JSON-LD (Ekosport, etc.).

Deux méthodes, essayées dans l'ordre :
  A. le JSON embarqué dans la page (Next.js, Nuxt...) : on y cherche des produits ;
  B. les cartes produit du HTML : un lien, une image et un ou deux prix en euros.
Si rien n'est trouvé, on affiche dans le journal ce que contient la page.
"""
import json
import re
from urllib.parse import urljoin

PRICE_RE = re.compile(r"(\d[\d\s\u00a0\u202f]*(?:[.,]\d{1,2})?)\s*(?:€|EUR)")
OLD_SELECTOR = (
    "s, del, strike, [class*=old], [class*=strike], [class*=before], [class*=barr], "
    "[class*=original], [class*=initial], [class*=was], [class*=regular]"
)

NAME_KEYS = ("name", "title", "label", "productName", "product_name")
URL_KEYS = ("url", "link", "href", "uri", "permalink", "productUrl", "product_url")
PRICE_KEYS = (
    "price", "salePrice", "sale_price", "sellingPrice", "finalPrice", "final_price",
    "currentPrice", "current_price", "specialPrice", "special_price", "minPrice",
)
OLD_KEYS = (
    "oldPrice", "old_price", "regularPrice", "regular_price", "originalPrice",
    "original_price", "strikePrice", "strikethroughPrice", "listPrice", "list_price",
    "msrp", "basePrice", "base_price", "initialPrice", "wasPrice", "crossedPrice",
    "recommendedPrice", "priceBeforeDiscount",
)
IMAGE_KEYS = ("image", "imageUrl", "image_url", "img", "thumbnail", "picture", "photo")


def _num(v):
    """Convertit un prix (nombre, texte « 1 299,90 € », dict {value: ..}) en float, ou None."""
    if isinstance(v, dict):
        v = v.get("value") or v.get("amount") or v.get("price")
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "")
    s = s.replace(",", ".")
    try:
        x = float(s)
    except ValueError:
        return None
    return x if x > 0 else None


def _prices_in_text(text):
    out = []
    for m in PRICE_RE.finditer(text):
        x = _num(m.group(1))
        if x:
            out.append(x)
    return out


def _first_str(v):
    if isinstance(v, str):
        return v
    if isinstance(v, list) and v:
        return _first_str(v[0])
    if isinstance(v, dict):
        return v.get("url") or v.get("src") or v.get("contentUrl") or ""
    return ""


def _pick(d, keys):
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return None


def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def _json_blocks(soup):
    blocks = []
    for tag in soup.find_all("script"):
        txt = (tag.string or tag.get_text() or "").strip()
        typ = (tag.get("type") or "").lower()
        if not txt or "ld+json" in typ:
            continue  # le JSON-LD est déjà traité par le robot
        if "json" in typ or tag.get("id") == "__NEXT_DATA__" or txt[:1] in "{[":
            try:
                blocks.append(json.loads(txt))
            except ValueError:
                continue
    return blocks


def _from_json(soup, base_url):
    found = {}
    blocks = _json_blocks(soup)
    for block in blocks:
        for d in _walk(block):
            name = _pick(d, NAME_KEYS)
            link = _pick(d, URL_KEYS)
            price = _num(_pick(d, PRICE_KEYS))
            if not (isinstance(name, str) and len(name.strip()) > 3 and isinstance(link, str) and price):
                continue
            strike = _num(_pick(d, OLD_KEYS))
            if strike and strike <= price:
                strike = None
            url = urljoin(base_url, link)
            image = _first_str(_pick(d, IMAGE_KEYS) or "")
            prev = found.get(url)
            if not prev or price < prev["price"]:
                found[url] = {
                    "name": name.strip(), "price": price, "strike": strike, "url": url,
                    "image": urljoin(base_url, image) if image else "",
                }
    return found, len(blocks)


def _card_title(node, anchor):
    img = node.find("img")
    if img and img.get("alt") and len(img["alt"].strip()) > 5:
        return img["alt"].strip()
    for tag in ("h2", "h3", "h4", "h5"):
        h = node.find(tag)
        if h and h.get_text(strip=True):
            return h.get_text(" ", strip=True)
    if anchor.get("title"):
        return anchor["title"].strip()
    return re.sub(r"\s+", " ", PRICE_RE.sub("", anchor.get_text(" ", strip=True))).strip()[:120]


def _card_image(node, base_url):
    img = node.find("img")
    if not img:
        return ""
    for attr in ("data-src", "data-original", "data-lazy-src", "src"):
        v = img.get(attr)
        if v and not v.startswith("data:"):
            return urljoin(base_url, v)
    srcset = img.get("srcset") or img.get("data-srcset")
    if srcset:
        return urljoin(base_url, srcset.split(",")[0].strip().split(" ")[0])
    return ""


def _from_cards(soup, base_url):
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        card, node = None, a
        for _ in range(5):
            if node is None or node.name in ("body", "html"):
                break
            if len({x["href"] for x in node.find_all("a", href=True)}) > 3:
                break  # conteneur trop grand : plusieurs produits mélangés
            if _prices_in_text(node.get_text(" ", strip=True)) and node.find("img"):
                card = node
                break
            node = node.parent
        if card is None:
            continue

        prices = sorted(set(_prices_in_text(card.get_text(" ", strip=True))))
        old = None
        for el in card.select(OLD_SELECTOR):
            vals = _prices_in_text(el.get_text(" ", strip=True))
            if vals:
                old = max(vals)
                break
        if old is None and len(prices) >= 2:
            old = prices[-1]  # sans balisage : le plus élevé est considéré comme l'ancien prix
        lower = [p for p in prices if old is None or p < old]
        if not lower:
            continue
        price = max(lower)  # on ignore les montants du type « économisez X € »
        strike = old if old and old > price else None
        if strike and not (5 <= round((1 - price / strike) * 100) <= 90):
            strike = None  # écart invraisemblable : on ne retient que le prix

        name = _card_title(card, a)
        if len(name) < 4 or price < 3:
            continue
        url = urljoin(base_url, href)
        prev = found.get(url)
        if not prev or price < prev["price"]:
            found[url] = {
                "name": name, "price": price, "strike": strike, "url": url,
                "image": _card_image(card, base_url),
            }
    return found


def extract_fallback(html, soup, url):
    """Renvoie {url_produit: {name, price, strike, url, image}} ; vide si rien n'est reconnu."""
    found, n_blocks = _from_json(soup, url)
    if found:
        print(f"[repli] {url} : {len(found)} produit(s) lus dans le JSON embarqué")
        return found
    found = _from_cards(soup, url)
    if found:
        print(f"[repli] {url} : {len(found)} produit(s) lus dans les cartes HTML")
        return found
    print(
        f"[repli] {url} : rien de reconnu ({len(html)} caractères reçus, "
        f"{html.count('€')} fois « € », {n_blocks} bloc(s) JSON, "
        f"{len(soup.find_all('img'))} image(s), {len(soup.find_all('a'))} lien(s))"
    )
    return {}
