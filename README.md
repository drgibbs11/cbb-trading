# CBB Trading System

Live college basketball trading engine for Kalshi markets. Watches ESPN win probabilities vs Kalshi YES prices, enters on divergence > 10%, exits on convergence/reversal/time.

## Architecture

- **Engine**: Python 3.11+ (Railway)
- **Database**: Supabase (PostgreSQL)
- **Dashboard**: React SPA → Netlify (Spec 3)

## Repository Structure

```
/cbb-trading
  /cbb                    ← Engine (Railway)
    main.py              ← Entry point
    config.py            ← Constants & env vars
    espn.py              ← ESPN API client
    kalshi.py            ← Kalshi API client
    signals.py           ← Entry logic & edge calc
    positions.py         ← Exit logic & PnL
    mapping.py           ← Team name normalization
    seed_teams.py        ← Team mapping seed data
    utils.py             ← Logging & retry helpers
    requirements.txt
  /supabase
    /migrations
      0001_cbb_schema.sql
  /dashboard             ← Spec 3 (Netlify SPA)
  README.md
```

## Quick Start

1. **Run migration** in Supabase SQL Editor:
   ```sql
   -- Paste contents of supabase/migrations/0001_cbb_schema.sql
   ```

2. **Seed team mapping**:
   ```bash
   cd cbb
   python seed_teams.py
   ```

3. **Set env vars** in Railway:
   ```
   SUPABASE_URL=
   SUPABASE_SERVICE_ROLE_KEY=
   CBB_PAPER_TRADING=true
   CBB_BANKROLL=500
   CBB_MAX_CONCURRENT_GAMES=4
   ```

4. **Deploy**:
   ```bash
   git push origin main
   ```

## Entry Criteria

- Edge (ESPN W% - Kalshi Ask) ≥ 10%
- ≥ 5 minutes remaining in game
- H2: ≥ 8 minutes remaining
- Max 4 concurrent positions
- 1 position per game max

## Exit Triggers

- **Game over** (always)
- **Overtime** (OT unpredictable)
- **Halftime** (H1 positions exit at H2)
- **Signal reversal** (ESPN dropped 20pp below entry)
- **Convergence** (Kalshi price within 4pp of ESPN)
- **Time expiry** (≤ 5 min left)
- **Daily stop-loss** (5% of bankroll)

## Bet Sizing

| Edge | Size |
|------|------|
| ≥25% | $5 |
| ≥20% | $3 |
| ≥15% | $2 |
| ≥10% | $1 |

## Paper vs Live

Paper trading uses `CBB_PAPER_TRADING=true`. No Kalshi auth required.

Live trading requires:
- `KALSHI_API_KEY_ID`
- `KALSHI_PRIVATE_KEY_PEM` (RSA private key, `\n` escaped)

## Status

- Spec 1 (Database): ✅ Complete
- Spec 2 (Engine): ✅ Complete
- Spec 3 (Dashboard): ⏳ Pending
