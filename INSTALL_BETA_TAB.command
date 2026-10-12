#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if command -v python3.12 >/dev/null 2>&1; then
  python3.12 install_beta_dashboard.py "$@"
else
  python3 install_beta_dashboard.py "$@"
fi
