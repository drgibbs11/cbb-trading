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
