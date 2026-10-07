# Victor dashboard refresh · approved 2026-10-06

Four tabs: Overview, Teams & activity, News & events, Research. The stock selector is above the completed-candle chart. BB20/2, RSI14 and volume default on; EMA9, EMA21 and VWAP are independent display toggles. Chart intervals: 5, 15, 30, 60 minutes. Existing stock research, strategy rules, simulations and supervisor research remain available.

Team details show strategies, latest scan decisions, reported positions, partial exit fills, closed trades and recorded entry context. Totals use reporting teams for the current Eastern date. Active balance means remaining invested premium; market value and unrealized P/L are separate. Closed P/L includes fully closed trades; all realized exits including partials are separately reported. Closed-day virtual balance is starting allowances plus closed P/L, not broker equity or buying power. Incomplete trade history or pending partial entries produces unavailable totals. Stale option quotes do not contribute a current market valuation.

Market cards display Yahoo indicative quotes with explicit delay and unverified bid/ask timestamps. Actual 10Y/2Y Treasury yields use FRED DGS10/DGS2 daily observations, with basis-point and relative changes against the preceding observation; they are not intraday yields. Mag-7 daily changes and preceding-session breadth use available public observations. Prior-session QQQ technical bias is computed from completed historical closes and EMA9/21, not a saved previous VIC score. Engine direction and coverage come from shared Mac telemetry; missing engine input is not substituted with a dashboard decision.

Calendars preserve today's, this week's and next-30-days views of HIGH-impact Fed/BLS/BEA events. Actual/consensus values remain N/A when the source does not provide them. Earnings cover the Mag-7; Yahoo dates are unconfirmed provider schedules. Conference-call times remain TBA pending investor-relations confirmation. No sample dates or demo prices are shipped. The existing engine publishes latest scan decisions and fill activity, not a complete chronological scan journal; that limitation is shown explicitly.

## Deployment

Streamlit Cloud: the dashboard repository main branch contains the matched five-file update. A successful GitHub push is not proof of a completed hosted redeployment.

Mac: extract Victor_Dashboard_Update_2026-10-06.zip and run INSTALL.command, or run `python3 install_dashboard.py --target "$HOME/Desktop/Coding"`. The installer backs up and replaces only dashboard.py, dashboard_views.py, dashboard_data.py, dashboard_metrics.py and telemetry_link.py. Existing credentials, trading rules, engine files and session state are retained. Restart the dashboard and telemetry uploader after installation. Updating GitHub does not change the Desktop/Coding files automatically. The uploader needs the updated telemetry_link.py to retain the new partial-entry and entry-time fields.

No paper session is started by this update. No strategy, allocation, exit policy or order behavior is changed. Passcode authentication and the positive telemetry allowlist remain required.

## Verification

Six focused calculation/transport tests, eight existing telemetry tests, and offline Streamlit checks passed: PIN boundary, all four tabs, 17 selectable team cards, missing data, selected-team callback, 60m chart, default indicator switches and separate RSI/volume panels. Market feeds and hosted deployment still need verification in the actual environment.
