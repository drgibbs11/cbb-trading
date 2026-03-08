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
