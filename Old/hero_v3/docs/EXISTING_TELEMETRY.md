# What the supplied telemetry can establish

No `hero_eval_records.jsonl`, resolved outcome ledger, complete OHLC archive, or broker closed-order export is included in the root ZIP or nested September 22 backup. The data consists of a current execution-state snapshot, last-status-per-ticker telemetry, and an older console log. These do not establish daily realized P&L, expectancy or that every breakout reversed.

| Saved position | Quantity | Average option entry | Underlying reference | Extension_R | VIC |
|---|---:|---:|---:|---:|---|
| SPY 2026-09-25 PUT, strike 771 | 7 | $3.88 | $768.50 | 1.8812 | PERMIT, SHADOW mode |
| QQQ 2026-09-25 PUT, strike 745 | 5 | $6.15 | $740.7000 | 1.4356 | VETO, SHADOW mode |

These are snapshot records, not newly verified broker holdings. Stop/target status lines carry underlying prices, not current option liquidation prices. No realized profit or loss is calculated from them.

The root source has >1R extension in shadow; both recorded positions exceed that. The later per-ticker telemetry also includes an AMZN VIC veto. This is consistent with versions or operating modes changing intraday, but does not identify the exact running process. Capture source SHA, loaded config, startup time and interpreter/launcher path for future investigations.

Holly and dashboard hard-coded win rates are not admissible performance evidence. The delivery includes comparison code, but a report on this attachment must return **insufficient comparable data**. The raw momentum research baseline is retained for future observations; it is not a backfilled reconstruction of today's missing history.
