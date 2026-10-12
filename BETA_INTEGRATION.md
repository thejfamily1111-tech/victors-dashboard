# Beta Research in Victor Terminal

The fifth main tab is **Beta Research**. It opens on **Overview**, followed by
**Research & watchlist**, **Positions & orders**, **Activity**, and **Validation**.
The embedded panels preserve the Beta Research v0.3.3 dossier, score, company
event, financial statement, contract, order, audit and validation views.

This is a read-only presentation integration. It never imports the Beta runner
or broker, submits orders, calls SEC/OpenAI/Alpaca, or changes trading settings.
Beta's folder, SQLite ledger and research process remain separate. There is
still one shared paper brokerage account. Existing QQQ telemetry is unchanged.

## Mac dashboard

Unzip `Victor_Beta_Dashboard_Integration_v1.0.zip` in Downloads. In a new VS Code
terminal, run:

```bash
bash "$HOME/Downloads/Victor_Beta_Dashboard_Integration_v1.0/INSTALL_BETA_TAB.command"
```

The default destination is the existing `~/Desktop/Coding` folder; it does not
create another Beta Research project. If the dashboard lives elsewhere, append
`--target "/absolute/path/to/existing/dashboard"`.

Install the integration files into the existing `Coding` dashboard directory
using the packaged installer. It backs up and changes only `dashboard_views.py`
and adds the `beta_panel` package and uploader. It refuses an unrecognized
dashboard version instead of overwriting it. Restart the existing dashboard.

By default the tab reads the sibling `Beta Research/data/beta.sqlite3` in SQLite
read-only mode, including committed WAL updates. If the folder is elsewhere,
set `BETA_RESEARCH_DIR` in Coding's `.env` to its absolute path. The reader honors
Beta's `BETA_DATA_DIR` and public feed/reserve settings, without loading its API
keys into the dashboard environment. `BETA_DASHBOARD_MODE=local` explicitly
chooses local data if the main dashboard uses remote QQQ telemetry.

No separate server on port 8502 is needed for the integrated view. Starting or
stopping either dashboard does not start or stop the paper runner.

## Existing online dashboard

1. Deploy this dashboard revision to the existing website.
2. Run `BETA_TELEMETRY_SETUP.sql` once in the **existing** Supabase project's SQL
   editor. This additive migration creates `vt_private.beta_latest` and two
   Beta-only RPCs. It reuses the existing hashed reader/writer tokens and does
   not rotate them, overwrite QQQ reports or modify the existing QQQ RPCs.
3. Keep the existing website's `TELEMETRY_URL`, `TELEMETRY_PUBLISHABLE_KEY`, and
   `TELEMETRY_READ_TOKEN`. Set `BETA_DASHBOARD_MODE="remote"` if not already
   inherited from `TELEMETRY_MODE="remote"`. The writer token stays on the Mac.
4. From the existing Coding environment on the Mac, verify one upload:

   ```bash
   python beta_publish.py --once
   ```

5. Then keep the separate read-only uploader running:

   ```bash
   python beta_publish.py
   ```

Defaults are `~/Desktop/Beta Research` and `~/Desktop/Coding/.env`. Custom paths
use `--beta-dir` and `--settings`. Neither the uploader nor the SQL migration
starts trading. The website cannot directly read a Mac folder.

The uploader sends only selected Beta research/ledger collections, public
mandate settings and local provider-health counts. Identity documents and
environment files are excluded. Credential-like keys and configured secret
values are removed; source URL queries are stripped. Financial research and
position/order details are private report content protected by the existing
dashboard login and Supabase reader token. The reporter uploads every 30 seconds,
backs off on errors, and stops on access-denied or missing-endpoint responses.

The dashboard refresh follows the existing 15-second auto-refresh setting.
It labels snapshots older than two minutes and runner updates older than five
minutes. Uploader liveness is not runner liveness. A missing connection does not
mean zero positions. Unavailable data never triggers a broker action.

All positions, orders, dossiers and validation reports are included, plus the
latest 200 activity events (matching the standalone dashboard). If the complete
report exceeds 8 MB it is rejected, never silently truncated. A future paginated
transport is needed for very large histories; the current website will show its
last snapshot as stale. Local source records remain untouched.

## Verification and rollout status

Offline tests cover read-only committed-WAL access, missing-path behavior,
credential exclusion, transport destination restrictions, snapshot validation,
the five nested tabs and populated dossiers. No production data, provider calls,
paper orders or live orders are required by these tests.

The Supabase migration and online round trip must be checked after installation;
offline tests do not establish production connectivity. No historical options
backtest is implied by this dashboard change.
