-- =============================================================
-- CBB Trading System — Schema Migration 0001
-- =============================================================

-- ── Team name mapping ─────────────────────────────────────────
-- Bridges Kalshi event title names ↔ ESPN team IDs.
-- Multiple kalshi_name rows can map to the same espn_id (aliases).
-- Populated by seed_teams.py on each deploy.

CREATE TABLE IF NOT EXISTS cbb_team_mapping (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  kalshi_name   TEXT        UNIQUE NOT NULL,   -- normalized lowercase key
  espn_id       TEXT        NOT NULL,
  espn_name     TEXT        NOT NULL,
  espn_abbr     TEXT,
  conference    TEXT,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ctm_kalshi  ON cbb_team_mapping(kalshi_name);
CREATE INDEX IF NOT EXISTS idx_ctm_espn_id ON cbb_team_mapping(espn_id);


-- ── Games ──────────────────────────────────────────────────────
-- One row per game. Created when the game is first detected as
-- scheduled or live. Updated through game completion.

CREATE TABLE IF NOT EXISTS cbb_games (
  game_id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  espn_game_id            TEXT        UNIQUE NOT NULL,
  kalshi_event_ticker     TEXT,
  home_team_espn_id       TEXT        NOT NULL,
  away_team_espn_id       TEXT        NOT NULL,
  home_team_name          TEXT        NOT NULL,
  away_team_name          TEXT        NOT NULL,
  home_team_abbr          TEXT,
  away_team_abbr          TEXT,
  conference_home         TEXT,
  conference_away         TEXT,
  tip_off_time            TIMESTAMPTZ,
  pre_game_home_kalshi_prob  NUMERIC(5,4),   -- Kalshi YES ask price at T-10min
  pre_game_away_kalshi_prob  NUMERIC(5,4),
  pre_game_spread         NUMERIC(5,2),       -- positive = home favored
  status                  TEXT        DEFAULT 'scheduled',
    -- scheduled | live | halftime | final | postponed
  final_score_home        INTEGER,
  final_score_away        INTEGER,
  winner_espn_id          TEXT,               -- populated on STATUS_FINAL
  is_neutral_site         BOOLEAN     DEFAULT FALSE,
  created_at              TIMESTAMPTZ DEFAULT NOW(),
  updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cbb_games_status     ON cbb_games(status);
CREATE INDEX IF NOT EXISTS idx_cbb_games_tip_off    ON cbb_games(tip_off_time);
CREATE INDEX IF NOT EXISTS idx_cbb_games_espn_id    ON cbb_games(espn_game_id);


-- ── Game states ────────────────────────────────────────────────
-- Time-series snapshots written every 60s during live games.
-- Used for signal replay, analytics, and dashboard sparklines.

CREATE TABLE IF NOT EXISTS cbb_game_states (
  id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id               UUID        REFERENCES cbb_games(game_id) ON DELETE CASCADE,
  espn_game_id          TEXT        NOT NULL,
  snapshot_time         TIMESTAMPTZ DEFAULT NOW(),
  score_home            INTEGER,
  score_away            INTEGER,
  score_differential    INTEGER,    -- home minus away (positive = home leading)
  minutes_remaining     NUMERIC(5,2),
  half                  INTEGER,    -- 1, 2, or 3+ for OT
  espn_home_win_prob    NUMERIC(5,4),
  espn_away_win_prob    NUMERIC(5,4),
  kalshi_home_yes_bid   INTEGER,    -- in cents (0–100)
  kalshi_home_yes_ask   INTEGER,
  kalshi_away_yes_bid   INTEGER,
  kalshi_away_yes_ask   INTEGER,
  home_edge             NUMERIC(5,4),   -- espn_home_win_prob - (kalshi_home_yes_ask/100)
  away_edge             NUMERIC(5,4)
);

CREATE INDEX IF NOT EXISTS idx_cbb_gs_game_id   ON cbb_game_states(game_id);
CREATE INDEX IF NOT EXISTS idx_cbb_gs_espn_id   ON cbb_game_states(espn_game_id);
CREATE INDEX IF NOT EXISTS idx_cbb_gs_snap_time ON cbb_game_states(snapshot_time);


-- ── Positions ──────────────────────────────────────────────────
-- One row per trade entered. Updated in-place on exit.

CREATE TABLE IF NOT EXISTS cbb_positions (
  position_id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id                   UUID        REFERENCES cbb_games(game_id) ON DELETE SET NULL,
  espn_game_id              TEXT        NOT NULL,
  kalshi_market_ticker      TEXT        NOT NULL,
  kalshi_order_id           TEXT,       -- populated on live trades; null in paper mode
  team_espn_id              TEXT        NOT NULL,
  team_name                 TEXT        NOT NULL,
  is_paper_trade            BOOLEAN     DEFAULT TRUE,

  -- Entry
  entry_time                TIMESTAMPTZ DEFAULT NOW(),
  entry_half                INTEGER,
  entry_minutes_remaining   NUMERIC(5,2),
  entry_score_differential  INTEGER,    -- score at time of entry (home - away)
  entry_espn_probability    NUMERIC(5,4),
  entry_kalshi_price_cents  INTEGER,    -- yes_ask at entry
  entry_edge                NUMERIC(5,4),
  contracts                 INTEGER     NOT NULL,
  cost_basis_cents          INTEGER     NOT NULL,   -- entry_price_cents * contracts

  -- Exit
  status                    TEXT        DEFAULT 'open',
    -- open | closed | cancelled
  exit_time                 TIMESTAMPTZ,
  exit_kalshi_price_cents   INTEGER,    -- yes_bid at exit
  exit_espn_probability     NUMERIC(5,4),
  exit_reason               TEXT,
    -- CONVERGENCE | SIGNAL_REVERSAL | TIME_EXPIRY | HALFTIME |
    -- OVERTIME | GAME_OVER | STOP_LOSS | MANUAL

  -- PnL
  gross_pnl_cents           INTEGER,    -- (exit_price - entry_price) * contracts
  fee_cents                 INTEGER     DEFAULT 0,
  net_pnl_cents             INTEGER,    -- gross - fee
  net_pnl_dollars           NUMERIC(10,4),
  hold_duration_seconds     INTEGER,    -- exit_time - entry_time

  created_at                TIMESTAMPTZ DEFAULT NOW(),
  updated_at                TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cbb_pos_game_id   ON cbb_positions(game_id);
CREATE INDEX IF NOT EXISTS idx_cbb_pos_status    ON cbb_positions(status);
CREATE INDEX IF NOT EXISTS idx_cbb_pos_entry     ON cbb_positions(entry_time);
CREATE INDEX IF NOT EXISTS idx_cbb_pos_paper     ON cbb_positions(is_paper_trade);
CREATE INDEX IF NOT EXISTS idx_cbb_pos_team      ON cbb_positions(team_espn_id);


-- ── Signals ────────────────────────────────────────────────────
-- Every signal evaluation — whether a trade fired or not.
-- Critical for understanding why trades were or weren't taken.

CREATE TABLE IF NOT EXISTS cbb_signals (
  signal_id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id               UUID        REFERENCES cbb_games(game_id) ON DELETE SET NULL,
  espn_game_id          TEXT        NOT NULL,
  signal_time           TIMESTAMPTZ DEFAULT NOW(),
  team_espn_id          TEXT        NOT NULL,
  team_name             TEXT        NOT NULL,
  half                  INTEGER,
  minutes_remaining     NUMERIC(5,2),
  score_differential    INTEGER,
  espn_win_prob         NUMERIC(5,4),
  kalshi_yes_ask        INTEGER,    -- cents
  edge                  NUMERIC(5,4),
  action_taken          TEXT        NOT NULL,
    -- TRADE_FIRED | TRADE_SIMULATED | BELOW_THRESHOLD |
    -- POSITION_ALREADY_OPEN | ONE_POSITION_RULE | CAP_REACHED |
    -- UNMAPPED_TEAM | NO_KALSHI_MARKET | HALFTIME_BLOCKED |
    -- TIME_BLOCKED | STOP_LOSS_ACTIVE | ESPN_WP_UNAVAILABLE
  position_id           UUID        REFERENCES cbb_positions(position_id) ON DELETE SET NULL,
  notes                 TEXT        -- optional free text for debugging
);

CREATE INDEX IF NOT EXISTS idx_cbb_sig_game_id ON cbb_signals(game_id);
CREATE INDEX IF NOT EXISTS idx_cbb_sig_time    ON cbb_signals(signal_time);
CREATE INDEX IF NOT EXISTS idx_cbb_sig_action  ON cbb_signals(action_taken);


-- ── Daily PnL summary ─────────────────────────────────────────
-- One row per calendar day. Updated incrementally as positions close.
-- Used for stop-loss check and dashboard summary tiles.

CREATE TABLE IF NOT EXISTS cbb_daily_pnl (
  id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  date                DATE        UNIQUE NOT NULL,
  trades_entered      INTEGER     DEFAULT 0,
  trades_exited       INTEGER     DEFAULT 0,
  wins                INTEGER     DEFAULT 0,   -- closed with positive net PnL
  losses              INTEGER     DEFAULT 0,
  pushes              INTEGER     DEFAULT 0,   -- net PnL = 0
  gross_pnl_cents     INTEGER     DEFAULT 0,
  fees_cents          INTEGER     DEFAULT 0,
  net_pnl_cents       INTEGER     DEFAULT 0,
  net_pnl_dollars     NUMERIC(10,4) DEFAULT 0,
  paper_mode          BOOLEAN     DEFAULT TRUE,
  stop_loss_hit       BOOLEAN     DEFAULT FALSE,
  stop_loss_hit_at    TIMESTAMPTZ,
  updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cbb_dpnl_date ON cbb_daily_pnl(date);


-- ── Bankroll ──────────────────────────────────────────────────
-- Single-row tracker for current bankroll balance.
-- Separate rows for paper vs live. Updated on each position close.

CREATE TABLE IF NOT EXISTS cbb_bankroll (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  balance_cents   INTEGER     NOT NULL,       -- current balance in cents
  balance_dollars NUMERIC(10,4) GENERATED ALWAYS AS (balance_cents / 100.0) STORED,
  is_paper        BOOLEAN     DEFAULT TRUE,
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Ensure only one row per mode
CREATE UNIQUE INDEX IF NOT EXISTS idx_cbb_bankroll_mode ON cbb_bankroll(is_paper);


-- ── Worker health ─────────────────────────────────────────────
-- Heartbeat rows written by the engine every loop iteration.
-- Dashboard uses this to show "last seen" status.

CREATE TABLE IF NOT EXISTS cbb_worker_health (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  ts            TIMESTAMPTZ DEFAULT NOW(),
  loop_count    INTEGER,
  live_games    INTEGER,    -- number of games in STATUS_IN_PROGRESS this iteration
  open_positions INTEGER,
  paper_mode    BOOLEAN,
  error_msg     TEXT        -- null if healthy
);

CREATE INDEX IF NOT EXISTS idx_cbb_health_ts ON cbb_worker_health(ts DESC);

-- Trim old health rows automatically (keep 7 days)
-- Run this periodically from the engine or a Supabase scheduled function:
-- DELETE FROM cbb_worker_health WHERE ts < NOW() - INTERVAL '7 days';


-- ── Unmapped teams log ────────────────────────────────────────
-- When the engine sees a Kalshi team name it can't match,
-- it logs here. Use this to identify gaps in the mapping table.

CREATE TABLE IF NOT EXISTS cbb_unmapped_teams (
  id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  kalshi_raw_name     TEXT        NOT NULL,
  kalshi_event_ticker TEXT,
  first_seen          TIMESTAMPTZ DEFAULT NOW(),
  last_seen           TIMESTAMPTZ DEFAULT NOW(),
  occurrence_count    INTEGER     DEFAULT 1
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_cbb_unmapped_name ON cbb_unmapped_teams(kalshi_raw_name);
