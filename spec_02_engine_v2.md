# CBB Worker — Spec 2 of 3: Python Trading Engine
**For: OpenClaw Agent (Kimi K2.5)**
**Version: 2.1 — March 2026**
**Prerequisite: Spec 1 (Database) must be complete before implementing this.**

---

## 0. READ THIS FIRST

This spec covers the full Python trading engine. It polls ESPN and Kalshi every 60 seconds, calculates divergence edges, fires paper or live trades, and writes all state to Supabase.

The engine is a single long-running Python process deployed as a Railway service named `cbb-worker`, connected to the GitHub repo `cbb-trading`.

Language: **Python 3.11+**
Runtime: Railway (single process, no workers, no threads required)
Schema: already created by Spec 1

Do not implement the dashboard here. That is Spec 3.

When this spec is complete, the following must be true:
- `python main.py` (run from inside the `cbb/` directory) starts and runs indefinitely without crashing
- Every 60 seconds it logs a structured heartbeat to stdout
- Paper trades are recorded to Supabase correctly
- All entry and exit conditions match the logic in this spec exactly
- The daily stop-loss halts trading and logs correctly

---

## 1. Repository Structure

**GitHub repo:** `cbb-trading`

All engine files live in the `cbb/` subdirectory at the repo root:

```
/cbb-trading              ← repo root
  /cbb                    ← Railway root directory for cbb-worker service
    main.py               ← entry point, bootstrap + main loop
    config.py             ← all constants and env var reads
    espn.py               ← ESPN API client
    kalshi.py             ← Kalshi API client (public reads + optional auth)
    signals.py            ← edge calculation + entry decision logic
    positions.py          ← exit condition logic + PnL calculation
    mapping.py            ← normalize() + lookup_team()
    seed_teams.py         ← from Spec 1 (already created)
    utils.py              ← logging + retry helpers
    requirements.txt
  /supabase
    /migrations
      0001_cbb_schema.sql ← already run manually (Spec 1)
  /dashboard              ← Netlify SPA (Spec 3, build later)
  .gitignore
  README.md
```

Railway is configured with **Root Directory = `cbb`**, so from Railway's perspective `main.py` is at the root. All imports in the engine use flat imports (e.g. `from config import ...`) — no `/cbb/` prefix needed.

---

## 2. Environment Variables

Read from Railway environment. Kalshi credentials are **optional during paper trading** — the Kalshi market data endpoints are fully public and require no authentication. Only set them when going live.

```
# Required always
SUPABASE_URL                   ← Supabase project URL
SUPABASE_SERVICE_ROLE_KEY      ← Supabase service role key (not anon key)

# Required only for live trading (leave unset during paper trading)
KALSHI_API_KEY_ID              ← Kalshi API key ID string
KALSHI_PRIVATE_KEY_PEM         ← Full RSA private key PEM, \n escaped as literal \n

# Trading config (all optional, defaults shown)
CBB_PAPER_TRADING              ← "true" or "false" (default: "true")
CBB_BANKROLL                   ← starting bankroll in dollars (default: "500")
CBB_MAX_CONCURRENT_GAMES       ← max simultaneous open positions (default: "4")
CBB_DAILY_STOP_LOSS_PCT        ← e.g. "0.05" for 5% (default: "0.05")
```

At startup, if `CBB_PAPER_TRADING` is not set, default to `"true"` and log a warning. If `KALSHI_API_KEY_ID` is not set and `CBB_PAPER_TRADING` is `"false"`, abort with a `FATAL_ERROR` log before entering the main loop.

---

## 3. `requirements.txt`

```
supabase==2.4.2
httpx==0.27.0
cryptography==42.0.5
python-dotenv==1.0.1
```

`cryptography` is included unconditionally so the package is always installed and the import in `kalshi.py` doesn't fail. However, the private key is only **loaded** if `KALSHI_PRIVATE_KEY_PEM` is set, and signing is only **called** during live order placement. During paper trading the library is imported but never exercised.

---

## 4. `config.py`

```python
import os
import sys

# ── Trading mode ──────────────────────────────────────────────────────
PAPER_TRADING = os.environ.get("CBB_PAPER_TRADING", "true").lower() == "true"
BANKROLL_DOLLARS = float(os.environ.get("CBB_BANKROLL", "500"))
MAX_CONCURRENT_GAMES = int(os.environ.get("CBB_MAX_CONCURRENT_GAMES", "4"))
DAILY_STOP_LOSS_PCT = float(os.environ.get("CBB_DAILY_STOP_LOSS_PCT", "0.05"))

# ── Kalshi credentials (optional — only required for live trading) ─────
# GET endpoints (market data) are fully public. No key needed for paper mode.
# Only POST /orders requires authentication.
KALSHI_API_KEY_ID    = os.environ.get("KALSHI_API_KEY_ID", "")
KALSHI_PRIVATE_KEY_PEM = os.environ.get("KALSHI_PRIVATE_KEY_PEM", "").replace("\\n", "\n")

# Guard: abort at startup if live trading is requested without credentials
if not PAPER_TRADING and not KALSHI_API_KEY_ID:
    print('{"event": "FATAL_ERROR", "error": "KALSHI_API_KEY_ID is required when CBB_PAPER_TRADING=false"}', flush=True)
    sys.exit(1)

# ── Loop timing ───────────────────────────────────────────────────────
MAIN_LOOP_INTERVAL_SECONDS = 60
ESPN_SUMMARY_STAGGER_MS = 150   # ms delay between per-game ESPN summary calls

# ── ESPN ──────────────────────────────────────────────────────────────
ESPN_SCOREBOARD_URL = (
    "http://site.api.espn.com/apis/site/v2/sports/basketball"
    "/mens-college-basketball/scoreboard"
)
ESPN_SUMMARY_URL = (
    "http://site.api.espn.com/apis/site/v2/sports/basketball"
    "/mens-college-basketball/summary"
)
ESPN_SCOREBOARD_PARAMS = {"groups": 50, "limit": 200}

ESPN_LIVE_STATUSES = {"STATUS_IN_PROGRESS"}
ESPN_HALFTIME_STATUS = "STATUS_HALFTIME"
ESPN_FINAL_STATUS = "STATUS_FINAL"

# ── Kalshi ────────────────────────────────────────────────────────────
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_CBB_KEYWORDS = ["NCAAB", "CBB", "NCAABB", "KXNCAAB"]

# ── Entry thresholds ──────────────────────────────────────────────────
MIN_EDGE = 0.10                  # minimum divergence to enter
MIN_MINUTES_REMAINING = 5        # never enter if <= 5 min left in game
H2_ENTRY_CUTOFF_MINUTES = 8      # never enter if H2 and <= 8 min left

# ── Exit thresholds ───────────────────────────────────────────────────
CONVERGENCE_BUFFER = 0.04        # exit when kalshi >= entry_espn - 0.04
REVERSAL_THRESHOLD = 0.20        # exit when espn drops 20pp below entry
LATE_GAME_EXIT_MINUTES = 5       # force exit if H2 and <= 5 min

# ── Bet sizing tiers: (min_edge, dollars) ─────────────────────────────
# Checked in order — first match wins
BET_TIERS = [
    (0.25, 5),
    (0.20, 3),
    (0.15, 2),
    (0.10, 1),
]
MAX_GAME_EXPOSURE_PCT = 0.03     # max 3% of bankroll per single trade

# ── Retry policy ──────────────────────────────────────────────────────
ESPN_RETRY_DELAYS = [1, 2, 4]    # seconds
KALSHI_RETRY_DELAYS = [2, 4, 8]
SUPABASE_RETRY_DELAYS = [1, 2, 4]
```

---

## 5. `mapping.py`

```python
import re

def normalize(raw: str) -> str:
    """
    Normalize a raw Kalshi team name for lookup.
    Must be byte-for-byte identical to seed_teams.normalize().
    Steps: lowercase → strip → remove all punctuation except & → collapse spaces
    """
    s = raw.lower().strip()
    s = re.sub(r"[^a-z0-9 &]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def strip_ranking(raw: str) -> str:
    """
    Remove ESPN/Kalshi ranking prefix like 'No. 3 Michigan' → 'Michigan'
    Handles: 'No. 3', 'No 3', '#3', '(3)'
    """
    s = re.sub(r"^(no\.?\s*\d+\s+|#\d+\s+|\(\d+\)\s*)", "", raw, flags=re.IGNORECASE)
    return s.strip()


def lookup_team(supabase_client, raw_kalshi_name: str) -> dict | None:
    """
    Look up a team in the Supabase team_name_mapping table.
    Returns dict with keys: espn_id, espn_name, espn_abbr, conference
    Returns None if not found.
    """
    cleaned = strip_ranking(raw_kalshi_name)
    key = normalize(cleaned)

    result = supabase_client.table("team_name_mapping") \
        .select("espn_id, espn_name, espn_abbr, conference") \
        .eq("kalshi_name", key) \
        .maybe_single() \
        .execute()

    if result.data:
        return result.data
    return None


def parse_kalshi_title(title: str) -> tuple[str, str] | None:
    """
    Parse a Kalshi event title into two team name strings.
    Handles formats:
      'Duke vs North Carolina'
      'Will Duke win vs North Carolina?'
      'Michigan State vs Purdue'
    Returns (team_a, team_b) or None if unparseable.
    """
    # Strip 'Will ... win' wrapper
    title = re.sub(r"^will\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+win\??$", "", title, flags=re.IGNORECASE)
    title = title.rstrip("?").strip()

    # Split on ' vs ' (with optional period)
    parts = re.split(r"\s+vs\.?\s+", title, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) != 2:
        return None

    return parts[0].strip(), parts[1].strip()
```

---

## 6. `espn.py`

```python
import time
import httpx
from config import (
    ESPN_SCOREBOARD_URL, ESPN_SUMMARY_URL, ESPN_SCOREBOARD_PARAMS,
    ESPN_RETRY_DELAYS, ESPN_SUMMARY_STAGGER_MS
)
from utils import log, retry


def get_live_games() -> list[dict]:
    """
    Fetch ESPN scoreboard and return a list of processed game dicts
    for all D1 games that are currently in progress.

    Each returned dict:
    {
        "espn_game_id": str,
        "home_team": { "id", "display_name", "short_name", "abbr", "score" },
        "away_team": { "id", "display_name", "short_name", "abbr", "score" },
        "status_name": str,          # e.g. STATUS_IN_PROGRESS
        "half": int,                 # 1, 2, or 3+ for OT
        "display_clock": str,        # "12:34"
        "minutes_remaining": float,
        "is_halftime": bool,
        "start_time": str,           # ISO timestamp
    }
    """
    def _fetch():
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(ESPN_SCOREBOARD_URL, params=ESPN_SCOREBOARD_PARAMS)
            resp.raise_for_status()
            return resp.json()

    data = retry(_fetch, ESPN_RETRY_DELAYS, label="ESPN_SCOREBOARD")
    if not data:
        return []

    games = []
    for event in data.get("events", []):
        try:
            game = _parse_scoreboard_event(event)
            if game:
                games.append(game)
        except Exception as e:
            log("ESPN_PARSE_ERROR", {"espn_id": event.get("id"), "error": str(e)})

    return games


def _parse_scoreboard_event(event: dict) -> dict | None:
    status = event.get("status", {})
    status_type = status.get("type", {})
    status_name = status_type.get("name", "")

    competition = event.get("competitions", [{}])[0]
    competitors = competition.get("competitors", [])
    if len(competitors) < 2:
        return None

    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

    half = status.get("period", 1)
    display_clock = status.get("displayClock", "0:00")
    minutes_remaining = _parse_clock(display_clock)

    start_time = event.get("date", "")

    return {
        "espn_game_id": str(event["id"]),
        "home_team": {
            "id": str(home["team"]["id"]),
            "display_name": home["team"].get("displayName", ""),
            "short_name": home["team"].get("shortDisplayName", ""),
            "abbr": home["team"].get("abbreviation", ""),
            "score": int(home.get("score", 0) or 0),
        },
        "away_team": {
            "id": str(away["team"]["id"]),
            "display_name": away["team"].get("displayName", ""),
            "short_name": away["team"].get("shortDisplayName", ""),
            "abbr": away["team"].get("abbreviation", ""),
            "score": int(away.get("score", 0) or 0),
        },
        "status_name": status_name,
        "half": half,
        "display_clock": display_clock,
        "minutes_remaining": minutes_remaining,
        "is_halftime": status_name == "STATUS_HALFTIME",
        "is_final": status_name == "STATUS_FINAL",
        "start_time": start_time,
    }


def _parse_clock(display_clock: str) -> float:
    """Convert 'MM:SS' to minutes remaining as a float."""
    try:
        parts = display_clock.split(":")
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = int(parts[1])
            return round(minutes + seconds / 60, 2)
    except Exception:
        pass
    return 0.0


def get_win_probability(espn_game_id: str) -> dict | None:
    """
    Fetch game summary and return the most recent win probability entry.

    Returns:
    {
        "home_win_pct": float,   # 0.0–1.0
        "away_win_pct": float,
        "seconds_left": int,
    }
    or None if unavailable.
    """
    time.sleep(ESPN_SUMMARY_STAGGER_MS / 1000)

    def _fetch():
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(ESPN_SUMMARY_URL, params={"event": espn_game_id})
            resp.raise_for_status()
            return resp.json()

    data = retry(_fetch, ESPN_RETRY_DELAYS, label=f"ESPN_SUMMARY_{espn_game_id}")
    if not data:
        return None

    wp_array = data.get("winprobability", [])
    if not wp_array:
        return None

    latest = wp_array[-1]
    return {
        "home_win_pct": float(latest.get("homeWinPercentage", 0)),
        "away_win_pct": float(latest.get("awayWinPercentage", 0)),
        "seconds_left": int(latest.get("secondsLeft", 0)),
    }
```

---

## 7. `kalshi.py`

```python
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
# All GET endpoints (market data, events, prices) are fully public.
# Only POST /orders requires RSA authentication.
# During paper trading KALSHI_PRIVATE_KEY_PEM will be empty — that's fine.

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

    Uses public endpoint — no auth required.

    Each returned dict:
    {
        "event_ticker": str,
        "series_ticker": str,
        "title": str,
        "sub_title": str,
        "markets": [
            {
                "ticker": str,
                "title": str,
                "yes_bid": int,    # cents
                "yes_ask": int,    # cents
                "status": str,
            }
        ]
    }
    """
    events = []
    cursor = None

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
            break

        for event in data.get("events", []):
            if _is_cbb_event(event):
                events.append(_parse_event(event))

        cursor = data.get("cursor")
        if not cursor:
            break

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
```

---

## 8. `signals.py`

```python
from config import (
    MIN_EDGE, MIN_MINUTES_REMAINING, H2_ENTRY_CUTOFF_MINUTES,
    BET_TIERS, MAX_GAME_EXPOSURE_PCT
)


def calculate_edge(espn_win_prob: float, kalshi_yes_ask_cents: int) -> float:
    """ESPN win probability minus Kalshi implied probability."""
    if kalshi_yes_ask_cents <= 0:
        return 0.0
    return round(espn_win_prob - (kalshi_yes_ask_cents / 100), 4)


def get_bet_size(edge: float, bankroll_dollars: float) -> float:
    """
    Return dollar bet size for a given edge and current bankroll.
    Returns 0 if no tier matches.
    """
    tier_amount = 0
    for (min_edge, amount) in BET_TIERS:
        if edge >= min_edge:
            tier_amount = amount
            break

    if tier_amount == 0:
        return 0

    cap = bankroll_dollars * MAX_GAME_EXPOSURE_PCT
    return min(tier_amount, max(1, int(cap)))


def get_contract_count(bet_size_dollars: float, yes_ask_cents: int) -> int:
    """
    Number of contracts to buy.
    Each contract costs yes_ask_cents / 100 dollars.
    """
    if yes_ask_cents <= 0:
        return 0
    cost_per_contract = yes_ask_cents / 100
    return max(1, int(bet_size_dollars / cost_per_contract))


def evaluate_entry(
    edge: float,
    half: int,
    minutes_remaining: float,
    has_open_position: bool,
    is_mapped: bool,
    open_position_count: int,
    max_concurrent: int,
    stop_loss_active: bool,
) -> tuple[bool, str]:
    """
    Return (should_enter: bool, reason: str).
    reason is one of the action_taken values for cbb_signals.
    """
    if stop_loss_active:
        return False, "STOP_LOSS_ACTIVE"
    if not is_mapped:
        return False, "UNMAPPED_TEAM"
    if edge < MIN_EDGE:
        return False, "BELOW_THRESHOLD"
    if has_open_position:
        return False, "POSITION_ALREADY_OPEN"
    if open_position_count >= max_concurrent:
        return False, "CAP_REACHED"
    if minutes_remaining <= MIN_MINUTES_REMAINING:
        return False, "TIME_BLOCKED"
    if half == 2 and minutes_remaining <= H2_ENTRY_CUTOFF_MINUTES:
        return False, "HALFTIME_BLOCKED"
    if half >= 3:
        return False, "TIME_BLOCKED"   # no new entries in OT

    return True, "TRADE_FIRED"
```

---

## 9. `positions.py`

```python
from config import CONVERGENCE_BUFFER, REVERSAL_THRESHOLD, LATE_GAME_EXIT_MINUTES


def check_exit(
    position: dict,
    current_espn_prob: float,
    current_kalshi_bid_cents: int,
    half: int,
    minutes_remaining: float,
    game_status: str,
) -> str | None:
    """
    Check whether an open position should be exited.
    Returns exit reason string, or None if no exit yet.

    Priority order matters — check most urgent conditions first.
    """

    # 1. Game over — always exit
    if game_status == "STATUS_FINAL":
        return "GAME_OVER"

    # 2. Overtime — exit immediately, OT is unpredictable
    if half >= 3:
        return "OVERTIME"

    # 3. Halftime — exit first-half positions when H2 begins
    if game_status == "STATUS_IN_PROGRESS" and half == 2:
        if position.get("entry_half") == 1:
            return "HALFTIME"

    # 4. Late game time expiry
    if half == 2 and minutes_remaining <= LATE_GAME_EXIT_MINUTES:
        return "TIME_EXPIRY"

    # 5. Signal reversal — ESPN has sharply moved against us
    entry_prob = position["entry_espn_probability"]
    if current_espn_prob < entry_prob - REVERSAL_THRESHOLD:
        return "SIGNAL_REVERSAL"

    # 6. Convergence — Kalshi price has moved to our target
    target_price = entry_prob - CONVERGENCE_BUFFER
    current_kalshi_prob = current_kalshi_bid_cents / 100
    if current_kalshi_prob >= target_price:
        return "CONVERGENCE"

    return None


def calculate_pnl(position: dict, exit_price_cents: int) -> dict:
    """
    Calculate gross and net PnL for a closing position.
    Returns dict with: gross_pnl_cents, fee_cents, net_pnl_cents, net_pnl_dollars
    """
    entry_price = position["entry_kalshi_price_cents"]
    contracts = position["contracts"]

    gross = (exit_price_cents - entry_price) * contracts

    # Kalshi fee: $0.01–$0.02 per contract, capped at 100 contracts
    # Conservative estimate: $0.01 per contract on exit
    fee = min(contracts, 100)  # cents

    net = gross - fee

    return {
        "gross_pnl_cents": gross,
        "fee_cents": fee,
        "net_pnl_cents": net,
        "net_pnl_dollars": round(net / 100, 4),
    }
```

---

## 10. `utils.py`

```python
import time
import json
from datetime import datetime, timezone


def log(event: str, data: dict = None):
    """Emit structured JSON log to stdout."""
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
    }
    if data:
        payload.update(data)
    print(json.dumps(payload), flush=True)


def retry(fn, delays: list[int], label: str = ""):
    """
    Call fn() with exponential backoff retries.
    Returns result on success. Returns None after all retries exhausted.
    Logs each failure.
    """
    last_err = None
    for attempt, delay in enumerate(delays):
        try:
            return fn()
        except Exception as e:
            last_err = e
            log(f"RETRY_{label}", {"attempt": attempt + 1, "delay": delay, "error": str(e)})
            time.sleep(delay)
    log(f"RETRY_EXHAUSTED_{label}", {"error": str(last_err)})
    return None


def sleep_ms(ms: int):
    time.sleep(ms / 1000)
```

---

## 11. `main.py`

This is the full entry point. Read it carefully — the ordering of operations within the main loop is critical.

```python
#!/usr/bin/env python3
"""
CBB Trading Engine — main.py
Entry point for Railway cbb-worker service.
"""

import time
import os
from datetime import datetime, timezone, date

from supabase import create_client, Client

import config
from utils import log, retry
from seed_teams import seed as seed_team_mapping
from mapping import lookup_team, parse_kalshi_title, normalize, strip_ranking
from espn import get_live_games, get_win_probability
import kalshi as kalshi_client
from signals import calculate_edge, get_bet_size, get_contract_count, evaluate_entry
from positions import check_exit, calculate_pnl


# ── Supabase client ───────────────────────────────────────────────────
supabase: Client = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_ROLE_KEY"],
)


# ── Bootstrap ─────────────────────────────────────────────────────────

def bootstrap():
    log("CBB_WORKER_START", {
        "paper_mode": config.PAPER_TRADING,
        "bankroll": config.BANKROLL_DOLLARS,
        "max_concurrent": config.MAX_CONCURRENT_GAMES,
    })

    # Seed team mapping table
    seed_team_mapping()

    # Ensure bankroll row exists for current mode
    existing = supabase.table("cbb_bankroll") \
        .select("id") \
        .eq("is_paper", config.PAPER_TRADING) \
        .maybe_single() \
        .execute()

    if not existing.data:
        bankroll_cents = int(config.BANKROLL_DOLLARS * 100)
        supabase.table("cbb_bankroll").insert({
            "balance_cents": bankroll_cents,
            "is_paper": config.PAPER_TRADING,
        }).execute()
        log("BANKROLL_INITIALIZED", {
            "balance_dollars": config.BANKROLL_DOLLARS,
            "paper": config.PAPER_TRADING,
        })


# ── Daily stop-loss ───────────────────────────────────────────────────

def is_stop_loss_active() -> bool:
    today = date.today().isoformat()
    result = supabase.table("cbb_daily_pnl") \
        .select("stop_loss_hit") \
        .eq("date", today) \
        .maybe_single() \
        .execute()
    return bool(result.data and result.data.get("stop_loss_hit"))


def check_and_set_stop_loss(bankroll_dollars: float) -> bool:
    today = date.today().isoformat()
    result = supabase.table("cbb_daily_pnl") \
        .select("net_pnl_cents") \
        .eq("date", today) \
        .maybe_single() \
        .execute()

    if not result.data:
        return False

    net_pnl_dollars = result.data["net_pnl_cents"] / 100
    threshold = -(bankroll_dollars * config.DAILY_STOP_LOSS_PCT)

    if net_pnl_dollars <= threshold:
        supabase.table("cbb_daily_pnl").upsert({
            "date": today,
            "stop_loss_hit": True,
            "stop_loss_hit_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="date").execute()
        log("DAILY_STOP_LOSS_HIT", {
            "net_pnl_dollars": net_pnl_dollars,
            "threshold": threshold,
        })
        return True

    return False


# ── Bankroll helpers ──────────────────────────────────────────────────

def get_bankroll_dollars() -> float:
    result = supabase.table("cbb_bankroll") \
        .select("balance_cents") \
        .eq("is_paper", config.PAPER_TRADING) \
        .maybe_single() \
        .execute()
    if result.data:
        return result.data["balance_cents"] / 100
    return config.BANKROLL_DOLLARS


def update_bankroll(delta_cents: int):
    current = supabase.table("cbb_bankroll") \
        .select("id, balance_cents") \
        .eq("is_paper", config.PAPER_TRADING) \
        .maybe_single() \
        .execute()
    if current.data:
        new_balance = current.data["balance_cents"] + delta_cents
        supabase.table("cbb_bankroll") \
            .update({"balance_cents": new_balance}) \
            .eq("id", current.data["id"]) \
            .execute()


# ── Open positions ────────────────────────────────────────────────────

def get_open_positions() -> list[dict]:
    result = supabase.table("cbb_positions") \
        .select("*") \
        .eq("status", "open") \
        .eq("is_paper_trade", config.PAPER_TRADING) \
        .execute()
    return result.data or []


def has_open_position(espn_game_id: str) -> bool:
    result = supabase.table("cbb_positions") \
        .select("position_id") \
        .eq("espn_game_id", espn_game_id) \
        .eq("status", "open") \
        .eq("is_paper_trade", config.PAPER_TRADING) \
        .execute()
    return bool(result.data)


# ── Game / DB helpers ─────────────────────────────────────────────────

def upsert_game(game: dict, kalshi_event_ticker: str = None) -> str | None:
    """
    Upsert a cbb_games row. Returns the game_id UUID.
    """
    row = {
        "espn_game_id": game["espn_game_id"],
        "home_team_espn_id": game["home_team"]["id"],
        "away_team_espn_id": game["away_team"]["id"],
        "home_team_name": game["home_team"]["display_name"],
        "away_team_name": game["away_team"]["display_name"],
        "home_team_abbr": game["home_team"]["abbr"],
        "away_team_abbr": game["away_team"]["abbr"],
        "status": "live" if game["status_name"] == "STATUS_IN_PROGRESS" else "scheduled",
    }
    if kalshi_event_ticker:
        row["kalshi_event_ticker"] = kalshi_event_ticker
    if game.get("start_time"):
        row["tip_off_time"] = game["start_time"]

    result = supabase.table("cbb_games").upsert(
        row, on_conflict="espn_game_id"
    ).execute()

    if result.data:
        return result.data[0]["game_id"]
    return None


def write_game_state(game_id: str, game: dict, wp: dict,
                     home_bid: int, home_ask: int, away_bid: int, away_ask: int):
    score_diff = game["home_team"]["score"] - game["away_team"]["score"]
    home_edge = calculate_edge(wp["home_win_pct"], home_ask) if home_ask else 0
    away_edge = calculate_edge(wp["away_win_pct"], away_ask) if away_ask else 0

    supabase.table("cbb_game_states").insert({
        "game_id": game_id,
        "espn_game_id": game["espn_game_id"],
        "score_home": game["home_team"]["score"],
        "score_away": game["away_team"]["score"],
        "score_differential": score_diff,
        "minutes_remaining": game["minutes_remaining"],
        "half": game["half"],
        "espn_home_win_prob": wp["home_win_pct"],
        "espn_away_win_prob": wp["away_win_pct"],
        "kalshi_home_yes_bid": home_bid,
        "kalshi_home_yes_ask": home_ask,
        "kalshi_away_yes_bid": away_bid,
        "kalshi_away_yes_ask": away_ask,
        "home_edge": home_edge,
        "away_edge": away_edge,
    }).execute()


def log_signal(game_id: str, game: dict, team_id: str, team_name: str,
               wp: float, ask: int, edge: float, action: str, position_id: str = None):
    supabase.table("cbb_signals").insert({
        "game_id": game_id,
        "espn_game_id": game["espn_game_id"],
        "team_espn_id": team_id,
        "team_name": team_name,
        "half": game["half"],
        "minutes_remaining": game["minutes_remaining"],
        "score_differential": game["home_team"]["score"] - game["away_team"]["score"],
        "espn_win_prob": wp,
        "kalshi_yes_ask": ask,
        "edge": edge,
        "action_taken": action,
        "position_id": position_id,
    }).execute()


def update_daily_pnl(net_pnl_cents: int, won: bool):
    today = date.today().isoformat()
    existing = supabase.table("cbb_daily_pnl") \
        .select("*") \
        .eq("date", today) \
        .maybe_single() \
        .execute()

    if existing.data:
        row = existing.data
        supabase.table("cbb_daily_pnl").update({
            "trades_exited": row["trades_exited"] + 1,
            "wins": row["wins"] + (1 if won else 0),
            "losses": row["losses"] + (0 if won else 1),
            "net_pnl_cents": row["net_pnl_cents"] + net_pnl_cents,
            "net_pnl_dollars": (row["net_pnl_cents"] + net_pnl_cents) / 100,
            "paper_mode": config.PAPER_TRADING,
        }).eq("date", today).execute()
    else:
        supabase.table("cbb_daily_pnl").insert({
            "date": today,
            "trades_exited": 1,
            "wins": 1 if won else 0,
            "losses": 0 if won else 1,
            "net_pnl_cents": net_pnl_cents,
            "net_pnl_dollars": net_pnl_cents / 100,
            "paper_mode": config.PAPER_TRADING,
        }).execute()


def write_health(loop_count: int, live_games: int, open_positions: int, error: str = None):
    supabase.table("cbb_worker_health").insert({
        "loop_count": loop_count,
        "live_games": live_games,
        "open_positions": open_positions,
        "paper_mode": config.PAPER_TRADING,
        "error_msg": error,
    }).execute()


def log_unmapped(raw_name: str, event_ticker: str):
    """Upsert an unmapped team occurrence."""
    existing = supabase.table("cbb_unmapped_teams") \
        .select("id, occurrence_count") \
        .eq("kalshi_raw_name", raw_name) \
        .maybe_single() \
        .execute()

    if existing.data:
        supabase.table("cbb_unmapped_teams").update({
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "occurrence_count": existing.data["occurrence_count"] + 1,
        }).eq("id", existing.data["id"]).execute()
    else:
        supabase.table("cbb_unmapped_teams").insert({
            "kalshi_raw_name": raw_name,
            "kalshi_event_ticker": event_ticker,
        }).execute()


# ── Entry logic ───────────────────────────────────────────────────────

def try_enter_position(
    game: dict,
    game_id: str,
    kalshi_event: dict,
    team: dict,            # home_team or away_team dict
    espn_win_prob: float,
    kalshi_ask_cents: int,
    kalshi_market: dict,
    bankroll_dollars: float,
    open_position_count: int,
    stop_loss_active: bool,
):
    edge = calculate_edge(espn_win_prob, kalshi_ask_cents)
    is_mapped = lookup_team(supabase, team["display_name"]) is not None or \
                lookup_team(supabase, team["short_name"]) is not None

    should_enter, reason = evaluate_entry(
        edge=edge,
        half=game["half"],
        minutes_remaining=game["minutes_remaining"],
        has_open_position=has_open_position(game["espn_game_id"]),
        is_mapped=is_mapped,
        open_position_count=open_position_count,
        max_concurrent=config.MAX_CONCURRENT_GAMES,
        stop_loss_active=stop_loss_active,
    )

    if not should_enter:
        log_signal(game_id, game, team["id"], team["display_name"],
                   espn_win_prob, kalshi_ask_cents, edge, reason)
        return

    # Size the trade
    bet_size = get_bet_size(edge, bankroll_dollars)
    if bet_size == 0:
        log_signal(game_id, game, team["id"], team["display_name"],
                   espn_win_prob, kalshi_ask_cents, edge, "BELOW_THRESHOLD")
        return

    contracts = get_contract_count(bet_size, kalshi_ask_cents)
    cost_basis_cents = kalshi_ask_cents * contracts

    # Place order
    order_result = kalshi_client.buy_yes(
        ticker=kalshi_market["ticker"],
        contracts=contracts,
        yes_ask_cents=kalshi_ask_cents,
    )
    if not order_result:
        log("ORDER_FAILED", {"ticker": kalshi_market["ticker"]})
        return

    order_id = order_result.get("order_id")

    # Record position
    pos_row = {
        "game_id": game_id,
        "espn_game_id": game["espn_game_id"],
        "kalshi_market_ticker": kalshi_market["ticker"],
        "kalshi_order_id": order_id if not config.PAPER_TRADING else None,
        "team_espn_id": team["id"],
        "team_name": team["display_name"],
        "is_paper_trade": config.PAPER_TRADING,
        "entry_half": game["half"],
        "entry_minutes_remaining": game["minutes_remaining"],
        "entry_score_differential": game["home_team"]["score"] - game["away_team"]["score"],
        "entry_espn_probability": espn_win_prob,
        "entry_kalshi_price_cents": kalshi_ask_cents,
        "entry_edge": edge,
        "contracts": contracts,
        "cost_basis_cents": cost_basis_cents,
        "status": "open",
    }
    pos_result = supabase.table("cbb_positions").insert(pos_row).execute()
    position_id = pos_result.data[0]["position_id"] if pos_result.data else None

    action = "TRADE_SIMULATED" if config.PAPER_TRADING else "TRADE_FIRED"
    log_signal(game_id, game, team["id"], team["display_name"],
               espn_win_prob, kalshi_ask_cents, edge, action, position_id)

    log("POSITION_OPENED", {
        "position_id": position_id,
        "team": team["display_name"],
        "edge": edge,
        "contracts": contracts,
        "cost_basis_dollars": cost_basis_cents / 100,
        "paper": config.PAPER_TRADING,
    })


# ── Exit logic ────────────────────────────────────────────────────────

def try_exit_position(
    position: dict,
    game: dict,
    espn_win_prob: float,
    kalshi_bid_cents: int,
    game_status: str,
):
    exit_reason = check_exit(
        position=position,
        current_espn_prob=espn_win_prob,
        current_kalshi_bid_cents=kalshi_bid_cents,
        half=game["half"],
        minutes_remaining=game["minutes_remaining"],
        game_status=game_status,
    )

    if not exit_reason:
        return

    log("EXIT_TRIGGERED", {
        "position_id": position["position_id"],
        "reason": exit_reason,
        "team": position["team_name"],
    })

    # Place sell order
    order_result = kalshi_client.sell_yes(
        ticker=position["kalshi_market_ticker"],
        contracts=position["contracts"],
        yes_bid_cents=kalshi_bid_cents,
    )

    exit_price = kalshi_bid_cents
    pnl = calculate_pnl(position, exit_price)

    # Update position row
    supabase.table("cbb_positions").update({
        "status": "closed",
        "exit_time": datetime.now(timezone.utc).isoformat(),
        "exit_kalshi_price_cents": exit_price,
        "exit_espn_probability": espn_win_prob,
        "exit_reason": exit_reason,
        "gross_pnl_cents": pnl["gross_pnl_cents"],
        "fee_cents": pnl["fee_cents"],
        "net_pnl_cents": pnl["net_pnl_cents"],
        "net_pnl_dollars": pnl["net_pnl_dollars"],
    }).eq("position_id", position["position_id"]).execute()

    # Update bankroll
    update_bankroll(pnl["net_pnl_cents"])

    # Update daily PnL
    update_daily_pnl(pnl["net_pnl_cents"], won=pnl["net_pnl_cents"] > 0)

    log("POSITION_CLOSED", {
        "position_id": position["position_id"],
        "team": position["team_name"],
        "exit_reason": exit_reason,
        "net_pnl_dollars": pnl["net_pnl_dollars"],
        "paper": config.PAPER_TRADING,
    })


# ── Main loop ─────────────────────────────────────────────────────────

def main_loop():
    loop_count = 0

    while True:
        loop_start = time.time()
        loop_count += 1
        log("LOOP_START", {"loop": loop_count})

        try:
            # ── 1. Check daily stop-loss ──────────────────────────────
            stop_loss_active = is_stop_loss_active()
            if stop_loss_active:
                log("STOP_LOSS_ACTIVE", {"sleeping": 3600})
                # Still evaluate exits for open positions even during stop-loss
                # but don't enter new positions

            # ── 2. Get current bankroll ───────────────────────────────
            bankroll = get_bankroll_dollars()

            # ── 3. Fetch ESPN scoreboard (one call, all D1 games) ─────
            all_games = get_live_games()
            live_games = [g for g in all_games if g["status_name"] == "STATUS_IN_PROGRESS"
                          or g.get("is_halftime")]

            log("ESPN_SCOREBOARD_FETCHED", {
                "total": len(all_games),
                "live": len(live_games),
            })

            # ── 4. Fetch all open Kalshi CBB events (one paginated call)
            kalshi_events = kalshi_client.get_live_cbb_events()
            log("KALSHI_EVENTS_FETCHED", {"count": len(kalshi_events)})

            # Build index: espn_team_id → kalshi_event + market info
            # We'll use team name matching via lookup_team
            # For each Kalshi event, parse both team names and match to ESPN IDs

            kalshi_index = {}  # espn_game_id → kalshi event + markets
            for ke in kalshi_events:
                parsed = parse_kalshi_title(ke["title"])
                if not parsed:
                    continue
                team_a_raw, team_b_raw = parsed
                team_a_info = lookup_team(supabase, team_a_raw)
                team_b_info = lookup_team(supabase, team_b_raw)

                if not team_a_info:
                    log_unmapped(team_a_raw, ke["event_ticker"])
                if not team_b_info:
                    log_unmapped(team_b_raw, ke["event_ticker"])

                if team_a_info and team_b_info:
                    kalshi_index[(team_a_info["espn_id"], team_b_info["espn_id"])] = ke
                    kalshi_index[(team_b_info["espn_id"], team_a_info["espn_id"])] = ke

            # ── 5. Get open positions ─────────────────────────────────
            open_positions = get_open_positions()
            open_position_count = len(open_positions)
            open_pos_by_game = {p["espn_game_id"]: p for p in open_positions}

            # Also check stop-loss threshold against current daily PnL
            if not stop_loss_active:
                stop_loss_active = check_and_set_stop_loss(bankroll)

            # ── 6. Process each live game ─────────────────────────────
            for game in live_games:
                try:
                    _process_game(
                        game=game,
                        kalshi_index=kalshi_index,
                        open_pos_by_game=open_pos_by_game,
                        open_position_count=open_position_count,
                        bankroll=bankroll,
                        stop_loss_active=stop_loss_active,
                    )
                except Exception as e:
                    log("GAME_PROCESSING_FAILED", {
                        "espn_game_id": game.get("espn_game_id"),
                        "error": str(e),
                    })

            # ── 7. Exit check for any open positions on finished games ─
            # Handle positions whose game isn't in the live list anymore
            live_ids = {g["espn_game_id"] for g in live_games}
            for pos in open_positions:
                if pos["espn_game_id"] not in live_ids:
                    # Game is over or not appearing — close position
                    try_exit_position(
                        position=pos,
                        game={"half": 2, "minutes_remaining": 0,
                              "home_team": {"score": 0}, "away_team": {"score": 0},
                              "espn_game_id": pos["espn_game_id"]},
                        espn_win_prob=0.0,
                        kalshi_bid_cents=0,
                        game_status="STATUS_FINAL",
                    )

            # ── 8. Write health heartbeat ─────────────────────────────
            write_health(loop_count, len(live_games), open_position_count)

        except Exception as e:
            log("MAIN_LOOP_ERROR", {"error": str(e), "loop": loop_count})
            write_health(loop_count, 0, 0, error=str(e))

        # ── Sleep remainder of 60s interval ──────────────────────────
        elapsed = time.time() - loop_start
        sleep_time = max(0, config.MAIN_LOOP_INTERVAL_SECONDS - elapsed)
        log("LOOP_END", {"loop": loop_count, "elapsed_s": round(elapsed, 1), "sleeping_s": round(sleep_time, 1)})
        time.sleep(sleep_time)


def _process_game(
    game: dict,
    kalshi_index: dict,
    open_pos_by_game: dict,
    open_position_count: int,
    bankroll: float,
    stop_loss_active: bool,
):
    espn_id = game["espn_game_id"]
    home = game["home_team"]
    away = game["away_team"]

    # Find matching Kalshi event
    kalshi_event = (
        kalshi_index.get((home["id"], away["id"])) or
        kalshi_index.get((away["id"], home["id"]))
    )

    if not kalshi_event:
        # No Kalshi market found — still upsert game and fetch WP for exit checks
        pass

    # Fetch ESPN win probability for this game
    wp = get_win_probability(espn_id)
    if not wp:
        log("ESPN_WP_UNAVAILABLE", {"espn_game_id": espn_id})
        return

    # Upsert game row
    game_id = upsert_game(
        game,
        kalshi_event_ticker=kalshi_event["event_ticker"] if kalshi_event else None
    )

    # Get Kalshi prices for both teams
    home_market = kalshi_client.find_win_market(kalshi_event, home["short_name"]) \
        if kalshi_event else None
    away_market = kalshi_client.find_win_market(kalshi_event, away["short_name"]) \
        if kalshi_event else None

    home_bid = home_market["yes_bid"] if home_market else 0
    home_ask = home_market["yes_ask"] if home_market else 0
    away_bid = away_market["yes_bid"] if away_market else 0
    away_ask = away_market["yes_ask"] if away_market else 0

    # Write game state snapshot
    if game_id:
        write_game_state(game_id, game, wp, home_bid, home_ask, away_bid, away_ask)

    # ── Exit check for existing open position on this game ────────────
    open_pos = open_pos_by_game.get(espn_id)
    if open_pos:
        # Determine which team's market we're in
        pos_team_id = open_pos["team_espn_id"]
        if pos_team_id == home["id"]:
            current_bid = home_bid
            current_espn_prob = wp["home_win_pct"]
        else:
            current_bid = away_bid
            current_espn_prob = wp["away_win_pct"]

        try_exit_position(
            position=open_pos,
            game=game,
            espn_win_prob=current_espn_prob,
            kalshi_bid_cents=current_bid,
            game_status=game["status_name"],
        )
        return  # one position per game — don't try to enter after exit check

    # ── Entry check ───────────────────────────────────────────────────
    if not kalshi_event or game.get("is_halftime"):
        return

    # Evaluate home team entry
    if home_market and home_ask > 0:
        try_enter_position(
            game=game,
            game_id=game_id,
            kalshi_event=kalshi_event,
            team=home,
            espn_win_prob=wp["home_win_pct"],
            kalshi_ask_cents=home_ask,
            kalshi_market=home_market,
            bankroll_dollars=bankroll,
            open_position_count=open_position_count,
            stop_loss_active=stop_loss_active,
        )

    # Evaluate away team entry (only if home wasn't entered this loop)
    if away_market and away_ask > 0 and not has_open_position(espn_id):
        try_enter_position(
            game=game,
            game_id=game_id,
            kalshi_event=kalshi_event,
            team=away,
            espn_win_prob=wp["away_win_pct"],
            kalshi_ask_cents=away_ask,
            kalshi_market=away_market,
            bankroll_dollars=bankroll,
            open_position_count=open_position_count,
            stop_loss_active=stop_loss_active,
        )


# ── Entry point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    bootstrap()
    main_loop()
```

---

## 12. Railway Deployment

### 12.1 Service Configuration

The Railway service `cbb-worker` already exists and is connected to the `cbb-trading` GitHub repo. Configure it as follows in Railway → service settings:

| Setting | Value |
|---|---|
| **Root Directory** | `cbb` |
| **Custom Start Command** | `python main.py` |
| **Watch Paths** | `cbb/**` and `supabase/migrations/**` |

Watch paths ensure that pushing changes to `/dashboard` does not trigger a redeploy of the engine.

### 12.2 Environment Variables

In Railway → `cbb-worker` → Variables tab, add:

```
SUPABASE_URL                  ← from Supabase project settings → API → Project URL
SUPABASE_SERVICE_ROLE_KEY     ← from Supabase project settings → API → service_role key
CBB_PAPER_TRADING             true
CBB_BANKROLL                  500
CBB_MAX_CONCURRENT_GAMES      4
CBB_DAILY_STOP_LOSS_PCT       0.05
```

Do **not** add `KALSHI_API_KEY_ID` or `KALSHI_PRIVATE_KEY_PEM` yet. Leave them unset for the full paper trading phase.

### 12.3 First Deploy Sequence

The migration must be run in Supabase **before** the first Railway deploy fires, otherwise the engine crashes on startup trying to seed tables that don't exist.

Correct order:
1. Run `supabase/migrations/0001_cbb_schema.sql` in Supabase SQL Editor
2. Push code to `cbb-trading` GitHub repo
3. Railway auto-deploys from the push (or trigger manually)
4. Watch logs for `CBB_WORKER_START` and `BANKROLL_INITIALIZED`

### 12.4 Health Monitoring

The engine writes a row to `cbb_worker_health` on every loop. The dashboard (Spec 3) reads the most recent row. If the `ts` field is more than 3 minutes old, the dashboard shows a "Worker Offline" warning.

### 12.5 Suspending for Offseason

The CBB season ends mid-March and resumes in November. Suspend the `cbb-worker` service from the Railway dashboard (service → Settings → Suspend) during the offseason. No code changes needed. Resume it the day before the season tips off.

---

## 13. Verification Checklist

Before marking this spec complete:

- [ ] `python main.py` (run from inside `cbb/`) starts without import errors **with no Kalshi env vars set**
- [ ] On first run: `BANKROLL_INITIALIZED` log appears
- [ ] Team mapping seed runs silently on startup
- [ ] ESPN scoreboard fetch returns games (test with live season)
- [ ] Kalshi events fetch returns results and parses without crash — **no credentials needed**
- [ ] `normalize()` in `mapping.py` is identical to `seed_teams.normalize()`
- [ ] Paper trades write to `cbb_positions` with `is_paper_trade=true`
- [ ] Exit logic fires correctly when a test position is manually inserted
- [ ] `cbb_worker_health` has a new row every ~60 seconds
- [ ] `cbb_daily_pnl` has a row for today after at least one position closes
- [ ] No position is opened during halftime (`is_halftime=True`)
- [ ] No position is opened when `stop_loss_active=True`
- [ ] All Supabase writes use retry logic from `utils.retry()`
- [ ] Starting with `CBB_PAPER_TRADING=false` and no `KALSHI_API_KEY_ID` exits with `FATAL_ERROR` log and non-zero exit code
- [ ] `_private_key` is `None` at module load when `KALSHI_PRIVATE_KEY_PEM` is unset — no `AttributeError` raised

---

*End of Spec 2 of 3*
