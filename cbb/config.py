import os
import sys

# ── Trading mode ──────────────────────────────────────────────────────
PAPER_TRADING = os.environ.get("CBB_PAPER_TRADING", "true").lower() == "true"
BANKROLL_DOLLARS = float(os.environ.get("CBB_BANKROLL", "500"))
MAX_CONCURRENT_GAMES = int(os.environ.get("CBB_MAX_CONCURRENT_GAMES", "4"))
DAILY_STOP_LOSS_PCT = float(os.environ.get("CBB_DAILY_STOP_LOSS_PCT", "0.05"))

# ── Kalshi credentials (optional — only required for live trading) ─────
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
