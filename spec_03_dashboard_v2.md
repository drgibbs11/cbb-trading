# CBB Worker — Spec 3 of 3: Monitoring Dashboard
**For: OpenClaw Agent (Kimi K2.5)**
**Version: 2.1 — March 2026**
**Prerequisite: Spec 1 (Database) must be complete. Spec 2 (Engine) should be running or have data.**

---

## 0. READ THIS FIRST

This spec covers the full monitoring dashboard deployed to Netlify. It is a static React SPA that reads directly from Supabase using the **anon key** (read-only, public). No backend. No server functions.

**GitHub repo:** `cbb-trading` (same repo as the engine — dashboard lives in the `dashboard/` subdirectory)
**Netlify site name:** `cbb-trading` (deploys to `cbb-trading.netlify.app` or a custom domain)

The dashboard has three pages:
- **Page 1 — Live** — intraday status, worker health, open positions, today's PnL
- **Page 2 — History** — settled positions with full trade log
- **Page 3 — Analytics** — edge calibration, PnL curves, win rates, model performance

The dashboard auto-refreshes Page 1 every 30 seconds while the tab is active. Pages 2 and 3 refresh on navigation.

Design aesthetic: dark theme, monospace numbers, trading terminal feel. Think Bloomberg/Robinhood dark mode cross. Not a standard SaaS dashboard. Dense information, no wasted space.

---

## 1. Repository Structure

All dashboard files live in the `dashboard/` subdirectory at the repo root. Netlify is configured with Base Directory = `dashboard`.

```
/cbb-trading                  ← repo root
  /cbb                        ← engine (Spec 2)
  /supabase/migrations/
  /dashboard                  ← Netlify root directory for the SPA
    index.html
    src/
      main.jsx
      App.jsx
      pages/
        Live.jsx
        History.jsx
        Analytics.jsx
      components/
        Nav.jsx
        Tile.jsx
        PositionRow.jsx
        SignalRow.jsx
        PnLChart.jsx
        WinRateChart.jsx
        EdgeCalibrationChart.jsx
        WorkerStatus.jsx
      lib/
        supabase.js
        format.js
      index.css
    package.json
    vite.config.js
    netlify.toml
    .env.example
```

---

## 2. Environment Variables

These are Netlify build-time environment variables. Set them in the Netlify dashboard under Site Settings → Environment Variables.

```
VITE_SUPABASE_URL          ← same as SUPABASE_URL
VITE_SUPABASE_ANON_KEY     ← Supabase anon/public key (NOT the service role key)
```

Never expose the service role key in the frontend.

---

## 3. Tech Stack

```json
{
  "react": "^18.3.0",
  "react-dom": "^18.3.0",
  "@supabase/supabase-js": "^2.43.0",
  "recharts": "^2.12.0",
  "vite": "^5.2.0",
  "@vitejs/plugin-react": "^4.2.0"
}
```

No Tailwind (bundle size). Pure CSS via `index.css` with CSS variables for the design system. No component library. Write all components from scratch.

---

## 4. Design System (`index.css`)

```css
:root {
  /* Background layers */
  --bg-base:    #0a0a0f;
  --bg-surface: #111118;
  --bg-card:    #16161f;
  --bg-hover:   #1e1e2a;
  --bg-input:   #1a1a24;

  /* Borders */
  --border:     #2a2a3a;
  --border-dim: #1e1e2c;

  /* Text */
  --text-primary:   #e8e8f0;
  --text-secondary: #8888aa;
  --text-dim:       #55556a;
  --text-mono:      'JetBrains Mono', 'Fira Code', 'Courier New', monospace;

  /* Accent — green for profit, red for loss, blue for edge signal */
  --green:      #00e676;
  --green-dim:  #1a3d2a;
  --red:        #ff4444;
  --red-dim:    #3d1a1a;
  --blue:       #4488ff;
  --blue-dim:   #1a2a4a;
  --yellow:     #ffcc00;
  --yellow-dim: #3d3300;
  --purple:     #aa88ff;

  /* Sizing */
  --radius:   6px;
  --radius-lg: 10px;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg-base);
  color: var(--text-primary);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 14px;
  line-height: 1.5;
}

.mono { font-family: var(--text-mono); }
.dim  { color: var(--text-secondary); }
.tiny { font-size: 11px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.08em; }

.green  { color: var(--green); }
.red    { color: var(--red); }
.blue   { color: var(--blue); }
.yellow { color: var(--yellow); }

/* Card */
.card {
  background: var(--bg-card);
  border: 1px solid var(--border-dim);
  border-radius: var(--radius-lg);
  padding: 16px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.card-title {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-secondary);
}

/* Table */
.data-table {
  width: 100%;
  border-collapse: collapse;
}

.data-table th {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-dim);
  padding: 6px 8px;
  border-bottom: 1px solid var(--border-dim);
  text-align: left;
  white-space: nowrap;
}

.data-table td {
  padding: 8px;
  border-bottom: 1px solid var(--border-dim);
  font-family: var(--text-mono);
  font-size: 12px;
  white-space: nowrap;
}

.data-table tr:last-child td { border-bottom: none; }

.data-table tr:hover td { background: var(--bg-hover); }

/* Badge */
.badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.badge-green  { background: var(--green-dim);  color: var(--green); }
.badge-red    { background: var(--red-dim);    color: var(--red); }
.badge-blue   { background: var(--blue-dim);   color: var(--blue); }
.badge-yellow { background: var(--yellow-dim); color: var(--yellow); }
.badge-dim    { background: var(--bg-input);   color: var(--text-secondary); }

/* Layout */
.page { padding: 20px 24px; max-width: 1440px; margin: 0 auto; }

.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }
.grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.grid-auto { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; }

.stack { display: flex; flex-direction: column; gap: 12px; }
.row   { display: flex; align-items: center; gap: 8px; }

/* Stat tile */
.stat-tile {
  background: var(--bg-card);
  border: 1px solid var(--border-dim);
  border-radius: var(--radius-lg);
  padding: 14px 16px;
}

.stat-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-dim);
  margin-bottom: 6px;
}

.stat-value {
  font-family: var(--text-mono);
  font-size: 26px;
  font-weight: 700;
  line-height: 1;
}

.stat-sub {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 4px;
}

/* Nav */
.nav {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 0 24px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  height: 48px;
  position: sticky;
  top: 0;
  z-index: 100;
}

.nav-brand {
  font-size: 13px;
  font-weight: 700;
  font-family: var(--text-mono);
  color: var(--blue);
  margin-right: 24px;
  letter-spacing: 0.05em;
}

.nav-tab {
  padding: 0 16px;
  height: 48px;
  display: flex;
  align-items: center;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: color 0.15s, border-color 0.15s;
  text-decoration: none;
}

.nav-tab:hover { color: var(--text-primary); }
.nav-tab.active { color: var(--text-primary); border-bottom-color: var(--blue); }

.nav-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 12px;
}

/* Worker status dot */
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.status-dot.online  { background: var(--green); box-shadow: 0 0 6px var(--green); }
.status-dot.offline { background: var(--red); }
.status-dot.stale   { background: var(--yellow); }

/* Scrollable table wrapper */
.table-wrap {
  overflow-x: auto;
  border-radius: var(--radius);
}

/* Progress bar */
.progress-bar {
  height: 4px;
  background: var(--bg-input);
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s;
}

/* Recharts overrides */
.recharts-cartesian-grid-horizontal line,
.recharts-cartesian-grid-vertical line {
  stroke: var(--border-dim) !important;
}

.recharts-text { fill: var(--text-dim) !important; font-size: 11px !important; }
.recharts-tooltip-wrapper { outline: none; }
.custom-tooltip {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px 12px;
  font-family: var(--text-mono);
  font-size: 12px;
}

@media (max-width: 900px) {
  .grid-4 { grid-template-columns: 1fr 1fr; }
  .grid-3 { grid-template-columns: 1fr 1fr; }
  .grid-2 { grid-template-columns: 1fr; }
}
```

---

## 5. `lib/supabase.js`

```javascript
import { createClient } from '@supabase/supabase-js'

const supabaseUrl  = import.meta.env.VITE_SUPABASE_URL
const supabaseAnon = import.meta.env.VITE_SUPABASE_ANON_KEY

export const supabase = createClient(supabaseUrl, supabaseAnon)
```

---

## 6. `lib/format.js`

```javascript
// Number formatting helpers

export function formatPnl(dollars) {
  const abs = Math.abs(dollars)
  const sign = dollars >= 0 ? '+' : '-'
  return `${sign}$${abs.toFixed(2)}`
}

export function formatPnlCents(cents) {
  return formatPnl(cents / 100)
}

export function pnlClass(value) {
  if (value > 0) return 'green'
  if (value < 0) return 'red'
  return 'dim'
}

export function formatPct(prob) {
  return `${(prob * 100).toFixed(1)}%`
}

export function formatEdge(edge) {
  return `+${(edge * 100).toFixed(1)}pp`
}

export function formatTime(isoString) {
  if (!isoString) return '—'
  const d = new Date(isoString)
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function formatDate(isoString) {
  if (!isoString) return '—'
  const d = new Date(isoString)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function formatDuration(seconds) {
  if (!seconds) return '—'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}m ${s}s`
}

export function exitReasonBadge(reason) {
  const map = {
    CONVERGENCE:      ['badge-green',  'Converged'],
    SIGNAL_REVERSAL:  ['badge-red',    'Reversed'],
    TIME_EXPIRY:      ['badge-yellow', 'Time'],
    HALFTIME:         ['badge-dim',    'Halftime'],
    OVERTIME:         ['badge-dim',    'OT'],
    GAME_OVER:        ['badge-dim',    'Final'],
    STOP_LOSS:        ['badge-red',    'Stop Loss'],
    MANUAL:           ['badge-dim',    'Manual'],
  }
  return map[reason] || ['badge-dim', reason]
}
```

---

## 7. Page 1 — Live (`pages/Live.jsx`)

This is the most important page. It shows everything happening right now.

### 7.1 Layout (top to bottom)

```
[ Worker Status Bar — full width ]

[ Stat tiles row — 6 tiles ]
  Today PnL | Bankroll | Open Positions | Win Rate Today | Signals Today | Mode

[ Two-column section ]
  Left (60%): Open Positions table
  Right (40%): Live Games feed

[ Signal log — last 20 signals ]
```

### 7.2 Worker Status Bar (`components/WorkerStatus.jsx`)

Fetches the most recent row from `cbb_worker_health`.

```
● ONLINE   Last loop: 14s ago   Loop #1,847   Live games: 3   Open positions: 2   PAPER MODE
```

- Green dot if last heartbeat < 90s ago
- Yellow dot if 90s–3min ago (stale)
- Red dot + "WORKER OFFLINE" if > 3min ago
- Shows paper/live mode badge

### 7.3 Stat Tiles

Each tile is a `<Tile>` component with label + big number + optional subtext.

| Tile | Query | Color |
|---|---|---|
| Today P&L | `cbb_daily_pnl` where date = today, `net_pnl_dollars` | green/red based on value |
| Bankroll | `cbb_bankroll` where `is_paper` matches env | white |
| Open Positions | count of `cbb_positions` where status='open' | blue if > 0 |
| Win Rate | wins / (wins + losses) from `cbb_daily_pnl` today | green/yellow/red |
| Signals Today | count of `cbb_signals` for today | dim |
| Mode | `is_paper_trade` flag from most recent position | yellow=PAPER, green=LIVE |

### 7.4 Open Positions Table

Columns: `Team | Game | Entry Time | Half | Min Left at Entry | Edge | Contracts | Cost | ESPN% | Kalshi% | Unrealized`

- **Team**: `team_name` from position + conference badge
- **Game**: `home_team_abbr` vs `away_team_abbr` from `cbb_games` join
- **Entry Time**: formatted as HH:MM:SS
- **Half / Min Left**: `entry_half` + `entry_minutes_remaining`
- **Edge**: `entry_edge` as `+14.2pp` in blue
- **Contracts**: count
- **Cost**: `cost_basis_cents / 100` in dollars
- **ESPN%**: `entry_espn_probability` as percentage
- **Kalshi%**: `entry_kalshi_price_cents / 100` as percentage
- **Unrealized**: This requires a live Kalshi price. For simplicity, show "—" here (live prices require a separate fetch that would need auth). Show "—" with a dim tooltip saying "No live quote".

Empty state: "No open positions" with a soft icon.

### 7.5 Live Games Feed

Right column. Shows all games currently `STATUS_IN_PROGRESS` from `cbb_games`. For each game:

```
┌─────────────────────────────────────────────┐
│  DUKE              vs   UNC                  │
│  45                     38                   │
│  H2  12:34 remaining                         │
│  ESPN: 72% │ Kalshi: 64% │ Edge: +8.0pp      │
│  [ position badge if open ]                  │
└─────────────────────────────────────────────┘
```

Pull the most recent `cbb_game_states` row for each live game and display those probabilities.

If `home_edge >= 0.10`, highlight the home side edge in blue.
If `away_edge >= 0.10`, highlight the away side edge in blue.

Sort by edge descending (highest actionable edge at top).

### 7.6 Signal Log

Bottom of page. Last 20 signals from `cbb_signals` ordered by `signal_time DESC`.

Columns: `Time | Team | Game | Half | Min | Edge | ESPN% | Kalshi% | Action`

- Action column uses `badge` component:
  - `TRADE_FIRED` / `TRADE_SIMULATED` → green badge
  - `BELOW_THRESHOLD` → dim badge
  - `POSITION_ALREADY_OPEN` / `CAP_REACHED` → dim badge
  - `UNMAPPED_TEAM` → red badge
  - `STOP_LOSS_ACTIVE` → red badge

Auto-refreshes every 30 seconds (only while this tab is active — pause refresh when page is hidden using `document.visibilityState`).

---

## 8. Page 2 — History (`pages/History.jsx`)

### 8.1 Layout

```
[ Filter bar: Date range | Mode (paper/live) | Conference | Exit Reason | Team search ]

[ Summary stats row: Total PnL | Trades | Win Rate | Avg Hold | Best Trade | Worst Trade ]

[ Settled positions table — paginated 50 per page ]

[ Unmapped teams panel ]
```

### 8.2 Filters

Date range: last 7 days / last 30 days / all time (dropdown)
Mode: paper / live / both
Conference: dropdown of distinct conferences from `cbb_games`
Exit reason: dropdown of all exit reason values
Team search: text input, filters by `team_name` contains

### 8.3 Summary Stats (filtered)

Compute from the filtered result set (not a separate query):
- Total Net PnL in dollars
- Total trades (closed positions)
- Win rate %
- Average hold duration
- Best single trade (highest net PnL)
- Worst single trade (lowest net PnL)

### 8.4 Settled Positions Table

Columns:
`Date | Team | Game | Mode | Entry Time | Exit Time | Hold | Half/Min | Entry Edge | Entry ESPN% | Entry Kalshi% | Exit Kalshi% | Contracts | P&L | Exit Reason`

- Sortable by clicking column headers (client-side sort)
- P&L column: green for profit, red for loss
- Exit Reason: badge component
- Mode: paper/live badge
- Paginate: 50 rows per page, show page controls

Join `cbb_positions` with `cbb_games` for game names.

Query:
```javascript
supabase
  .from('cbb_positions')
  .select(`
    *,
    cbb_games (
      home_team_name,
      away_team_name,
      home_team_abbr,
      away_team_abbr,
      conference_home,
      conference_away
    )
  `)
  .eq('status', 'closed')
  .order('exit_time', { ascending: false })
  .range(offset, offset + 49)
```

### 8.5 Unmapped Teams Panel

At the bottom. Shows rows from `cbb_unmapped_teams` ordered by `occurrence_count DESC`.

```
┌─ Unmapped Teams (add to mapping table to capture these games) ─┐
│  Raw Kalshi Name         │ Occurrences │ Last Seen              │
│  Miami OH                │     14      │ today 3:42 PM          │
│  N. Kentucky             │      7      │ yesterday 8:12 PM      │
└────────────────────────────────────────────────────────────────┘
```

This is a critical operational tool. If a team has high occurrence count, it means Kalshi is listing games for that team but the engine is skipping them due to missing mapping.

---

## 9. Page 3 — Analytics (`pages/Analytics.jsx`)

### 9.1 Layout

```
[ Time range selector: 7d / 30d / All ]

[ Row 1: Cumulative PnL Chart (full width) ]

[ Row 2 — two columns ]
  Left:  Win Rate by Exit Reason (bar chart)
  Right: Edge Calibration chart

[ Row 3 — two columns ]
  Left:  Trade Volume by Day of Week (bar chart)
  Right: Average Edge at Entry by Conference

[ Row 4 — two columns ]
  Left:  Hold Duration Distribution
  Right: PnL by Half (H1 vs H2 entries)

[ Row 5: Top Performing Teams table ]
[ Row 6: Conference Breakdown table ]
```

### 9.2 Cumulative PnL Chart (`components/PnLChart.jsx`)

Line chart from `cbb_daily_pnl`, sorted by date ascending.
X-axis: date. Y-axis: cumulative net PnL dollars.
Use Recharts `LineChart` with a `ReferenceLine` at y=0.
Green line when above 0, red line when below (use two separate Line components split at 0, or a gradient stroke).
Show tooltip with date + daily PnL + cumulative.

```javascript
// Sample data transform
const cumulative = dailyPnl.reduce((acc, row, i) => {
  const prev = i > 0 ? acc[i-1].cumulative : 0
  acc.push({
    date: row.date,
    daily: row.net_pnl_dollars,
    cumulative: prev + row.net_pnl_dollars
  })
  return acc
}, [])
```

### 9.3 Win Rate by Exit Reason (`components/WinRateChart.jsx`)

Horizontal bar chart. X-axis: win rate (0–100%). Each bar is an exit reason.
Color: green bars for reasons > 50% win rate, red for < 50%.

Data query:
```javascript
supabase
  .from('cbb_positions')
  .select('exit_reason, net_pnl_cents')
  .eq('status', 'closed')
```

Group client-side by `exit_reason`, compute win rate for each.

### 9.4 Edge Calibration Chart (`components/EdgeCalibrationChart.jsx`)

This is the most analytically useful chart. It shows: **given an edge bucket at entry, what was the actual win rate?**

X-axis: edge buckets (10–12%, 12–14%, 14–16%, 16–20%, 20–25%, 25%+)
Y-axis: actual win rate %
Expected line: a diagonal from 10% edge → should win 60% of the time, etc.

The key insight: if the engine is well-calibrated, higher edge buckets should have higher win rates. If not, the edge signal needs recalibration.

Data: pull all closed positions. Group by `entry_edge` bucket. Compute win rate per bucket.

```javascript
const buckets = [
  { min: 0.10, max: 0.12, label: '10–12%' },
  { min: 0.12, max: 0.14, label: '12–14%' },
  { min: 0.14, max: 0.16, label: '14–16%' },
  { min: 0.16, max: 0.20, label: '16–20%' },
  { min: 0.20, max: 0.25, label: '20–25%' },
  { min: 0.25, max: 1.00, label: '25%+' },
]
```

Show bar + a scatter dot for the expected win rate at that edge level (a simple model: expected_win_rate ≈ 0.5 + edge * 0.5, though this is a simplification).

### 9.5 Trade Volume by Day of Week

Bar chart. X: Mon–Sun. Y: number of trades entered.
Compute from `cbb_positions` using `new Date(entry_time).getDay()`.
This tells you which days have the most games and trading opportunities.

### 9.6 Average Edge by Conference

Horizontal bar chart. Pull `cbb_positions` joined to `cbb_games`.
For each conference, compute average `entry_edge`.
Sort descending. Color bars by edge level (blue if > 15%, dim otherwise).

This identifies which conferences consistently produce pricing dislocations.

### 9.7 Hold Duration Distribution

Histogram. Buckets: 0–2 min, 2–5 min, 5–10 min, 10–15 min, 15–20 min, 20+ min.
Compute from `hold_duration_seconds` on closed positions.
Bar color: green if most positions in that bucket were wins, red otherwise.

### 9.8 PnL by Half

Simple grouped bar chart:
- H1 entries: total P&L and win rate
- H2 entries: total P&L and win rate

Directly answers: should we be entering more/less in the first half?

### 9.9 Top Performing Teams

Table of top 10 teams by net PnL (trades taken on that team).
Columns: `Team | Conference | Trades | Wins | Win Rate | Total PnL | Avg Edge`

### 9.10 Conference Breakdown

Table of all conferences with at least 2 trades.
Columns: `Conference | Trades | Win Rate | Total PnL | Avg Edge | Avg Hold`

---

## 10. Full Component Implementations

### 10.1 `App.jsx`

```jsx
import { useState } from 'react'
import Nav from './components/Nav'
import Live from './pages/Live'
import History from './pages/History'
import Analytics from './pages/Analytics'
import './index.css'

export default function App() {
  const [page, setPage] = useState('live')
  return (
    <div>
      <Nav page={page} setPage={setPage} />
      {page === 'live'      && <Live />}
      {page === 'history'   && <History />}
      {page === 'analytics' && <Analytics />}
    </div>
  )
}
```

### 10.2 `Nav.jsx`

```jsx
import WorkerStatus from './WorkerStatus'

export default function Nav({ page, setPage }) {
  return (
    <nav className="nav">
      <span className="nav-brand">CBB/TRADING</span>
      {['live', 'history', 'analytics'].map(p => (
        <a
          key={p}
          className={`nav-tab ${page === p ? 'active' : ''}`}
          onClick={() => setPage(p)}
        >
          {p.charAt(0).toUpperCase() + p.slice(1)}
        </a>
      ))}
      <div className="nav-right">
        <WorkerStatus />
      </div>
    </nav>
  )
}
```

### 10.3 `Tile.jsx`

```jsx
export default function Tile({ label, value, sub, valueClass = '', style = {} }) {
  return (
    <div className="stat-tile" style={style}>
      <div className="stat-label">{label}</div>
      <div className={`stat-value mono ${valueClass}`}>{value}</div>
      {sub && <div className="stat-sub dim">{sub}</div>}
    </div>
  )
}
```

### 10.4 `WorkerStatus.jsx`

```jsx
import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'

export default function WorkerStatus() {
  const [health, setHealth] = useState(null)

  useEffect(() => {
    const fetch = async () => {
      const { data } = await supabase
        .from('cbb_worker_health')
        .select('*')
        .order('ts', { ascending: false })
        .limit(1)
        .single()
      setHealth(data)
    }
    fetch()
    const iv = setInterval(fetch, 30000)
    return () => clearInterval(iv)
  }, [])

  if (!health) return <span className="tiny dim">Loading...</span>

  const age = (Date.now() - new Date(health.ts).getTime()) / 1000
  const dotClass = age < 90 ? 'online' : age < 180 ? 'stale' : 'offline'
  const label = age < 90 ? 'Online' : age < 180 ? 'Stale' : 'Offline'

  return (
    <div className="row" style={{ fontSize: 12 }}>
      <span className={`status-dot ${dotClass}`} />
      <span className={dotClass === 'offline' ? 'red' : 'dim'}>
        {label}
      </span>
      <span className="dim">·</span>
      <span className="dim mono">Loop #{health.loop_count?.toLocaleString()}</span>
      <span className="dim">·</span>
      <span className="dim">
        {age < 60 ? `${Math.floor(age)}s ago` : `${Math.floor(age/60)}m ago`}
      </span>
      {health.paper_mode && (
        <>
          <span className="dim">·</span>
          <span className="badge badge-yellow">Paper</span>
        </>
      )}
    </div>
  )
}
```

---

## 11. `index.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>CBB Trading</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet" />
</head>
<body>
  <div id="root"></div>
  <script type="module" src="/src/App.jsx"></script>
</body>
</html>
```

Wait — Vite needs a main entry point. Correct entry:

```html
  <script type="module" src="/src/main.jsx"></script>
```

### `src/main.jsx`

```jsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
```

---

## 12. `package.json`

```json
{
  "name": "cbb-trading",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@supabase/supabase-js": "^2.43.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "recharts": "^2.12.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.2.0",
    "vite": "^5.2.0"
  }
}
```

---

## 13. `vite.config.js`

```javascript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
  },
})
```

---

## 14. `netlify.toml`

This file lives at `dashboard/netlify.toml`. Netlify reads it relative to the base directory, so the paths here are relative to `dashboard/`.

```toml
[build]
  command = "npm run build"
  publish = "dist"

[build.environment]
  NODE_VERSION = "20"

[[redirects]]
  from   = "/*"
  to     = "/index.html"
  status = 200
```

---

## 15. `.env.example`

```
VITE_SUPABASE_URL=https://xxxxxxxxxxx.supabase.co
VITE_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

## 16. Supabase RLS Policy Notes

The dashboard uses the **anon key**. For the SELECT queries to work, you must enable Row Level Security on each table and add a policy:

```sql
-- Add to migration or run manually for each table:
ALTER TABLE cbb_positions      ENABLE ROW LEVEL SECURITY;
ALTER TABLE cbb_games          ENABLE ROW LEVEL SECURITY;
ALTER TABLE cbb_game_states    ENABLE ROW LEVEL SECURITY;
ALTER TABLE cbb_signals        ENABLE ROW LEVEL SECURITY;
ALTER TABLE cbb_daily_pnl      ENABLE ROW LEVEL SECURITY;
ALTER TABLE cbb_bankroll       ENABLE ROW LEVEL SECURITY;
ALTER TABLE cbb_worker_health  ENABLE ROW LEVEL SECURITY;
ALTER TABLE cbb_unmapped_teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE team_name_mapping  ENABLE ROW LEVEL SECURITY;

-- Read-only access for the anon role (dashboard):
CREATE POLICY "anon_read" ON cbb_positions      FOR SELECT USING (true);
CREATE POLICY "anon_read" ON cbb_games          FOR SELECT USING (true);
CREATE POLICY "anon_read" ON cbb_game_states    FOR SELECT USING (true);
CREATE POLICY "anon_read" ON cbb_signals        FOR SELECT USING (true);
CREATE POLICY "anon_read" ON cbb_daily_pnl      FOR SELECT USING (true);
CREATE POLICY "anon_read" ON cbb_bankroll       FOR SELECT USING (true);
CREATE POLICY "anon_read" ON cbb_worker_health  FOR SELECT USING (true);
CREATE POLICY "anon_read" ON cbb_unmapped_teams FOR SELECT USING (true);
CREATE POLICY "anon_read" ON team_name_mapping  FOR SELECT USING (true);
```

These policies grant public read-only access. Since this is trading P&L data you'd prefer to keep private, optionally add `auth.uid() IS NOT NULL` instead of `true` — but that requires a Supabase Auth login flow, which is out of scope for this MVP.

For MVP: leave `USING (true)` and accept that anyone with the URL can view. The anon key is already public-facing from the Netlify bundle anyway. The data exposed is trading stats — no personal/financial credentials.

---

## 17. Deployment Steps

1. Push the `dashboard/` directory to the `cbb-trading` GitHub repo
2. In Netlify: **New site → Import from GitHub → select `cbb-trading`**
3. Set **Base directory:** `dashboard`
4. Set **Build command:** `npm run build`
5. Set **Publish directory:** `dist` (Netlify resolves this relative to the base directory)
6. Add environment variables: `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`
7. Click **Deploy**
8. (Optional) Set custom domain or keep `cbb-trading.netlify.app`

Netlify and Railway are both connected to the same `cbb-trading` repo but watch different subdirectories. Pushing a change to `cbb/` triggers a Railway redeploy; pushing a change to `dashboard/` triggers a Netlify redeploy. They are fully independent.

---

## 18. Verification Checklist

Before marking this spec complete:

- [ ] `npm run build` in `/dashboard` exits with no errors
- [ ] Live page loads and shows worker status (online/offline/stale)
- [ ] Stat tiles load with real data from Supabase
- [ ] Open positions table renders (or shows "No open positions" empty state)
- [ ] Live games feed shows game cards
- [ ] Signal log shows last 20 signals
- [ ] History page filters work (date range, mode, conference)
- [ ] Settled positions table is sortable
- [ ] Unmapped teams panel shows any existing rows
- [ ] Analytics page renders all 8 charts without errors
- [ ] Cumulative PnL chart shows a line (or flat line at $0 if no trades yet)
- [ ] Site deployed to Netlify and accessible at HTTPS URL
- [ ] Anon key is in the Netlify env vars, NOT in the git repo
- [ ] Page auto-refreshes every 30s on the Live tab only

---

*End of Spec 3 of 3*
*Build order: Spec 1 → Spec 2 → Spec 3*
*All three specs together form the complete CBB trading system.*
