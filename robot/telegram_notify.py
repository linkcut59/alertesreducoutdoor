"""Envoie sur Telegram les affaires detectees lors du dernier passage du robot.

Ce script lit docs/data/deals.json et docs/data/status.json (ecrits par check.py).
Il envoie uniquement les affaires NOUVELLES du dernier passage, sauf si TELEGRAM_ALL=true
(case "renvoyer" cochee au lancement manuel), auquel cas il renvoie toutes les affaires actives.

Secrets necessaires (Settings > Secrets and variables > Actions) :
  TELEGRAM_BOT_TOKEN  : le token donne par BotFather
  TELEGRAM_CHAT_ID    : @nomducanal (canal public) ou -100... (canal prive)
"""

import html
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
SEND_ALL = os.environ.get("TELEGRAM_ALL", "").strip().lower() == "true"
MAX_MESSAGES = 15  # evite d'inonder le canal (Telegram limite aussi le rythme)


def load(name, default):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def euros(x):
    try:
        return f"{float(x):.2f}".replace(".", ",") + " €"
    except (TypeError, ValueError):
        return ""


def post(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT, "text": text, "parse_mode":"HTML","disable_web_page_preview":"true"}
    for attempt in range(2):
        r = requests.post(url, data=payload, timeout=30)
        if r.status_code == 429 and attempt == 0:
            try:
                wait = int(r.json().get("parameters", {}).get("retry_after", 5))
            except (ValueError, KeyError):
                wait = 5
            time.sleep(min(wait, 30))
            continue
        if r.status_code != 200:
            print(f"Telegram a refuse le message (HTTP {r.status_code}) : {r.text[:200]}")
            return False
        return True
    return False


def format_deal(d):
    lines = [f"🔻 <b>{html.escape(str(d.get('name', 'Produit')))}</b>"]
    price, ref, pct = d.get("price"), d.get("ref"), d.get("pct") or 0
    prix = f"💶 <b>{euros(price)}</b>"
    try:
        if ref and float(ref) > float(price):
            prix += f" <s>{euros(ref)} (-{float(pct):.0f} %)"
    except (TypeError, ValueError):
        pass
    lines.append(prix)
    if d.get("shop"):
        lines.append(f"🏬 {html.escape(str(d['shop']))}")
    if d.get("reason"):
        lines.append(f"ℹ️ {html.escape(str(d['reason']))}")
    url = str(d.get("url", ""))
    if url.startswith("http"):
        lines.append(f'🔗 <a href="{html.escape(url, quote=True)}">Voir l\'offre</a>')
    return "\n".join(lines)


def main():
    if not TOKEN or not CHAT:
        print("Telegram : TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID manquant, aucun envoi.")
        return 0
    deals = [d for d in load("deals.json", []) if d.get("active")]
    if not SEND_ALL:
        run_date = load("status.json", {}).get("_robot", {}).get("date")
        deals = [d for d in deals if d.get("date") == run_date]
    if not deals:
        print("Telegram : aucune nouvelle affaire a envoyer.")
        return 0
    deals.sort(key=lambda d: d.get("pct") or 0, reverse=True)
    sent = 0
    for d in deals[:MAX_MESSAGES]:
        if post(format_deal(d)):
            sent += 1
        time.sleep(1.2)
    extra = len(deals) - MAX_MESSAGES
    if extra > 0 and sent:
        post(f"➕ {extra} autre(s) affaire(s) detectee(s) ce passage.")
    print(f"Telegram : {sent} message(s) envoye(s) sur {len(deals)} affaire(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
