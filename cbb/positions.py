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
