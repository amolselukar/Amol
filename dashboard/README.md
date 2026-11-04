# ORION Control — dashboard

Built 2026-08-26 so past performance never has to be re-derived by hand.

## How to open it

The server runs on the VM, port **8787**, protected by a token:

    token: /home/selukar_amol123/Amol/dashboard/.dash_token
    current value: 3KjgYVNb-NzMjumpbvmy3rka

**Option A — SSH tunnel (works right now, no firewall change):**

    gcloud compute ssh <this-vm> -- -L 8787:localhost:8787

then open in a browser: `http://localhost:8787/?t=3KjgYVNb-NzMjumpbvmy3rka`

**Option B — open the port (then reachable from any browser/phone):**
Add a GCP firewall rule allowing TCP 8787 to this VM, then open
`http://34.100.170.253:8787/?t=3KjgYVNb-NzMjumpbvmy3rka`

I could not do this from the VM — its service account lacks firewall scopes.
Prefer restricting the source range to your own IP. Without the correct `?t=`
token every request is refused with 403, so the token is the only thing
standing between the page and the internet if you open it wide.

## Tabs

| Tab | What it shows |
|---|---|
| **Today** | Live NIFTY + SENSEX at the top, today's P&L per bot and per engine, and every open position with live LTP and unrealised P&L |
| **Daily P&L** | One row per trading day, per-bot columns, running total. Click any row to expand every individual trade with entry, exit, reason and rupees |
| **Carried Stocks** | Every carried stock position with live stock price, live option price, entry stock price, stop level, day N/5, unrealised; plus closed stock trades per day with exit reasons |
| **Engines & Logic** | Every engine, its all-time P&L and win count, and a plain description of what its rules actually are |

Page auto-refreshes every 20 seconds; index and position prices are cached 15s
server-side.

## Pieces

| File | Role |
|---|---|
| `collector.py` | Reads bot state files, flight-recorder logs, shadow CSVs and the stocks trade book; writes the archive. Read-only w.r.t. every bot file |
| `data/snapshots.json` | **Append-only capture store — the durable truth.** Never delete this |
| `data/history.json` | Derived view the page reads; safe to delete, rebuilt on next run |
| `server.py` | Stdlib-only HTTP server (no pip installs). Re-runs the collector every 60s |
| `start_dashboard.sh` | Idempotent launcher used by cron |
| `.dash_token` | Access token, chmod 600 |

## Why the append-only store exists

Each bot keeps the day's closed trades in `trades_today` inside its state file
and **wipes it at the next day boundary**. The flight-recorder logs are not a
reliable fallback — the SENSEX ones on disk and in git contain only the boot
banner. So the collector must capture trades while the day is still live and
keep its own permanent copy. That is what cron does:

    */5  * * * *          keep the dashboard up (idempotent)
    @reboot               start it after a VM reboot
    */10 3-11 * * 1-5     capture trades every 10 min through the session
    5 10 * * 1-5          final capture at 15:35 IST, after the bots stop

## Coverage, honestly

- **NIFTY V2.5.20** — backfilled from flight-recorder logs to 2026-07-13;
  79 log-paired trades, every pair validated against the logged `pnl/sh`
  (0 mismatches, 0 unmatched exits). Shadow books APEX/T5/EXP12 come from
  their own CSVs.
- **SENSEX V2.5.20** — history starts **2026-08-26**. Its flight-recorder logs
  hold no trade lines, so 08-24 and 08-25 could not be recovered. From now on
  it is captured live like everything else.
- **STOCKS_V1** — from `Stocks_TradeBook.csv`, complete since 2026-08-24.

Totals shown on the page are exactly what is archived — no estimates.
