# HERO / VIC / LEARN — paper refactor v3

This is a reviewed replacement release, not a deployed bot. No account was accessed and no broker order was sent while building it. Read **docs/REVIEW.md** before migration. The source archive's legacy state shows open positions: do not discard or overwrite your current state while positions/orders remain.

## What changes

HERO trades confirmed opening-range failures, initially with mode B (one further confirming completed 5-minute candle). VIC vetoes always block. Options come only from broker snapshots. Stops sit beyond the failure extreme and initial R remains fixed. Full option premium bounds sizing, with a maximum 0.5% equity per trade and 3.5% portfolio premium exposure. The new dashboard reads engine state without recalculating decisions.

Modes A/C, raw momentum baseline, descriptive Alpha, RVOL, ORB width, and sweep depth are research observations. They do not override hard gates. Profitable performance has not been established.

## Files and dependency map

| Existing file | Replacement / responsibility |
|---|---|
| research_momentum_bot.py | Same name: scheduler, paper adapter, order journal, risk and orchestration |
| market_mechanics_bible.py | Same name: canonical ORB, features, fade state machine, raw baseline |
| market_barometer.py | Same name: completed daily/1H/4H context, VIC permission |
| option_engine.py | Same name: actual broker Greeks, quote/contract eligibility and selection |
| alpha_engine.py | Same name: descriptive score from production features, shadow only |
| rvol_engine.py | Same name: facade over canonical same-clock calculation |
| safe_yf.py | Same name: bounded data fetches, pacing, locked cache |
| learn_tracker.py | Same name: append-only v3 decision/outcome journals and research summaries |
| resolve_daily_candidates.py | Same name: explicit-date offline 1m path resolution |
| desk_report_cards.py | Same name: empirical comparisons from v3 records |
| dashboard.py | Same name: read-only Streamlit monitor |
| economic_calendar.py | Same name: explicit NOT_CONFIGURED; unverified dates removed |
| *_clean_v2.py | Not present in attachment; do not invent parallel production files |
| holly_engine.py, ai_manager.py, research_logger.py | Not imported by v3; source retained as archive/*.py.txt |
| buy_tesla.py, trader_bot.py, watchlist_scanner.py, test_order.py | Independent order-capable scripts; archived as non-executable text |
| test_crypto.py | Omitted because it contains literal credentials and submits on import |
| fundamental_engine.py, market_intelligence.py, market_check.py, test_account.py | Archived; outside new production dashboard |

One execution entry point: `research_momentum_bot.py`. Import direction is HERO → mechanics / VIC / options / Alpha / LEARN / data. Dashboard reads `bot_telemetry.json`. Resolver/report cards read journals and cannot modify strategy/config.

## Migration on your Mac

1. Keep your existing directory as the rollback copy. Stop all old launchers/scanners and the old dashboard; verify the background process is actually stopped. The uploaded files do not include your `.app` launcher, so its configured path must be checked locally.
2. Reconcile current paper orders/positions in Alpaca. Safest migration is after HERO is flat and all its entry/exit orders are terminal. Do not close unrelated account positions. Do not run the old and new engines together.
3. Extract this release to a separate directory, such as `~/hero_v3`. These commands assume its contents are directly in that directory; if extracted with a containing `hero_refactor` folder, enter that folder instead.
4. Copy your `.env` locally into this new directory. Do not upload it again. Supported names are `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY`, or `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`. Alpaca PAPER is hard-coded, with no live URL override.
5. Preserve your existing `research_data` separately. v3 writes `hero_v3_events.jsonl` and `hero_v3_outcomes.jsonl`; it does not rewrite legacy research history. Do not copy old telemetry as v3 telemetry.
6. For a flat start, use a fresh directory without an execution-state file. Existing unrelated option exposure blocks new entries for manual reconciliation; unrelated stocks remain untouched.
7. If you must migrate the supplied style of active state, stage a conversion before starting:

```bash
cd ~/hero_v3
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python migrate_state.py /absolute/path/to/old/hero_execution_state.json staged_state.json
```

The converter refuses pending setups. It preserves each active stop/R/client ID and assumes the recorded quantity is the original order quantity; startup verifies that assumption against the actual broker order and blocks on mismatch. Review the staged file, then rename it to `hero_execution_state.json` in the NEW directory. Never use the uploaded September 23 snapshot to replace a newer local state.

For a flat start, skip conversion. Then run:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
python -m compileall -q .
python research_momentum_bot.py --config hero_config.json
```

In a second terminal, from the same directory:

```bash
source .venv/bin/activate
streamlit run dashboard.py --server.address 127.0.0.1
```

The dashboard is intentionally a production monitor. The former valuation simulator and synthetic backtest panels are not part of this view. Archived originals remain available as text for reference. Update the macOS launcher to this directory/interpreter only after the checklist below passes.

`VIC_MODE=SHADOW` no longer bypasses a veto. New config is `hero_config.json`. Config changes within a session are rejected; make strategy changes between sessions. No automatic threshold tuning occurs. Paths resolve relative to the code directory, not the launcher's working directory. Keep one engine process and one state directory; the process lock is local to that directory.

## Paper validation checklist

- [ ] Rotate the key pair embedded in `test_crypto.py` if it is still valid; `.env` and credential literals were excluded from this delivery.
- [ ] Confirm PAPER account identity, options permissions, options buying power and real-time data entitlement locally.
- [ ] Run the bundled offline tests; they never load your `.env` or contact a broker.
- [ ] Confirm no legacy engine/scanner/test-order process remains running.
- [ ] Confirm 09:30–09:55 ET are exactly six start-labelled bars; ORB locks at 10:00 and never changes during that session.
- [ ] Observe an outside breach with no return: no fade. Observe two accepted closes: no later fade from that episode.
- [ ] Observe a failed close inside and next-bar continuation inside: eligible B candidate, subject to all gates.
- [ ] Confirm identical setup/signal IDs across restart; no second submission.
- [ ] Confirm VIC VETO yields zero orders even with an old SHADOW environment value.
- [ ] Confirm missing/stale quotes, missing Greeks, adjusted contracts, or insufficient budget yield zero contracts.
- [ ] Watch one small paper order through SUBMITTED → PARTIAL/FILLED → CLOSE_PENDING → CLOSED; compare exact quantity and average price to Alpaca.
- [ ] Exercise cancel/late-fill/partial-cancel and connection-loss cases in paper; confirm state is retained until broker reconciliation.
- [ ] Confirm the engine closes only tracked HERO quantities, including on an early-close session (15 minutes before market close).
- [ ] Verify dashboard candles, levels, mode, gate reasons and actual option fills match the persisted engine snapshot.
- [ ] Archive complete session 1-minute paths and broker fills. Resolve/report offline over multiple sessions before comparing models.

## Research commands

The resolver consumes local, timestamp-aware CSVs named `TICKER_YYYY-MM-DD.csv`, with columns `timestamp,Open,High,Low,Close` (Volume optional). Supply the actual broker session calendar as JSON `[{"open":"...-04:00","close":"...-04:00"}]`, including early closes. It requires complete contiguous 1m data from the signal through the session close. Missing data stays unresolved.

```bash
python resolve_daily_candidates.py --bars-dir /absolute/path/to/one_minute_data --sessions /absolute/path/to/calendar.json --as-of '2026-09-23T16:05:00-04:00'
python desk_report_cards.py > comparison.json
```

Outcomes append separately, never rewrite decision records. Repeat outcomes are analytically deduplicated by setup ID. Gross underlying path results are not actual option returns. Actual broker option P&L is recorded on CLOSED events, before fees. Do not interpret the baseline's raw-entry observations as a reproduced net legacy-strategy backtest.

## Recovery and rollback

If an order submission times out, keep the state and client order ID. The bot looks up that ID; it never blindly resubmits. An unresolved/not-found intent blocks further execution and needs broker-side investigation. Do not delete the intent just to restart trading. Likewise, corruption, unknown HERO orders, or shared-contract quantity conflicts require reconciliation.

To roll back: stop v3, confirm/cancel its pending orders, and finish/reconcile its HERO positions in PAPER. Back up v3 state and both journals. Restart the preserved old installation only after v3 is flat and its orders are terminal. Do not feed v3 state into the old engine or overwrite current state with an old snapshot. The old installation retains the issues documented in REVIEW.md; rollback is operational recovery, not an endorsement of those controls.

## Limits

No live broker session, real-market performance test, or deployment was performed. Yahoo timestamps cannot prove end-to-end feed latency; the runtime blocks stale bar completions and quotes but needs supervised paper validation. Network calls can delay the nominal 10-second risk loop. Stops are software-managed underlying triggers, not broker-held option stop orders. Broker outages can delay exits. Unknown submit outcomes intentionally require manual investigation when lookup cannot resolve them. The local single-writer lock cannot coordinate a second installation on another machine.

News/event vetoes and a complete cost-adjusted, paired legacy-versus-fade options backtest are not implemented. Option snapshot volume is explicitly missing (not fabricated); bid/ask, Greeks, IV and contract open interest are recorded. Actual time spent beyond a boundary is not knowable from 5m OHLC; outside-close minutes are labelled as a proxy. These limits remain visible in telemetry and the review.
