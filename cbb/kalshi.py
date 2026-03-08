import time
import base64
import json

import httpx

from config import (
    KALSHI_BASE_URL, KALSHI_CBB_KEYWORDS, KALSHI_RETRY_DELAYS,
    PAPER_TRADING, KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PEM,
)
from utils import log, retry

# ── Auth setup (only needed for live order placement) ─────────────────
_private_key = None

if KALSHI_PRIVATE_KEY_PEM:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding

    _private_key = serialization.load_pem_private_key(
        KALSHI_PRIVATE_KEY_PEM.encode(),
        password=None,
    )


def _auth_headers(method: str, path: str) -> dict:
    """
    Generate signed auth headers for authenticated endpoints.
    Only called for live order placement — never during paper trading.
    Raises RuntimeError if private key is not loaded.
    """
    if not _private_key:
        raise RuntimeError(
            "Kalshi private key not configured. "
            "Set KALSHI_PRIVATE_KEY_PEM to place live orders."
        )

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding

    ts_ms = str(int(time.time() * 1000))
    msg = ts_ms + method.upper() + path
    signature = _private_key.sign(
        msg.encode(),
        asym_padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": KALSHI_API_KEY_ID,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
        "KALSHI-ACCESS-TIMESTAMP": ts_ms,
        "Content-Type": "application/json",
    }


# ── Public GET (no auth required) ────────────────────────────────────

def _get_public(path: str, params: dict = None) -> dict | None:
    """
    Call a public Kalshi GET endpoint. No authentication headers sent.
    All market data, event listings, and price feeds are public.
    """
    url = KALSHI_BASE_URL + path

    def _fetch():
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    return retry(_fetch, KALSHI_RETRY_DELAYS, label=f"KALSHI_GET{path}")


# ── Authenticated POST (live trading only) ────────────────────────────

def _post_authenticated(path: str, body: dict) -> dict | None:
    """
    Call an authenticated Kalshi POST endpoint.
    Only used for live order placement — never called in paper mode.
    """
    headers = _auth_headers("POST", path)
    url = KALSHI_BASE_URL + path

    def _fetch():
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            return resp.json()

    return retry(_fetch, KALSHI_RETRY_DELAYS, label=f"KALSHI_POST{path}")


# ── Market data ───────────────────────────────────────────────────────

def get_live_cbb_events() -> list[dict]:
    """
    Paginate through all open Kalshi events and return those
    matching college basketball patterns.
    """
    events = []
    cursor = None
    total_checked = 0
    cbb_found = 0

    while True:
        params = {
            "status": "open",
            "limit": 200,
            "with_nested_markets": "true",
        }
        if cursor:
            params["cursor"] = cursor

        data = _get_public("/events", params=params)
        if not data:
            log("KALSHI_API_EMPTY_RESPONSE")
            break

        page_events = data.get("events", [])
        log(f"KALSHI_API_PAGE: {len(page_events)} events returned")
        
        for event in page_events:
            total_checked += 1
            if _is_cbb_event(event):
                events.append(_parse_event(event))
                cbb_found += 1

        cursor = data.get("cursor")
        if not cursor:
            break

    log(f"KALSHI_FILTERED: {cbb_found}/{total_checked} events matched CBB keywords")
    return events


def _is_cbb_event(event: dict) -> bool:
    series = event.get("series_ticker", "").upper()
    title  = event.get("title", "").upper()
    return any(kw in series or kw in title for kw in KALSHI_CBB_KEYWORDS)


def _parse_event(event: dict) -> dict:
    markets = [
        {
            "ticker":   m.get("ticker", ""),
            "title":    m.get("title", ""),
            "yes_bid":  m.get("yes_bid", 0) or 0,
            "yes_ask":  m.get("yes_ask", 0) or 0,
            "status":   m.get("status", ""),
        }
        for m in event.get("markets", [])
    ]
    return {
        "event_ticker":  event.get("event_ticker", ""),
        "series_ticker": event.get("series_ticker", ""),
        "title":         event.get("title", ""),
        "sub_title":     event.get("sub_title", ""),
        "markets":       markets,
    }


def find_win_market(kalshi_event: dict, team_name: str) -> dict | None:
    """
    Within a Kalshi event's markets, find the win market for a specific team.
    Matches market titles containing the team name and a win-related keyword.
    Returns the market dict or None.
    """
    if not kalshi_event:
        return None
    target = team_name.lower()
    for market in kalshi_event.get("markets", []):
        title = market.get("title", "").lower()
        if target in title and "win" in title:
            return market
    return None


# ── Order placement ───────────────────────────────────────────────────

def place_order(ticker: str, action: str, contracts: int, price_cents: int) -> dict:
    """
    Place or simulate a Kalshi order.

    Paper mode  → logs and returns a synthetic response. No HTTP call made.
    Live mode   → signs and POSTs to /orders. Requires credentials.

    action: 'buy' or 'sell'
    price_cents: limit price in cents (1–99)
    """
    if PAPER_TRADING:
        synthetic_id = f"PAPER_{int(time.time() * 1000)}"
        log("TRADE_SIMULATED", {
            "ticker":       ticker,
            "action":       action,
            "contracts":    contracts,
            "price_cents":  price_cents,
            "order_id":     synthetic_id,
        })
        return {"order_id": synthetic_id, "status": "simulated"}

    # Live path — credentials required (enforced by config.py at startup)
    body = {
        "ticker":    ticker,
        "action":    action,
        "side":      "yes",
        "type":      "limit",
        "count":     contracts,
        "yes_price": price_cents,
    }
    return _post_authenticated("/orders", body)


def buy_yes(ticker: str, contracts: int, yes_ask_cents: int) -> dict:
    """Buy YES at yes_ask + 1 cent (aggressive limit, guarantees fill)."""
    price = min(yes_ask_cents + 1, 99)
    return place_order(ticker, "buy", contracts, price)


def sell_yes(ticker: str, contracts: int, yes_bid_cents: int) -> dict:
    """Sell YES at yes_bid - 1 cent (aggressive limit, guarantees fill)."""
    price = max(yes_bid_cents - 1, 1)
    return place_order(ticker, "sell", contracts, price)
