"""Robot de surveillance des prix outdoor.

Lit docs/data/watchlist.json, visite chaque page (fiche produit ou page de catégorie),
relève les prix, tient l'historique et publie les bonnes affaires dans docs/data/deals.json.
Une alerte part quand :
  - le prix baisse d'au moins `seuil` % par rapport au prix habituel (médiane des 30 derniers jours),
  - ou le site affiche lui-même un prix barré avec au moins `seuil` % de remise,
  - ou le prix passe sous le `plafond` en euros.
"""
import datetime as dt
import hashlib
import json
import os
import random
import re
import statistics
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
WATCH, HIST, DEALS, STATUS, CONFIG = (DATA / f for f in
    ("watchlist.json", "history.json", "deals.json", "status.json", "config.json"))

TODAY = dt.date.today().isoformat()
NOW = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
REF_DAYS = 30          # fenêtre du « prix habituel »
MIN_POINTS = 3         # jours de relevés minimum avant de comparer à l'historique
HIST_DAYS = 120        # historique conservé
MAX_DEALS = 300
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
SHOPS = {
    "snowleader": "Snowleader", "ekosport": "Ekosport", "alltricks": "Alltricks",
    "i-run": "i-Run", "auvieuxcampeur": "Au Vieux Campeur", "decathlon": "Decathlon",
    "glisshop": "Glisshop", "lepape": "Lepape", "intersport": "Intersport",
    "go-sport": "Go Sport", "trekkinn": "Trekkinn", "bergfreunde": "Bergfreunde",
}


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def shop_name(url):
    host = urlparse(url).netloc.lower().replace("www.", "")
    for k, v in SHOPS.items():
        if k in host:
            return v
    return host.split(".")[0].capitalize()


def to_price(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if re.search(r",\d{1,2}$", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        x = float(s)
        return x if x > 0 else None
    except ValueError:
        return None


# ---------- extraction ----------
def jsonld(soup):
    for tag in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        txt = tag.string or tag.get_text() or ""
        try:
            yield json.loads(txt, strict=False)
        except json.JSONDecodeError:
            continue


def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


def types(d):
    t = d.get("@type", [])
    return set(t if isinstance(t, list) else [t])


def first_str(v):
    if isinstance(v, str):
        return v
    if isinstance(v, list) and v:
        return first_str(v[0])
    if isinstance(v, dict):
        return v.get("url") or v.get("contentUrl") or v.get("name") or ""
    return ""


def read_offers(offers):
    """Renvoie (prix le plus bas en stock, prix barré éventuel)."""
    prices, strike = [], None
    for o in walk(offers):
        t = types(o)
        if not t & {"Offer", "AggregateOffer"} and "price" not in o and "lowPrice" not in o:
            continue
        avail = str(o.get("availability", "")).lower()
        if "outofstock" in avail or "soldout" in avail:
            continue
        p = to_price(o.get("lowPrice") if "AggregateOffer" in t else o.get("price"))
        if p is None:
            spec = o.get("priceSpecification")
            for s in walk(spec or []):
                if "strikethrough" not in str(s.get("priceType", "")).lower():
                    p = p or to_price(s.get("price"))
        if p:
            prices.append(p)
        for s in walk(o.get("priceSpecification") or []):
            pt = str(s.get("priceType", "")).lower()
            if "strikethrough" in pt or "listprice" in pt or "msrp" in pt:
                sp = to_price(s.get("price"))
                if sp:
                    strike = max(strike or 0, sp)
    return (min(prices) if prices else None), strike


def extract(html, url):
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for block in jsonld(soup):
        for d in walk(block):
            if not types(d) & {"Product", "ProductModel"} or "offers" not in d:
                continue
            price, strike = read_offers(d["offers"])
            if not price:
                continue
            purl = urljoin(url, first_str(d.get("url")) or first_str(d.get("offers", {}).get("url") if isinstance(d.get("offers"), dict) else "") or url)
            name = (d.get("name") or "").strip()
            brand = first_str(d.get("brand")) if d.get("brand") else ""
            if brand and brand.lower() not in name.lower():
                name = f"{brand} {name}"
            key = d.get("sku") or d.get("productID") or purl.split("?")[0] + "|" + name
            p = found.get(key)
            if not p or price < p["price"]:
                found[key] = {"name": name, "price": price, "strike": strike, "url": purl,
                              "image": urljoin(url, first_str(d.get("image"))) if d.get("image") else ""}
    if not found:  # repli : balises meta / microdonnées
        def meta(*names):
            for n in names:
                t = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n}) \
                    or soup.find(attrs={"itemprop": n})
                if t:
                    return t.get("content") or t.get_text(strip=True)
            return None
        price = to_price(meta("product:price:amount", "og:price:amount", "price"))
        if price:
            found[url] = {"name": meta("og:title") or (soup.title.string.strip() if soup.title else url),
                          "price": price, "strike": None, "url": url, "image": meta("og:image") or ""}
    return list(found.values())


# ---------- robot ----------
def fetch(session, url):
    for attempt in range(2):
        r = session.get(url, timeout=30, headers={
            "User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
        if r.status_code in (429, 503) and attempt == 0:
            time.sleep(20)
            continue
        return r
    return r


def pkey(shop, prod):
    return shop + ":" + hashlib.sha1((prod["url"].split("?")[0] + prod["name"]).encode()).hexdigest()[:12]


def usual_price(points):
    since = (dt.date.today() - dt.timedelta(days=REF_DAYS)).isoformat()
    past = [p for d, p in points if since <= d < TODAY]
    return statistics.median(past) if len(past) >= MIN_POINTS else None


def notify(deals, cfg):
    hook = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if not hook or not deals:
        return
    for d in deals[:10]:
        embed = {"title": f"-{d['pct']} % · {d['name']}"[:250], "url": d["url"],
                 "description": f"**{d['price']:.2f} €** au lieu de {d['ref']:.2f} € chez {d['shop']}\n{d['reason']}"}
        if d.get("image"):
            embed["thumbnail"] = {"url": d["image"]}
        try:
            requests.post(hook, json={"username": cfg.get("site_name", "Alertes"), "embeds": [embed]}, timeout=15)
            time.sleep(1)
        except requests.RequestException:
            pass


def main():
    watch = load(WATCH, [])
    hist = load(HIST, {})
    deals = load(DEALS, [])
    status = load(STATUS, {})
    cfg = load(CONFIG, {})
    session = requests.Session()
    new_deals, current = [], {}

    for w in watch:
        if not w.get("actif", True):
            continue
        wid, url = w["id"], w["url"]
        shop = shop_name(url)
        seuil = float(w.get("seuil") or 0)
        plafond = float(w.get("plafond") or 0)
        mots = [m.strip().lower() for m in str(w.get("filtre", "")).split(",") if m.strip()]
        try:
            r = fetch(session, url)
            if r.status_code != 200:
                status[wid] = {"date": NOW, "ok": False, "msg": f"Le site a refusé l'accès (HTTP {r.status_code})"}
                continue
            prods = extract(r.text, url)
        except Exception as e:  # noqa: BLE001
            status[wid] = {"date": NOW, "ok": False, "msg": f"Erreur : {e.__class__.__name__}"}
            continue
        finally:
            time.sleep(random.uniform(3, 7))
        if mots:
            prods = [p for p in prods if any(m in p["name"].lower() for m in mots)]
        if not prods:
            status[wid] = {"date": NOW, "ok": False,
                           "msg": "Page lue mais aucun prix trouvé (page protégée ou format non reconnu)"}
            continue
        status[wid] = {"date": NOW, "ok": True, "msg": f"{len(prods)} produit(s) relevé(s)", "n": len(prods)}

        for p in prods:
            k = pkey(shop, p)
            h = hist.setdefault(k, {"name": p["name"], "url": p["url"], "shop": shop, "points": []})
            h.update(name=p["name"], url=p["url"], image=p.get("image", ""))
            pts = h["points"]
            if pts and pts[-1][0] == TODAY:
                pts[-1][1] = min(pts[-1][1], p["price"])
            else:
                pts.append([TODAY, p["price"]])
            current[k] = p["price"]
            ref = usual_price(pts)
            reason, base = None, None
            if seuil and ref and (ref - p["price"]) / ref * 100 >= seuil:
                reason, base = f"Prix habituel ({REF_DAYS} j) : {ref:.2f} €", ref
            elif seuil and p.get("strike") and (p["strike"] - p["price"]) / p["strike"] * 100 >= seuil:
                reason, base = "Remise affichée par le site", p["strike"]
            elif plafond and p["price"] <= plafond:
                reason, base = f"Sous ton plafond de {plafond:.0f} €", ref or p.get("strike") or p["price"]
            if not reason:
                continue
            if any(d["key"] == k and d["active"] and d["price"] <= p["price"] + 0.01 for d in deals):
                continue  # déjà signalé à ce prix
            pct = round((base - p["price"]) / base * 100) if base else 0
            d = {"key": k, "watch": wid, "name": p["name"], "shop": shop, "url": p["url"],
                 "image": p.get("image", ""), "price": p["price"], "ref": round(base, 2), "pct": pct,
                 "reason": reason, "date": NOW, "active": True, "label": w.get("label", "")}
            deals = [x for x in deals if not (x["key"] == k and x["active"])]
            deals.insert(0, d)
            new_deals.append(d)

    # une affaire se termine quand le prix remonte
    for d in deals:
        if d["active"] and d["key"] in current and current[d["key"]] > d["price"] * 1.02:
            d["active"], d["ended"] = False, NOW

    cutoff = (dt.date.today() - dt.timedelta(days=HIST_DAYS)).isoformat()
    for h in hist.values():
        h["points"] = [p for p in h["points"] if p[0] >= cutoff]
    hist = {k: v for k, v in hist.items() if v["points"]}

    status["_robot"] = {"date": NOW, "new": len(new_deals)}
    dump(HIST, hist)
    dump(DEALS, deals[:MAX_DEALS])
    dump(STATUS, status)
    notify(new_deals, cfg)
    print(f"{len(new_deals)} nouvelle(s) affaire(s)")


if __name__ == "__main__":
    sys.exit(main())
