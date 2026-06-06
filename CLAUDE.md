# ORION Trading Bot — Project Memory

## CRITICAL: Preserve V2.5.14 Features
ORION V2.5.14 changes must be preserved in code — all updates documented in ORION_V2_5_14_CHANGES_LOG.txt.

Key features (DO NOT remove or modify without explicit user approval and new backtest evidence):
1. **7-tier profit lock ladder** replacing 3-tier ratchet
2. **VWAP triple confirmation** with futures VWAP as primary gate
3. **Nifty FUT token auto-resolution** from Kite instruments at boot
4. **VWAP trail exit** for VWAP engine trades (other engines use SMA8 low)
5. **Integrated EOD data capture** with futures + option + spot VWAP on all 3 timeframes (5m/15m/1h)
6. **Data validation post-capture** — checks all timeframes, VWAP columns, futures files

## EOD Data Output
Path: `daily_option_data/YYYY-MM-DD/`
Files: `nifty_5m/15m/1h.csv`, `nifty_fut_5m/15m/1h.csv`, `CE/PE/<strike>.csv` — all with VWAP column.

## Backtest Script
`fetch_and_backtest.py` reads from local `daily_option_data/` (NOT from Kite). Kite fallback only for futures if `nifty_fut_15m.csv` not saved locally.
