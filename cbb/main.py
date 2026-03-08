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
    from seed_teams import seed as seed_team_mapping
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
            live_ids = {g["espn_game_id"] for g in live_games}
            for pos in open_positions:
                if pos["espn_game_id"] not in live_ids:
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
        return

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
