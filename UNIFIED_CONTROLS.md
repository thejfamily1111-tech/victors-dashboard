# Victor Terminal unified controls

VictorTerminal.com is the operating dashboard. The QQQ Terminal tab has separate ON/OFF controls for QQQ trading, daytime QQQ research, overnight research, and VIC. The Beta Research tab has its own engine control and Overview, Research, Positions, and Activity sections.

All trading remains paper trading. OFF prevents new activity; existing positions still receive risk management. A requested change is not confirmation: the dashboard requires a fresh Mac receipt, the matching revision, and the worker's acknowledgement before showing it as applied. Missing or stale receipts remain unconfirmed.

## One-time connection

Install the matching unified Mac package into the existing QQQ and Beta Research folders. Keep each project's existing environment, credentials, data, and virtual environment. The installer verifies source hashes, backs up changed files, and starts one background connection at login. Busy old trading workers must finish safely before source replacement; staging an update does not mean installation succeeded.

The private Streamlit app needs these top-level secrets in addition to its existing dashboard PIN and telemetry settings:

```toml
CONTROL_GITHUB_TOKEN = "the existing private Mac connection token"
CONTROL_DEVICE_ID = "the existing 32-character device identifier"
```

The installer can save these two settings privately on the Mac for the one-time app setup. Add them to the existing Streamlit secrets; preserve the existing settings. Never commit the settings file or share it in chat. The dedicated connection token needs contents access to the existing private victor-terminal-research repository and vic-premarket-handoff branch. GitHub repository tokens cannot be restricted to individual file paths.

After setup, use only the dashboard buttons for routine operation. No daily commands or open Terminal window are required. The Mac must remain powered on, connected, and logged in. The background connection cannot operate while the Mac is shut down or logged out.

## Confirmation and recovery

The controls start OFF on a new installation. ON is unavailable until the dashboard has a fresh connection receipt. OFF can be saved when the Mac is offline and remains visibly pending until consumed. Connection lease expiry blocks new entries and research; position management continues.

QQQ and Beta use the same existing telemetry upload. No separate Beta uploader or new Supabase migration is required. Beta progress includes both worker heartbeats and last completed work, so an active process cannot be confused with a completed research scan. SEC and AI diagnostics retain the actual failure stage.

The release has offline control, runtime, telemetry, and UI tests. Live readiness requires installing the Mac package, configuring the private app connection, and verifying fresh worker acknowledgements. A GitHub commit alone does not confirm a successful live deployment or provider access.
