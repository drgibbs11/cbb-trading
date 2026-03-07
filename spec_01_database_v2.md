# CBB Worker — Spec 1 of 3: Database & Team Mapping
**For: OpenClaw Agent (Kimi K2.5)**
**Version: 2.1 — March 2026**
**Implement this spec completely before moving to Spec 2 or Spec 3.**

---

## 0. READ THIS FIRST

This is the first of three spec documents for the CBB live trading system. Your job in this spec is:

1. Create the full Supabase schema migration
2. Populate the `team_name_mapping` table with all D1 team entries
3. Create a seed script that runs on every deploy to keep the table in sync

Do not write any trading logic here. Do not touch ESPN or Kalshi APIs here. Only schema + seed data.

When this spec is complete, the following must be true:
- All tables exist in Supabase
- All indexes exist
- `team_name_mapping` is populated with every row defined in Section 3
- A standalone seed script exists at `cbb/seed_teams.py` that can re-run safely (upsert, not insert)

---

## 1. Repository

**GitHub repo:** `cbb-trading` (standalone repo — not a monorepo, no weather worker here)

**Local structure after setup:**
```
/cbb-trading            ← repo root
  /cbb                  ← all engine code (Spec 2 lives here)
  /supabase
    /migrations
      0001_cbb_schema.sql   ← the migration file you create in this spec
  /dashboard            ← Netlify dashboard (Spec 3 lives here)
  .gitignore
  README.md
```

Create the `supabase/migrations/` directory now. The migration filename is `0001_cbb_schema.sql` — this is the first and only migration in this repo (no weather migrations here).

Migration file: `supabase/migrations/0001_cbb_schema.sql`
Seed script: `cbb/seed_teams.py`

**Run the migration manually in Supabase before the first Railway deploy.** The engine will crash on startup if tables don't exist. Go to Supabase → SQL Editor → paste and run the full migration file.

---

## 2. Full Schema Migration

File: `supabase/migrations/0001_cbb_schema.sql`

Execute this entire file in order. Every statement uses `IF NOT EXISTS` so it is safe to re-run.

```sql
-- =============================================================
-- CBB Trading System — Schema Migration 0001
-- =============================================================

-- ── Team name mapping ─────────────────────────────────────────
-- Bridges Kalshi event title names ↔ ESPN team IDs.
-- Multiple kalshi_name rows can map to the same espn_id (aliases).
-- Populated by seed_teams.py on each deploy.

CREATE TABLE IF NOT EXISTS team_name_mapping (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  kalshi_name   TEXT        UNIQUE NOT NULL,   -- normalized lowercase key
  espn_id       TEXT        NOT NULL,
  espn_name     TEXT        NOT NULL,
  espn_abbr     TEXT,
  conference    TEXT,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tmm_kalshi  ON team_name_mapping(kalshi_name);
CREATE INDEX IF NOT EXISTS idx_tmm_espn_id ON team_name_mapping(espn_id);


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
```

---

## 3. Team Mapping Seed Data

File: `/cbb/seed_teams.py`

This script upserts every row in the mapping table. Run it on every deploy. It is safe to run multiple times — uses `ON CONFLICT (kalshi_name) DO UPDATE`.

The `kalshi_name` column is always **lowercase, trimmed, punctuation-stripped (except `&`)**. This must match the normalization function in the engine exactly.

```python
#!/usr/bin/env python3
"""
seed_teams.py — Populate team_name_mapping in Supabase.
Run on every deploy: python cbb/seed_teams.py
"""

import os
import sys
from supabase import create_client, Client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Each row: (kalshi_name, espn_id, espn_name, espn_abbr, conference)
# kalshi_name must be: lowercase, trimmed, no punctuation except &, single spaces
TEAMS = [

    # ── ACC ──────────────────────────────────────────────────────────
    ("duke",                    "150",  "Duke Blue Devils",              "DUKE",  "ACC"),
    ("duke blue devils",        "150",  "Duke Blue Devils",              "DUKE",  "ACC"),
    ("north carolina",          "153",  "North Carolina Tar Heels",      "UNC",   "ACC"),
    ("unc",                     "153",  "North Carolina Tar Heels",      "UNC",   "ACC"),
    ("tar heels",               "153",  "North Carolina Tar Heels",      "UNC",   "ACC"),
    ("virginia",                "258",  "Virginia Cavaliers",            "UVA",   "ACC"),
    ("uva",                     "258",  "Virginia Cavaliers",            "UVA",   "ACC"),
    ("virginia cavaliers",      "258",  "Virginia Cavaliers",            "UVA",   "ACC"),
    ("nc state",                "152",  "NC State Wolfpack",             "NCST",  "ACC"),
    ("nc st",                   "152",  "NC State Wolfpack",             "NCST",  "ACC"),
    ("north carolina state",    "152",  "NC State Wolfpack",             "NCST",  "ACC"),
    ("ncsu",                    "152",  "NC State Wolfpack",             "NCST",  "ACC"),
    ("clemson",                 "228",  "Clemson Tigers",                "CLEM",  "ACC"),
    ("miami",                   "2390", "Miami Hurricanes",              "MIA",   "ACC"),
    ("miami fl",                "2390", "Miami Hurricanes",              "MIA",   "ACC"),
    ("miami fl hurricanes",     "2390", "Miami Hurricanes",              "MIA",   "ACC"),
    ("florida state",           "52",   "Florida State Seminoles",       "FSU",   "ACC"),
    ("fsu",                     "52",   "Florida State Seminoles",       "FSU",   "ACC"),
    ("georgia tech",            "59",   "Georgia Tech Yellow Jackets",   "GT",    "ACC"),
    ("ga tech",                 "59",   "Georgia Tech Yellow Jackets",   "GT",    "ACC"),
    ("yellow jackets",          "59",   "Georgia Tech Yellow Jackets",   "GT",    "ACC"),
    ("wake forest",             "154",  "Wake Forest Demon Deacons",     "WAKE",  "ACC"),
    ("boston college",          "103",  "Boston College Eagles",         "BC",    "ACC"),
    ("bc",                      "103",  "Boston College Eagles",         "BC",    "ACC"),
    ("pittsburgh",              "221",  "Pittsburgh Panthers",           "PITT",  "ACC"),
    ("pitt",                    "221",  "Pittsburgh Panthers",           "PITT",  "ACC"),
    ("virginia tech",           "259",  "Virginia Tech Hokies",          "VT",    "ACC"),
    ("vt",                      "259",  "Virginia Tech Hokies",          "VT",    "ACC"),
    ("hokies",                  "259",  "Virginia Tech Hokies",          "VT",    "ACC"),
    ("louisville",              "97",   "Louisville Cardinals",          "LOU",   "ACC"),
    ("notre dame",              "87",   "Notre Dame Fighting Irish",     "ND",    "ACC"),
    ("fighting irish",          "87",   "Notre Dame Fighting Irish",     "ND",    "ACC"),
    ("syracuse",                "183",  "Syracuse Orange",               "SYR",   "ACC"),
    ("stanford",                "24",   "Stanford Cardinal",             "STAN",  "ACC"),
    ("cal",                     "25",   "California Golden Bears",       "CAL",   "ACC"),
    ("california",              "25",   "California Golden Bears",       "CAL",   "ACC"),
    ("golden bears",            "25",   "California Golden Bears",       "CAL",   "ACC"),
    ("smu",                     "2567", "SMU Mustangs",                  "SMU",   "ACC"),
    ("southern methodist",      "2567", "SMU Mustangs",                  "SMU",   "ACC"),

    # ── Big Ten ───────────────────────────────────────────────────────
    ("michigan",                "130",  "Michigan Wolverines",           "MICH",  "Big Ten"),
    ("michigan wolverines",     "130",  "Michigan Wolverines",           "MICH",  "Big Ten"),
    ("wolverines",              "130",  "Michigan Wolverines",           "MICH",  "Big Ten"),
    ("michigan state",          "127",  "Michigan State Spartans",       "MSU",   "Big Ten"),
    ("michigan st",             "127",  "Michigan State Spartans",       "MSU",   "Big Ten"),
    ("msu",                     "127",  "Michigan State Spartans",       "MSU",   "Big Ten"),
    ("spartans",                "127",  "Michigan State Spartans",       "MSU",   "Big Ten"),
    ("ohio state",              "194",  "Ohio State Buckeyes",           "OSU",   "Big Ten"),
    ("ohio st",                 "194",  "Ohio State Buckeyes",           "OSU",   "Big Ten"),
    ("osu",                     "194",  "Ohio State Buckeyes",           "OSU",   "Big Ten"),
    ("buckeyes",                "194",  "Ohio State Buckeyes",           "OSU",   "Big Ten"),
    ("indiana",                 "84",   "Indiana Hoosiers",              "IND",   "Big Ten"),
    ("hoosiers",                "84",   "Indiana Hoosiers",              "IND",   "Big Ten"),
    ("purdue",                  "2509", "Purdue Boilermakers",           "PUR",   "Big Ten"),
    ("boilermakers",            "2509", "Purdue Boilermakers",           "PUR",   "Big Ten"),
    ("iowa",                    "2294", "Iowa Hawkeyes",                 "IOWA",  "Big Ten"),
    ("hawkeyes",                "2294", "Iowa Hawkeyes",                 "IOWA",  "Big Ten"),
    ("illinois",                "356",  "Illinois Fighting Illini",      "ILL",   "Big Ten"),
    ("fighting illini",         "356",  "Illinois Fighting Illini",      "ILL",   "Big Ten"),
    ("maryland",                "120",  "Maryland Terrapins",            "MD",    "Big Ten"),
    ("terrapins",               "120",  "Maryland Terrapins",            "MD",    "Big Ten"),
    ("terps",                   "120",  "Maryland Terrapins",            "MD",    "Big Ten"),
    ("minnesota",               "135",  "Minnesota Golden Gophers",      "MINN",  "Big Ten"),
    ("gophers",                 "135",  "Minnesota Golden Gophers",      "MINN",  "Big Ten"),
    ("nebraska",                "158",  "Nebraska Cornhuskers",          "NEB",   "Big Ten"),
    ("cornhuskers",             "158",  "Nebraska Cornhuskers",          "NEB",   "Big Ten"),
    ("northwestern",            "77",   "Northwestern Wildcats",         "NW",    "Big Ten"),
    ("penn state",              "213",  "Penn State Nittany Lions",      "PSU",   "Big Ten"),
    ("penn st",                 "213",  "Penn State Nittany Lions",      "PSU",   "Big Ten"),
    ("psu",                     "213",  "Penn State Nittany Lions",      "PSU",   "Big Ten"),
    ("rutgers",                 "164",  "Rutgers Scarlet Knights",       "RUTG",  "Big Ten"),
    ("scarlet knights",         "164",  "Rutgers Scarlet Knights",       "RUTG",  "Big Ten"),
    ("wisconsin",               "275",  "Wisconsin Badgers",             "WIS",   "Big Ten"),
    ("badgers",                 "275",  "Wisconsin Badgers",             "WIS",   "Big Ten"),
    ("ucla",                    "26",   "UCLA Bruins",                   "UCLA",  "Big Ten"),
    ("bruins",                  "26",   "UCLA Bruins",                   "UCLA",  "Big Ten"),
    ("usc",                     "30",   "USC Trojans",                   "USC",   "Big Ten"),
    ("trojans",                 "30",   "USC Trojans",                   "USC",   "Big Ten"),
    ("oregon",                  "2483", "Oregon Ducks",                  "ORE",   "Big Ten"),
    ("ducks",                   "2483", "Oregon Ducks",                  "ORE",   "Big Ten"),
    ("washington",              "264",  "Washington Huskies",            "WASH",  "Big Ten"),
    ("huskies",                 "264",  "Washington Huskies",            "WASH",  "Big Ten"),

    # ── Big 12 ────────────────────────────────────────────────────────
    ("kansas",                  "2305", "Kansas Jayhawks",               "KU",    "Big 12"),
    ("ku",                      "2305", "Kansas Jayhawks",               "KU",    "Big 12"),
    ("jayhawks",                "2305", "Kansas Jayhawks",               "KU",    "Big 12"),
    ("baylor",                  "239",  "Baylor Bears",                  "BAY",   "Big 12"),
    ("texas",                   "251",  "Texas Longhorns",               "TEX",   "Big 12"),
    ("longhorns",               "251",  "Texas Longhorns",               "TEX",   "Big 12"),
    ("texas tech",              "2641", "Texas Tech Red Raiders",        "TTU",   "Big 12"),
    ("ttu",                     "2641", "Texas Tech Red Raiders",        "TTU",   "Big 12"),
    ("red raiders",             "2641", "Texas Tech Red Raiders",        "TTU",   "Big 12"),
    ("oklahoma",                "201",  "Oklahoma Sooners",              "OU",    "Big 12"),
    ("ou",                      "201",  "Oklahoma Sooners",              "OU",    "Big 12"),
    ("sooners",                 "201",  "Oklahoma Sooners",              "OU",    "Big 12"),
    ("oklahoma state",          "197",  "Oklahoma State Cowboys",        "OKST",  "Big 12"),
    ("oklahoma st",             "197",  "Oklahoma State Cowboys",        "OKST",  "Big 12"),
    ("okstate",                 "197",  "Oklahoma State Cowboys",        "OKST",  "Big 12"),
    ("iowa state",              "66",   "Iowa State Cyclones",           "ISU",   "Big 12"),
    ("iowa st",                 "66",   "Iowa State Cyclones",           "ISU",   "Big 12"),
    ("cyclones",                "66",   "Iowa State Cyclones",           "ISU",   "Big 12"),
    ("tcu",                     "2628", "TCU Horned Frogs",              "TCU",   "Big 12"),
    ("horned frogs",            "2628", "TCU Horned Frogs",              "TCU",   "Big 12"),
    ("west virginia",           "277",  "West Virginia Mountaineers",    "WVU",   "Big 12"),
    ("wvu",                     "277",  "West Virginia Mountaineers",    "WVU",   "Big 12"),
    ("mountaineers",            "277",  "West Virginia Mountaineers",    "WVU",   "Big 12"),
    ("kansas state",            "2306", "Kansas State Wildcats",         "KSU",   "Big 12"),
    ("kansas st",               "2306", "Kansas State Wildcats",         "KSU",   "Big 12"),
    ("kstate",                  "2306", "Kansas State Wildcats",         "KSU",   "Big 12"),
    ("cincinnati",              "2132", "Cincinnati Bearcats",           "CIN",   "Big 12"),
    ("bearcats",                "2132", "Cincinnati Bearcats",           "CIN",   "Big 12"),
    ("ucf",                     "2116", "UCF Knights",                   "UCF",   "Big 12"),
    ("central florida",         "2116", "UCF Knights",                   "UCF",   "Big 12"),
    ("byu",                     "252",  "BYU Cougars",                   "BYU",   "Big 12"),
    ("brigham young",           "252",  "BYU Cougars",                   "BYU",   "Big 12"),
    ("houston",                 "248",  "Houston Cougars",               "HOU",   "Big 12"),
    ("cougars",                 "248",  "Houston Cougars",               "HOU",   "Big 12"),
    ("arizona",                 "12",   "Arizona Wildcats",              "ARIZ",  "Big 12"),
    ("wildcats",                "12",   "Arizona Wildcats",              "ARIZ",  "Big 12"),
    ("arizona state",           "9",    "Arizona State Sun Devils",      "ASU",   "Big 12"),
    ("arizona st",              "9",    "Arizona State Sun Devils",      "ASU",   "Big 12"),
    ("asu",                     "9",    "Arizona State Sun Devils",      "ASU",   "Big 12"),
    ("sun devils",              "9",    "Arizona State Sun Devils",      "ASU",   "Big 12"),
    ("utah",                    "254",  "Utah Utes",                     "UTAH",  "Big 12"),
    ("utes",                    "254",  "Utah Utes",                     "UTAH",  "Big 12"),
    ("colorado",                "38",   "Colorado Buffaloes",            "COLO",  "Big 12"),
    ("buffaloes",               "38",   "Colorado Buffaloes",            "COLO",  "Big 12"),
    ("buffs",                   "38",   "Colorado Buffaloes",            "COLO",  "Big 12"),

    # ── SEC ───────────────────────────────────────────────────────────
    ("alabama",                 "333",  "Alabama Crimson Tide",          "ALA",   "SEC"),
    ("crimson tide",            "333",  "Alabama Crimson Tide",          "ALA",   "SEC"),
    ("kentucky",                "96",   "Kentucky Wildcats",             "UK",    "SEC"),
    ("uk",                      "96",   "Kentucky Wildcats",             "UK",    "SEC"),
    ("tennessee",               "2633", "Tennessee Volunteers",          "TENN",  "SEC"),
    ("volunteers",              "2633", "Tennessee Volunteers",          "TENN",  "SEC"),
    ("vols",                    "2633", "Tennessee Volunteers",          "TENN",  "SEC"),
    ("arkansas",                "8",    "Arkansas Razorbacks",           "ARK",   "SEC"),
    ("razorbacks",              "8",    "Arkansas Razorbacks",           "ARK",   "SEC"),
    ("auburn",                  "2",    "Auburn Tigers",                 "AUB",   "SEC"),
    ("florida",                 "57",   "Florida Gators",                "FLA",   "SEC"),
    ("florida gators",          "57",   "Florida Gators",                "FLA",   "SEC"),
    ("gators",                  "57",   "Florida Gators",                "FLA",   "SEC"),
    ("georgia",                 "61",   "Georgia Bulldogs",              "UGA",   "SEC"),
    ("bulldogs",                "61",   "Georgia Bulldogs",              "UGA",   "SEC"),
    ("lsu",                     "99",   "LSU Tigers",                    "LSU",   "SEC"),
    ("tigers",                  "99",   "LSU Tigers",                    "LSU",   "SEC"),
    ("ole miss",                "145",  "Ole Miss Rebels",               "MISS",  "SEC"),
    ("mississippi",             "145",  "Ole Miss Rebels",               "MISS",  "SEC"),
    ("rebels",                  "145",  "Ole Miss Rebels",               "MISS",  "SEC"),
    ("mississippi state",       "344",  "Mississippi State Bulldogs",    "MSST",  "SEC"),
    ("mississippi st",          "344",  "Mississippi State Bulldogs",    "MSST",  "SEC"),
    ("miss state",              "344",  "Mississippi State Bulldogs",    "MSST",  "SEC"),
    ("missouri",                "142",  "Missouri Tigers",               "MIZ",   "SEC"),
    ("mizzou",                  "142",  "Missouri Tigers",               "MIZ",   "SEC"),
    ("south carolina",          "2579", "South Carolina Gamecocks",      "SC",    "SEC"),
    ("gamecocks",               "2579", "South Carolina Gamecocks",      "SC",    "SEC"),
    ("texas a&m",               "245",  "Texas A&M Aggies",              "TAMU",  "SEC"),
    ("texas am",                "245",  "Texas A&M Aggies",              "TAMU",  "SEC"),
    ("aggies",                  "245",  "Texas A&M Aggies",              "TAMU",  "SEC"),
    ("vanderbilt",              "238",  "Vanderbilt Commodores",         "VAN",   "SEC"),
    ("commodores",              "238",  "Vanderbilt Commodores",         "VAN",   "SEC"),

    # ── Big East ──────────────────────────────────────────────────────
    ("connecticut",             "41",   "Connecticut Huskies",           "UCONN", "Big East"),
    ("uconn",                   "41",   "Connecticut Huskies",           "UCONN", "Big East"),
    ("villanova",               "222",  "Villanova Wildcats",            "NOVA",  "Big East"),
    ("nova",                    "222",  "Villanova Wildcats",            "NOVA",  "Big East"),
    ("marquette",               "269",  "Marquette Golden Eagles",       "MARQ",  "Big East"),
    ("st johns",                "2599", "St. John's Red Storm",          "STJ",   "Big East"),
    ("st. johns",               "2599", "St. John's Red Storm",          "STJ",   "Big East"),
    ("st. john's",              "2599", "St. John's Red Storm",          "STJ",   "Big East"),
    ("saint johns",             "2599", "St. John's Red Storm",          "STJ",   "Big East"),
    ("red storm",               "2599", "St. John's Red Storm",          "STJ",   "Big East"),
    ("georgetown",              "46",   "Georgetown Hoyas",              "GTWN",  "Big East"),
    ("hoyas",                   "46",   "Georgetown Hoyas",              "GTWN",  "Big East"),
    ("seton hall",              "2550", "Seton Hall Pirates",            "HALL",  "Big East"),
    ("providence",              "2507", "Providence Friars",             "PROV",  "Big East"),
    ("friars",                  "2507", "Providence Friars",             "PROV",  "Big East"),
    ("creighton",               "156",  "Creighton Bluejays",            "CREI",  "Big East"),
    ("bluejays",                "156",  "Creighton Bluejays",            "CREI",  "Big East"),
    ("xavier",                  "2752", "Xavier Musketeers",             "XAV",   "Big East"),
    ("musketeers",              "2752", "Xavier Musketeers",             "XAV",   "Big East"),
    ("depaul",                  "305",  "DePaul Blue Demons",            "DEP",   "Big East"),
    ("butler",                  "2086", "Butler Bulldogs",               "BUT",   "Big East"),

    # ── WCC ───────────────────────────────────────────────────────────
    ("gonzaga",                 "2250", "Gonzaga Bulldogs",              "GONZ",  "WCC"),
    ("zags",                    "2250", "Gonzaga Bulldogs",              "GONZ",  "WCC"),
    ("saint mary's",            "2608", "Saint Mary's Gaels",            "SMC",   "WCC"),
    ("st marys",                "2608", "Saint Mary's Gaels",            "SMC",   "WCC"),
    ("saint marys",             "2608", "Saint Mary's Gaels",            "SMC",   "WCC"),
    ("gaels",                   "2608", "Saint Mary's Gaels",            "SMC",   "WCC"),
    ("san francisco",           "2650", "San Francisco Dons",            "SF",    "WCC"),
    ("dons",                    "2650", "San Francisco Dons",            "SF",    "WCC"),
    ("loyola marymount",        "2361", "Loyola Marymount Lions",        "LMU",   "WCC"),
    ("lmu",                     "2361", "Loyola Marymount Lions",        "LMU",   "WCC"),
    ("pepperdine",              "2492", "Pepperdine Waves",              "PEPP",  "WCC"),
    ("santa clara",             "2615", "Santa Clara Broncos",           "SCU",   "WCC"),
    ("portland",                "2501", "Portland Pilots",               "PORT",  "WCC"),

    # ── A-10 ──────────────────────────────────────────────────────────
    ("dayton",                  "2168", "Dayton Flyers",                 "DAY",   "A-10"),
    ("flyers",                  "2168", "Dayton Flyers",                 "DAY",   "A-10"),
    ("vcu",                     "2670", "VCU Rams",                      "VCU",   "A-10"),
    ("richmond",                "257",  "Richmond Spiders",              "RICH",  "A-10"),
    ("george mason",            "2193", "George Mason Patriots",         "GMU",   "A-10"),
    ("gmu",                     "2193", "George Mason Patriots",         "GMU",   "A-10"),
    ("st bonaventure",          "179",  "St. Bonaventure Bonnies",       "SBU",   "A-10"),
    ("saint bonaventure",       "179",  "St. Bonaventure Bonnies",       "SBU",   "A-10"),
    ("bonnies",                 "179",  "St. Bonaventure Bonnies",       "SBU",   "A-10"),
    ("loyola chicago",          "309",  "Loyola Chicago Ramblers",       "LOYC",  "A-10"),
    ("davidson",                "2166", "Davidson Wildcats",             "DAV",   "A-10"),
    ("fordham",                 "2210", "Fordham Rams",                  "FOR",   "A-10"),
    ("george washington",       "45",   "George Washington Colonials",   "GW",    "A-10"),
    ("gwu",                     "45",   "George Washington Colonials",   "GW",    "A-10"),
    ("la salle",                "2350", "La Salle Explorers",            "LAS",   "A-10"),
    ("umass",                   "113",  "UMass Minutemen",               "MASS",  "A-10"),
    ("massachusetts",           "113",  "UMass Minutemen",               "MASS",  "A-10"),
    ("saint louis",             "139",  "Saint Louis Billikens",         "SLU",   "A-10"),
    ("billikens",               "139",  "Saint Louis Billikens",         "SLU",   "A-10"),
    ("duquesne",                "2184", "Duquesne Dukes",                "DUQ",   "A-10"),

    # ── Mountain West ─────────────────────────────────────────────────
    ("san diego state",         "21",   "San Diego State Aztecs",        "SDSU",  "Mountain West"),
    ("sdsu",                    "21",   "San Diego State Aztecs",        "SDSU",  "Mountain West"),
    ("aztecs",                  "21",   "San Diego State Aztecs",        "SDSU",  "Mountain West"),
    ("nevada",                  "2440", "Nevada Wolf Pack",              "NEV",   "Mountain West"),
    ("wolf pack",               "2440", "Nevada Wolf Pack",              "NEV",   "Mountain West"),
    ("unlv",                    "2439", "UNLV Rebels",                   "UNLV",  "Mountain West"),
    ("boise state",             "68",   "Boise State Broncos",           "BSU",   "Mountain West"),
    ("boise st",                "68",   "Boise State Broncos",           "BSU",   "Mountain West"),
    ("new mexico",              "167",  "New Mexico Lobos",              "UNM",   "Mountain West"),
    ("lobos",                   "167",  "New Mexico Lobos",              "UNM",   "Mountain West"),
    ("colorado state",          "36",   "Colorado State Rams",           "CSU",   "Mountain West"),
    ("colorado st",             "36",   "Colorado State Rams",           "CSU",   "Mountain West"),
    ("csu",                     "36",   "Colorado State Rams",           "CSU",   "Mountain West"),
    ("fresno state",            "278",  "Fresno State Bulldogs",         "FRES",  "Mountain West"),
    ("fresno st",               "278",  "Fresno State Bulldogs",         "FRES",  "Mountain West"),
    ("wyoming",                 "2751", "Wyoming Cowboys",               "WYO",   "Mountain West"),
    ("air force",               "2005", "Air Force Falcons",             "AF",    "Mountain West"),
    ("utah state",              "328",  "Utah State Aggies",             "USU",   "Mountain West"),
    ("utah st",                 "328",  "Utah State Aggies",             "USU",   "Mountain West"),
    ("san jose state",          "23",   "San Jose State Spartans",       "SJSU",  "Mountain West"),

    # ── American Athletic ─────────────────────────────────────────────
    ("memphis",                 "235",  "Memphis Tigers",                "MEM",   "American"),
    ("temple",                  "218",  "Temple Owls",                   "TEM",   "American"),
    ("tulsa",                   "202",  "Tulsa Golden Hurricane",        "TLSA",  "American"),
    ("south florida",           "58",   "South Florida Bulls",           "USF",   "American"),
    ("usf",                     "58",   "South Florida Bulls",           "USF",   "American"),
    ("tulane",                  "2655", "Tulane Green Wave",             "TULN",  "American"),
    ("east carolina",           "151",  "East Carolina Pirates",         "ECU",   "American"),
    ("ecu",                     "151",  "East Carolina Pirates",         "ECU",   "American"),
    ("wichita state",           "2724", "Wichita State Shockers",        "WICH",  "American"),
    ("wichita st",              "2724", "Wichita State Shockers",        "WICH",  "American"),
    ("shockers",                "2724", "Wichita State Shockers",        "WICH",  "American"),
    ("north texas",             "249",  "North Texas Mean Green",        "UNT",   "American"),
    ("unt",                     "249",  "North Texas Mean Green",        "UNT",   "American"),
    ("rice",                    "242",  "Rice Owls",                     "RICE",  "American"),
    ("utsa",                    "2636", "UTSA Roadrunners",              "UTSA",  "American"),
    ("charlotte",               "2429", "Charlotte 49ers",               "CLT",   "American"),
    ("florida atlantic",        "2226", "Florida Atlantic Owls",         "FAU",   "American"),
    ("fau",                     "2226", "Florida Atlantic Owls",         "FAU",   "American"),

    # ── MVC ───────────────────────────────────────────────────────────
    ("drake",                   "2181", "Drake Bulldogs",                "DRKE",  "MVC"),
    ("bradley",                 "71",   "Bradley Braves",                "BRAD",  "MVC"),
    ("illinois state",          "64",   "Illinois State Redbirds",       "ILST",  "MVC"),
    ("illinois st",             "64",   "Illinois State Redbirds",       "ILST",  "MVC"),
    ("indiana state",           "2316", "Indiana State Sycamores",       "INST",  "MVC"),
    ("indiana st",              "2316", "Indiana State Sycamores",       "INST",  "MVC"),
    ("valparaiso",              "2674", "Valparaiso Beacons",            "VAL",   "MVC"),
    ("evansville",              "339",  "Evansville Purple Aces",        "EVAN",  "MVC"),
    ("southern illinois",       "79",   "Southern Illinois Salukis",     "SIU",   "MVC"),
    ("siu",                     "79",   "Southern Illinois Salukis",     "SIU",   "MVC"),
    ("northern iowa",           "2710", "Northern Iowa Panthers",        "UNI",   "MVC"),
    ("uni",                     "2710", "Northern Iowa Panthers",        "UNI",   "MVC"),
    ("missouri state",          "2623", "Missouri State Bears",          "MOST",  "MVC"),
    ("missouri st",             "2623", "Missouri State Bears",          "MOST",  "MVC"),
    ("belmont",                 "2057", "Belmont Bruins",                "BEL",   "MVC"),
    ("murray state",            "2418", "Murray State Racers",           "MUR",   "MVC"),

    # ── Ivy League ────────────────────────────────────────────────────
    ("yale",                    "43",   "Yale Bulldogs",                 "YALE",  "Ivy League"),
    ("princeton",               "163",  "Princeton Tigers",              "PRIN",  "Ivy League"),
    ("harvard",                 "108",  "Harvard Crimson",               "HAR",   "Ivy League"),
    ("penn",                    "219",  "Pennsylvania Quakers",          "PENN",  "Ivy League"),
    ("pennsylvania",            "219",  "Pennsylvania Quakers",          "PENN",  "Ivy League"),
    ("columbia",                "171",  "Columbia Lions",                "CLMB",  "Ivy League"),
    ("cornell",                 "172",  "Cornell Big Red",               "COR",   "Ivy League"),
    ("brown",                   "225",  "Brown Bears",                   "BRWN",  "Ivy League"),
    ("dartmouth",               "159",  "Dartmouth Big Green",           "DART",  "Ivy League"),

    # ── WAC ───────────────────────────────────────────────────────────
    ("utah valley",             "3101", "Utah Valley Wolverines",        "UVU",   "WAC"),
    ("uvu",                     "3101", "Utah Valley Wolverines",        "UVU",   "WAC"),
    ("seattle",                 "2547", "Seattle Redhawks",              "SEA",   "WAC"),
    ("new mexico state",        "166",  "New Mexico State Aggies",       "NMSU",  "WAC"),
    ("nmsu",                    "166",  "New Mexico State Aggies",       "NMSU",  "WAC"),
    ("grand canyon",            "2253", "Grand Canyon Antelopes",        "GCU",   "WAC"),
    ("gcu",                     "2253", "Grand Canyon Antelopes",        "GCU",   "WAC"),
    ("tarleton state",          "2920", "Tarleton State Texans",         "TAR",   "WAC"),

    # ── CUSA ──────────────────────────────────────────────────────────
    ("liberty",                 "2335", "Liberty Flames",                "LIB",   "CUSA"),
    ("flames",                  "2335", "Liberty Flames",                "LIB",   "CUSA"),
    ("kennesaw state",          "338",  "Kennesaw State Owls",           "KENN",  "CUSA"),
    ("western kentucky",        "98",   "Western Kentucky Hilltoppers",  "WKU",   "CUSA"),
    ("wku",                     "98",   "Western Kentucky Hilltoppers",  "WKU",   "CUSA"),
    ("fiu",                     "2229", "FIU Panthers",                  "FIU",   "CUSA"),
    ("florida intl",            "2229", "FIU Panthers",                  "FIU",   "CUSA"),
    ("middle tennessee",        "2393", "Middle Tennessee Blue Raiders", "MTSU",  "CUSA"),
    ("mtsu",                    "2393", "Middle Tennessee Blue Raiders", "MTSU",  "CUSA"),
    ("sam houston",             "2534", "Sam Houston Bearkats",          "SHSU",  "CUSA"),
    ("niu",                     "2459", "Northern Illinois Huskies",     "NIU",   "CUSA"),
    ("northern illinois",       "2459", "Northern Illinois Huskies",     "NIU",   "CUSA"),
    ("western michigan",        "2711", "Western Michigan Broncos",      "WMU",   "CUSA"),

    # ── Sun Belt ──────────────────────────────────────────────────────
    ("app state",               "2026", "App State Mountaineers",        "APP",   "Sun Belt"),
    ("appalachian state",       "2026", "App State Mountaineers",        "APP",   "Sun Belt"),
    ("james madison",           "256",  "James Madison Dukes",           "JMU",   "Sun Belt"),
    ("jmu",                     "256",  "James Madison Dukes",           "JMU",   "Sun Belt"),
    ("old dominion",            "295",  "Old Dominion Monarchs",         "ODU",   "Sun Belt"),
    ("odu",                     "295",  "Old Dominion Monarchs",         "ODU",   "Sun Belt"),
    ("marshall",                "276",  "Marshall Thundering Herd",      "MRSH",  "Sun Belt"),
    ("southern miss",           "2572", "Southern Miss Golden Eagles",   "USM",   "Sun Belt"),
    ("southern mississippi",    "2572", "Southern Miss Golden Eagles",   "USM",   "Sun Belt"),
    ("georgia southern",        "290",  "Georgia Southern Eagles",       "GASO",  "Sun Belt"),
    ("coastal carolina",        "324",  "Coastal Carolina Chanticleers", "CCU",   "Sun Belt"),
    ("louisiana",               "309",  "Louisiana Ragin Cajuns",        "ULL",   "Sun Belt"),
    ("ul lafayette",            "309",  "Louisiana Ragin Cajuns",        "ULL",   "Sun Belt"),
    ("louisiana monroe",        "2433", "Louisiana Monroe Warhawks",     "ULM",   "Sun Belt"),
    ("ul monroe",               "2433", "Louisiana Monroe Warhawks",     "ULM",   "Sun Belt"),
    ("troy",                    "2653", "Troy Trojans",                  "TROY",  "Sun Belt"),
    ("south alabama",           "6",    "South Alabama Jaguars",         "USA",   "Sun Belt"),
    ("georgia state",           "2247", "Georgia State Panthers",        "GSU",   "Sun Belt"),
    ("arkansas state",          "2032", "Arkansas State Red Wolves",     "ARST",  "Sun Belt"),
    ("ark state",               "2032", "Arkansas State Red Wolves",     "ARST",  "Sun Belt"),
    ("texas state",             "326",  "Texas State Bobcats",           "TXST",  "Sun Belt"),

    # ── Southern Conference ───────────────────────────────────────────
    ("unc greensboro",          "2566", "UNC Greensboro Spartans",       "UNCG",  "Southern"),
    ("uncg",                    "2566", "UNC Greensboro Spartans",       "UNCG",  "Southern"),
    ("wofford",                 "2747", "Wofford Terriers",              "WOF",   "Southern"),
    ("furman",                  "231",  "Furman Paladins",               "FUR",   "Southern"),
    ("samford",                 "2523", "Samford Bulldogs",              "SAM",   "Southern"),
    ("chattanooga",             "236",  "Chattanooga Mocs",              "CHAT",  "Southern"),
    ("utc",                     "236",  "Chattanooga Mocs",              "CHAT",  "Southern"),
    ("mercer",                  "2382", "Mercer Bears",                  "MER",   "Southern"),
    ("western carolina",        "2749", "Western Carolina Catamounts",   "WCU",   "Southern"),
    ("the citadel",             "2643", "The Citadel Bulldogs",          "CIT",   "Southern"),
    ("citadel",                 "2643", "The Citadel Bulldogs",          "CIT",   "Southern"),
    ("vmit",                    "2710", "VMI Keydets",                   "VMI",   "Southern"),
    ("vmi",                     "2710", "VMI Keydets",                   "VMI",   "Southern"),
    ("east tennessee state",    "2193", "ETSU Buccaneers",               "ETSU",  "Southern"),
    ("etsu",                    "2193", "ETSU Buccaneers",               "ETSU",  "Southern"),

    # ── Big South ─────────────────────────────────────────────────────
    ("unc asheville",           "2567", "UNC Asheville Bulldogs",        "UNCA",  "Big South"),
    ("high point",              "2272", "High Point Panthers",           "HPU",   "Big South"),
    ("longwood",                "2360", "Longwood Lancers",              "LONG",  "Big South"),
    ("winthrop",                "2742", "Winthrop Eagles",               "WIN",   "Big South"),
    ("presbyterian",            "2503", "Presbyterian Blue Hose",        "PRES",  "Big South"),
    ("radford",                 "2513", "Radford Highlanders",           "RAD",   "Big South"),
    ("campbell",                "2103", "Campbell Fighting Camels",      "CAM",   "Big South"),
    ("gardner-webb",            "2241", "Gardner-Webb Bulldogs",         "GWEB",  "Big South"),
    ("gardner webb",            "2241", "Gardner-Webb Bulldogs",         "GWEB",  "Big South"),

    # ── Patriot League ────────────────────────────────────────────────
    ("colgate",                 "2142", "Colgate Raiders",               "COLG",  "Patriot"),
    ("bucknell",                "2081", "Bucknell Bison",                "BUCK",  "Patriot"),
    ("lehigh",                  "2329", "Lehigh Mountain Hawks",         "LEH",   "Patriot"),
    ("lafayette",               "322",  "Lafayette Leopards",            "LAF",   "Patriot"),
    ("holy cross",              "107",  "Holy Cross Crusaders",          "HC",    "Patriot"),
    ("navy",                    "2426", "Navy Midshipmen",               "NAVY",  "Patriot"),
    ("army",                    "349",  "Army West Point Black Knights", "ARMY",  "Patriot"),
    ("army west point",         "349",  "Army West Point Black Knights", "ARMY",  "Patriot"),
    ("boston university",       "104",  "Boston University Terriers",    "BU",    "Patriot"),
    ("bu",                      "104",  "Boston University Terriers",    "BU",    "Patriot"),

    # ── CAA ───────────────────────────────────────────────────────────
    ("hofstra",                 "2287", "Hofstra Pride",                 "HOF",   "CAA"),
    ("towson",                  "119",  "Towson Tigers",                 "TOW",   "CAA"),
    ("charleston",              "232",  "College of Charleston Cougars", "COFC",  "CAA"),
    ("college of charleston",   "232",  "College of Charleston Cougars", "COFC",  "CAA"),
    ("elon",                    "2198", "Elon Phoenix",                  "ELON",  "CAA"),
    ("delaware",                "48",   "Delaware Fightin Blue Hens",    "DEL",   "CAA"),
    ("drexel",                  "2182", "Drexel Dragons",                "DREX",  "CAA"),
    ("stony brook",             "2619", "Stony Brook Seawolves",         "STBK",  "CAA"),
    ("hampton",                 "2261", "Hampton Pirates",               "HAMP",  "CAA"),
    ("monmouth",                "2397", "Monmouth Hawks",                "MON",   "CAA"),
    ("northeastern",            "111",  "Northeastern Huskies",          "NE",    "CAA"),
    ("william & mary",          "2729", "William & Mary Tribe",          "W&M",   "CAA"),
    ("william and mary",        "2729", "William & Mary Tribe",          "W&M",   "CAA"),
    ("nc wilmington",           "2572", "UNC Wilmington Seahawks",       "UNCW",  "CAA"),
    ("uncw",                    "2572", "UNC Wilmington Seahawks",       "UNCW",  "CAA"),

    # ── MEAC ──────────────────────────────────────────────────────────
    ("norfolk state",           "2450", "Norfolk State Spartans",        "NORF",  "MEAC"),
    ("morgan state",            "2413", "Morgan State Bears",            "MORG",  "MEAC"),
    ("howard",                  "47",   "Howard Bison",                  "HOW",   "MEAC"),
    ("coppin state",            "2154", "Coppin State Eagles",           "COPP",  "MEAC"),
    ("south carolina state",    "2578", "South Carolina State Bulldogs", "SCST",  "MEAC"),
    ("florida a&m",             "50",   "Florida A&M Rattlers",          "FAMU",  "MEAC"),
    ("florida am",              "50",   "Florida A&M Rattlers",          "FAMU",  "MEAC"),
    ("famu",                    "50",   "Florida A&M Rattlers",          "FAMU",  "MEAC"),
    ("north carolina central",  "2427", "NC Central Eagles",             "NCCU",  "MEAC"),
    ("nccu",                    "2427", "NC Central Eagles",             "NCCU",  "MEAC"),
    ("north carolina at",       "2428", "NC A&T Aggies",                 "NCAT",  "MEAC"),
    ("nc a&t",                  "2428", "NC A&T Aggies",                 "NCAT",  "MEAC"),
    ("nc at",                   "2428", "NC A&T Aggies",                 "NCAT",  "MEAC"),
    ("delaware state",          "2169", "Delaware State Hornets",        "DSU",   "MEAC"),
    ("howard bison",            "47",   "Howard Bison",                  "HOW",   "MEAC"),

    # ── SWAC ──────────────────────────────────────────────────────────
    ("grambling",               "2755", "Grambling Tigers",              "GRAM",  "SWAC"),
    ("grambling state",         "2755", "Grambling Tigers",              "GRAM",  "SWAC"),
    ("prairie view",            "2506", "Prairie View A&M Panthers",     "PVAM",  "SWAC"),
    ("prairie view a&m",        "2506", "Prairie View A&M Panthers",     "PVAM",  "SWAC"),
    ("prairie view am",         "2506", "Prairie View A&M Panthers",     "PVAM",  "SWAC"),
    ("southern",                "2575", "Southern Jaguars",              "SOU",   "SWAC"),
    ("southern university",     "2575", "Southern Jaguars",              "SOU",   "SWAC"),
    ("alcorn state",            "2016", "Alcorn State Braves",           "ALCN",  "SWAC"),
    ("jackson state",           "2296", "Jackson State Tigers",          "JKST",  "SWAC"),
    ("texas southern",          "242",  "Texas Southern Tigers",         "TXSO",  "SWAC"),
    ("alabama a&m",             "2010", "Alabama A&M Bulldogs",          "AAMU",  "SWAC"),
    ("alabama am",              "2010", "Alabama A&M Bulldogs",          "AAMU",  "SWAC"),
    ("bethune-cookman",         "2065", "Bethune-Cookman Wildcats",      "BCU",   "SWAC"),
    ("bethune cookman",         "2065", "Bethune-Cookman Wildcats",      "BCU",   "SWAC"),
    ("mississippi valley",      "2408", "Mississippi Valley State Delta Devils", "MVSU", "SWAC"),
    ("mvsu",                    "2408", "Mississippi Valley State Delta Devils", "MVSU", "SWAC"),
    ("arkansas pine bluff",     "2029", "Arkansas-Pine Bluff Golden Lions", "UAPB", "SWAC"),
    ("uapb",                    "2029", "Arkansas-Pine Bluff Golden Lions", "UAPB", "SWAC"),
    ("southern br",             "2575", "Southern Jaguars",              "SOU",   "SWAC"),
    ("alabama state",           "2011", "Alabama State Hornets",         "ALST",  "SWAC"),
    ("alst",                    "2011", "Alabama State Hornets",         "ALST",  "SWAC"),

]


def normalize(raw: str) -> str:
    """Must match engine normalization exactly."""
    import re
    s = raw.lower().strip()
    s = re.sub(r"[^a-z0-9 &]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def seed():
    rows = []
    seen = set()
    for (kalshi_name, espn_id, espn_name, espn_abbr, conference) in TEAMS:
        key = normalize(kalshi_name)
        if key in seen:
            print(f"  DUPLICATE KEY skipped: '{key}'")
            continue
        seen.add(key)
        rows.append({
            "kalshi_name": key,
            "espn_id": espn_id,
            "espn_name": espn_name,
            "espn_abbr": espn_abbr,
            "conference": conference,
        })

    print(f"Upserting {len(rows)} team mapping rows...")

    # Batch upsert in chunks of 100
    chunk_size = 100
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        result = supabase.table("team_name_mapping").upsert(
            chunk,
            on_conflict="kalshi_name"
        ).execute()
        print(f"  Chunk {i // chunk_size + 1}: {len(chunk)} rows upserted")

    print("Done. team_name_mapping is up to date.")


if __name__ == "__main__":
    seed()
```

---

## 4. Startup Seeding (from Engine)

The Python engine (`main.py`, defined in Spec 2) must call `seed_teams.seed()` during its bootstrap phase before entering the main loop. This ensures the table is always current on redeploy, even if the manual seed script wasn't run separately.

```python
# In engine bootstrap:
from seed_teams import seed as seed_team_mapping
seed_team_mapping()
```

---

## 5. Verification Checklist

Before marking this spec complete:

- [ ] `supabase/migrations/0001_cbb_schema.sql` runs without errors in Supabase SQL Editor
- [ ] All 9 tables exist: `team_name_mapping`, `cbb_games`, `cbb_game_states`, `cbb_positions`, `cbb_signals`, `cbb_daily_pnl`, `cbb_bankroll`, `cbb_worker_health`, `cbb_unmapped_teams`
- [ ] All indexes exist
- [ ] `cbb/seed_teams.py` runs without errors: `python cbb/seed_teams.py`
- [ ] `team_name_mapping` has ≥ 300 rows after seeding
- [ ] Re-running seed script a second time produces no errors (upsert is idempotent)
- [ ] The `normalize()` function in `seed_teams.py` is byte-for-byte identical to the normalization logic in the engine

---

*End of Spec 1 of 3*
