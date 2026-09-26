# Engineering review — HERO / VIC / LEARN

Reviewed September 23, 2026. Status: implementation and offline validation complete; supervised broker validation remains. No trading account was accessed.

## Architecture diagnosis

The root `research_momentum_bot.py` is the strongest production-entry-point candidate: it has a main loop, is imported by the root dashboard, and its schema matches the provided execution state. The actual macOS launcher/process configuration was not supplied, so the running filename cannot be proved from the archive. No `research_momentum_bot_clean_v2.py` or `dashboard_clean_v2.py` is present. September 21 and nested September 22 backups are older, divergent versions, not alternate release entry points.

The core separation was only partial. HERO fetched its own 5m/15m features, Alpha fetched another snapshot and regime, the dashboard recomputed HERO/VIC decisions and selected Yahoo/synthetic options, and LEARN rebuilt stops independently. The result was multiple answers to the same trading decision.

The release consolidates mechanical features in `market_mechanics_bible.py`, keeps permission in `market_barometer.py`, moves broker contract eligibility to `option_engine.py`, and makes the dashboard a reader. Runtime IDs and write-ahead order state provide recovery across restarts. Archived sources are non-executable `.py.txt` files. Existing research history is not rewritten.

## Important findings

Line references below refer to the uploaded root originals, retained under `archive/` where safe.

| Severity | File / evidence | Finding and disposition |
|---|---|---|
| Critical | research_momentum_bot.py: 1044–1107 | Position query failure returned `{}`, allowing reconciliation to delete active trades. Now query errors block and preserve ownership. |
| Critical | research_momentum_bot.py: 1175–1200, 1290–1318 | EOD and stop/target exits cleared local state after requests, including failed requests. Now exit intent and broker fills remain tracked until terminal reconciliation. |
| Critical | research_momentum_bot.py: 1054–1107, 1203–1260 | Terminal canceled/expired/rejected buys were removed before reconciling partial fills. Now buy filled quantity survives cancellation. |
| Critical | research_momentum_bot.py: 1011, 1550–1622 | Random IDs plus persistence only after submit left a crash/timeout duplication window. Now deterministic IDs, persisted intent and client-ID lookup; unresolved intent blocks instead of retrying blindly. |
| High | state JSON: QQQ | Saved QQQ PUT was FILLED despite VIC VETO with scalar 0, because mode was SHADOW. Now VIC veto always blocks; environment cannot disable it. |
| High | state JSON vs root source | SPY extension 1.881R and QQQ 1.436R were filled, while attached source shadows >1R. This is evidence of source/runtime timing divergence, not proof the current gate was bypassed. Launcher identity remains unverified. |
| High | research_momentum_bot.py: 789–811 | Quote age was recorded but never filtered. Missing, future, or old option timestamps now reject eligibility and are rechecked before execution. |
| High | research_momentum_bot.py: 834–870 | Delta-linear estimated stop loss was used as risk dollars. This cannot cap nonlinear option/gap loss. New sizing uses full premium and reserves pending exposure. |
| High | research_momentum_bot.py: scan account snapshot | Buying power was fetched once for the scan, with no aggregate local premium cap. New per-decision account checks and portfolio reservations prevent local overcommitment. |
| High | original broker account.buying_power | Generic equity buying power may include margin unavailable to option purchases. New adapter requires options_buying_power. |
| High | research_momentum_bot.py: 382–408, 1644–1660 | Cooldown and scan slot were not durable setup-level deduplication. New persistent setup/breach IDs, daily config identity and a decision outbox prevent repeat firing after restart. |
| High | research_momentum_bot.py: 577–666 | Production routing directly bought continuation; trap execution disabled. No persistent acceptance episode. Replaced by explicit failure/acceptance state machine. |
| High | learn_tracker.py: 116–137 | LEARN recomputed stop/R from max(ATR, $0.50), independent of HERO. New records carry exact frozen entry/stop/R without rounding. |
| High | learn_tracker.py: 302–310 | Missing post-signal paths fell back to the last 30 bars, potentially preceding the signal or on another session. Removed; explicit date and contiguous post-decision data required. |
| High | learn_tracker.py: 353–380 | Path resolution broke early, lost later horizon returns, and only treated +2R/stop ties as ambiguous. New target-by-target resolution also detects +1R/VWAP/midpoint/opposite ties and continues full-session horizons. |
| High | resolve_daily_candidates.py: 61–75 | Rewrote the same JSONL ledger being appended by HERO, risking lost records; downloaded only latest day for unresolved history. Now offline local date-specific paths and a separate append-only outcome journal. |
| High | market_barometer.py: 74–109 | Dropped last hourly bar regardless of timestamp; 4H calendar resample could include incomplete/misaligned windows. New full 5m-grid aggregation anchored to actual session open, with explicit as-of time. |
| High | market_barometer.py: 164–178 | Missing 4H context was not itself a veto; no expected-bar freshness validation. New latest expected 1H/4H/daily windows must exist. |
| High | alpha_engine.py: 145–176 | Last 5m candle could be forming; Alpha used 5m indicators while HERO used 15m structure. New shadow Alpha consumes the already-frozen production snapshot. |
| High | alpha_engine.py / rvol_engine.py | Alpha supplied only today's bars to historical RVOL; RVOL paced 15m volume even on supplied 5m bars, and missing history became neutral defaults. Replaced with canonical same-clock ratio/percentile/z-score/sample size; missing stays null. |
| High | dashboard.py: 453–641, 755–870 | Recreated candidates, VIC decisions, contract selection and ORB levels independently, including a hard-coded CALL audit. New monitor renders engine state only. |
| High | option_engine.py: 163–222 | Fabricated synthetic contracts, quotes, Greeks, volume and OI after chain failures, sometimes status SUCCESS. Removed from active release. |
| High | dashboard.py: 368–377, 479–491; holly_engine.py | Hard-coded cash/feed-health and unsupported empirical win-rate profiles. Holly also logged assumed +2R for an observed setup. Removed from active dashboard/research path. No source backtest was supplied. |
| High | test_crypto.py and .env in ZIP | Literal credential strings in test_crypto.py; that script places an order at import. Excluded, and the supplied .env was never read or used. Rotate exposed keys if valid. |
| High | test_order.py, trader_bot.py, buy_tesla.py | Order-capable top-level code is unsafe for automatic test discovery. Archived as text; only isolated tests/ runs. Two legacy scripts also lacked required order-class imports. |
| Medium | market_mechanics_bible.py: 285–299 | ORB completeness used counts; duplicate/off-grid timestamps could impersonate six bars. New exact timestamp grid and OHLC validation. End-labelled windows now shift to correct start windows. |
| Medium | market_mechanics_bible.py: 340–350, 547–558 | Historical ORB percentile admitted incomplete sessions; attempt counting missed an initial outside close due to NaN previous value. Fixed; new fade attempts track breach episodes explicitly. |
| Medium | research_momentum_bot.py: 236–269 | Relative state paths and swallowed persistence errors could use the wrong directory or continue without restart safety. New script-relative paths, atomic fsynced writes, process lock and visible failure. |
| Medium | safe_yf.py | Claimed thread safety without a lock, returned arbitrarily stale cache on errors, and exposed a price without a source timestamp. New cache is locked and fails on fetch errors; broker timestamped underlying trades drive risk exits. |
| Medium | original 15:45-only schedule | No early-close handling. New entry cutoff is min(configured 15:00, close minus 60m); flatten is min(15:45, close minus 15m). |
| Medium | economic_calendar.py | Hard-coded 2026-09-23 FOMC meeting was wrong: Fed lists September 15–16, 2026. Static schedule removed; news risk explicitly unconfigured. Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm |
| Medium | research logs | Unknown metrics defaulted to 0/neutral and lacked shared setup/fill linkage. v3 uses null and explicit statuses, shared IDs, exact option symbols and separate order lifecycle events. |
| Medium | requirements.txt | Dashboard required streamlit-autorefresh but dependency was absent. Added and tested; Alpaca SDK pinned to tested 0.44.0. |

## Revised strategy specification

- Session is Eastern time, with actual broker calendar boundaries. Opening range uses exactly 09:30, 09:35, 09:40, 09:45, 09:50 and 09:55 start-labelled 5m candles. Snapshot freezes at first complete observation at/after 10:00; no execution before the first post-range close at 10:05.
- First bar with high above ORB high opens an upside episode; low below ORB low opens a downside episode. Every breach is journaled whether traded or not. A bar crossing both boundaries is invalidated because intrabar order is unknown.
- Two consecutive outside closes initially define acceptance. Once accepted, that episode cannot later turn into a fade. A later inside close rearms a new episode on a subsequent bar.
- Failure requires a completed close strictly between both boundaries within the configured failure window. A completed single-candle sweep-and-return qualifies for mode A; a wick touch without an inside close does not. Equality at a boundary is neither acceptance nor failure.
- Mode A: candidate at failure close. Mode B: exactly the next bar must remain inside and close farther in the fade direction. Mode C: a later bar approaches the breached boundary from inside within the ATR tolerance and closes inside. Each can emit only once per breach. Only the configured mode can submit; initial mode is B.
- Successful acceptance, expiry, return outside after failure, breach of the frozen stop, and a missing tactical bar invalidate/stop the relevant episode. Missing-bar recovery does not infer an entry from the gap.
- Upside failure → long PUT; downside failure → long CALL. These are option purchases, never naked short options.
- Stop is sweep high + 0.10 ATR for PUT or sweep low − 0.10 ATR for CALL. The stop freezes at failure. Each mode freezes its own `initial_r = abs(entry_reference - stop)` at its own candidate time; no later widening or R recalculation.
- VWAP-at-candidate, ORB midpoint, opposite boundary, 1R and 2R are frozen alternative research levels. Initial production target is midpoint. A target behind the entry is rejected, not silently swapped.
- Sweep Extension_R is maximum breach depth / frozen initial R. Because the stop is beyond the sweep and entry is inside, this ratio will normally be below 1 by construction. The requested >1R bins remain available but should not be expected to fill under this geometry. Breach depth/ATR is also recorded and is a less mechanically constrained research axis.
- Descriptive anatomy, exact clock RVOL and history sample size, ORB width, directional attempts and relative strength are logged. No wick/volume/Alpha threshold becomes an unvalidated hard gate.

## ACTIVE vs SHADOW

| Component | Treatment |
|---|---|
| PAPER, completed bars, exact locked ORB, fresh bars/quotes, broker reconciliation | ACTIVE fail-closed |
| Fade mode B and midpoint target | ACTIVE paper policy, unproven efficacy |
| VIC PERMIT/DOWNGRADE/VETO, sizing scalar | ACTIVE; no SHADOW override |
| Premium risk, portfolio cap, quantity zero, 7 names, 2 pending, 10 contracts | ACTIVE |
| Daily equity loss of 2% from first observed session equity | ACTIVE new-entry halt and pending cancellation; not a broker statement daily P&L measure |
| One setup/one breach submission, write-ahead IDs, single process lock | ACTIVE |
| Underlying structural stop, target, HERO-owned EOD exit | ACTIVE; software-managed, broker-authoritative terminal state |
| A/C entry alternatives, raw momentum baseline | SHADOW, no broker submission |
| Alpha descriptive score, RVOL, width, depth, wick/CLV, RS, daily regime | SHADOW/context; not profit probabilities |
| Outcome resolver and comparisons | OFFLINE only |
| News/event veto | NOT IMPLEMENTED; visible as unconfigured |

## Hypotheses, not proven constants

Acceptance=2 closes; failure window=3 bars; confirmation/retest window=3; stop buffer=0.10 ATR; retest tolerance=0.10 ATR; B initially; midpoint initially; fixed-R alternative=1; RVOL/width lookback=40 sessions; 1H EMA buffer=0.20 ATR; 4H obstacle bands=1R/2R; downgrade scalar=0.5; descriptive Alpha weights. These choices must be evaluated without optimizing on a single bad day. Safety/operational choices (30-second quote freshness, 180-second signal age, 2-bar pending TTL, delta .65±.10, OI ≥100, spread ≤6%, 1–7 DTE) likewise need execution-quality calibration; they are not evidence of predictive edge.

VIC 4H means strictly four regular-session hours beginning at 09:30. The remaining 2.5-hour regular-session stub is not mislabeled 4H. Early-close days may have no 4H bar; the previous full bar remains valid until a new complete window is expected. This convention differs from common chart-provider 4H conventions and is explicitly logged through timestamps.

## Validation performed

- 71 offline tests passed, with zero failures/errors/skips in the SDK-enabled run. `test_results.txt` has the test names. Tests cover all 17 requested categories, plus corrupt state, timeout-after-acceptance, partial-cancel fills, exit acknowledgement versus fill, shared-contract ownership, early closes, multi-mode research, candidate outbox recovery, config change rejection and calendar-aware HTF gaps.
- Actual Alpaca SDK request classes constructed and asserted with network calls mocked; PAPER constructor verified.
- Python syntax compilation passed.
- Streamlit AppTest rendered a production snapshot and chart with no exceptions; two tables and the ticker selector appeared. This is a functional render test, not a browser pixel review.
- No API credentials, live market feed, broker permissions, actual fills or full trading-day operation were validated. The included checklist is the deployment gate for local supervised PAPER use.

## Evidence limits / remaining work

The new raw momentum baseline preserves the old close/VWAP/15m-slope entry condition and 1 ATR stop / 2 ATR target, not the entire historical Alpha/VIC/contract/execution pipeline. It emits one research observation per qualifying bar; adjacent observations overlap. It is deliberately labelled `RAW_ENTRY_ONLY_LEGACY_GATES_NOT_REPLAYED`. A faithful economic comparison still needs archived as-of quotes/Greeks and complete fills for both policies, disjoint/out-of-sample sessions and transaction costs.

LEARN records all breach events and distinct A/B/C candidates. Breaches that never produce a tradeable failure remain state events, without an invented entry/R. Missing option snapshots, option volume, historical benchmark slots or market data remain missing. Relative strength can be absent on the first benchmark fetch and is not a hard gate. Candidate-time VWAP targets are frozen, not a hindsight moving VWAP strategy.

The resolver gives full-session underlying MFE/MAE, horizon returns and level-ordering outcomes. It requires complete 1m coverage and uses reference stop/target levels, not simulated executable fills, spread, fees or gap slippage. `sequential_unit_r_drawdown` is an ordered unit-risk observation statistic, not portfolio drawdown. Actual option fills/P&L live in broker events. No winner or profitability claim is justified yet.

Pending/active ownership is retained on failures. A broker outage can still prevent cancellation or an exit; software cannot guarantee flattening through an unavailable broker. A missing/not-found client-ID after an ambiguous submit intentionally stops progress for investigation. The main loop is synchronous, so network calls can delay risk polling; full-premium sizing bounds premium exposure but does not make software stops instant. News risk and the original non-trading valuation panels remain outside the new runtime.
