"""Publish read-only Beta records; never run research or submit orders."""
import argparse
from pathlib import Path
import time
from dotenv import dotenv_values
from beta_panel.snapshot import PRIVATE_KEY, read_local
from beta_panel.transport import LinkError, rpc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--beta-dir', type=Path, default=Path.home() / 'Desktop' / 'Beta Research')
    parser.add_argument('--settings', type=Path, default=Path.home() / 'Desktop' / 'Coding' / '.env')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    settings = dotenv_values(args.settings.expanduser(), interpolate=False)
    secrets = tuple(v for k, v in settings.items() if PRIVATE_KEY.search(k) and v)
    delay = 30
    while True:
        try:
            snapshot = read_local(args.beta_dir, secrets=secrets)
            rpc(settings.get('TELEMETRY_URL'), settings.get('TELEMETRY_PUBLISHABLE_KEY'),
                settings.get('TELEMETRY_WRITE_TOKEN'), snapshot=snapshot)
            print('Beta dashboard report published. Trading state unchanged.', flush=True)
            delay = 30
        except LinkError as exc:
            print(str(exc), flush=True)
            if args.once or exc.status in (401, 403, 404):
                return 1
            delay = min(max(delay * 2, 60), 900)
        except Exception as exc:
            print(f'Beta report not published ({type(exc).__name__}). Check the local ledger and settings.', flush=True)
            if args.once:
                return 1
            delay = min(max(delay * 2, 60), 900)
        if args.once:
            return 0
        time.sleep(delay)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('Beta uploader stopped. No trading process was changed.')
