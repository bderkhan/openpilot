#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ "${BKV_ISOLATED_BENCH:-}" != "1" ]; then
  echo "BKV BENCH ONLY: isolate from vehicles, then set BKV_ISOLATED_BENCH=1." >&2
  exit 78
fi
source "$DIR/launch_env.sh"

# Bench startup never upgrades the OS, swaps an overlay, or starts cloud services.
if [ -f /AGNOS ]; then
  CURRENT_VERSION="$(</VERSION)"
  if [ "$CURRENT_VERSION" != "$AGNOS_VERSION" ] && [[ "$CURRENT_VERSION" != "$AGNOS_VERSION"-* ]]; then
    echo "Bench requires OS $AGNOS_VERSION; found $CURRENT_VERSION. Prepare the stock OS separately." >&2
    exit 78
  fi
fi

PYTHON="${BKV_BENCH_PYTHON:-/usr/local/venv/bin/python3}"
if [ ! -x "$PYTHON" ]; then
  echo "Missing device Python runtime: $PYTHON" >&2
  exit 78
fi

if [ -d "$DIR/iqpilot" ]; then
  export IQPILOT_PROPRIETARY_ROOT="$DIR/artifacts"
  export IQPILOT_SOURCE_ROOT="$DIR/iqpilot"
  export PYTHONPATH="$DIR/artifacts/package_runtime:$DIR"
  MANAGER_DIR="$DIR/iqpilot/system/manager"
elif [ -d "$DIR/openpilot/system/manager" ] && [ ! -L "$DIR/openpilot/system" ]; then
  export PYTHONPATH="$DIR:$DIR/msgq_repo:$DIR/opendbc_repo:$DIR/rednose_repo:$DIR/tinygrad_repo:$DIR/teleoprtc_repo"
  MANAGER_DIR="$DIR/openpilot/system/manager"
else
  export PYTHONPATH="$DIR"
  MANAGER_DIR="$DIR/system/manager"
fi

echo "BKV BENCH ONLY. Stock CAN and vehicle control are enabled for the simulator rig; stock DM/seatbelt events/IR stay disabled."
cd "$MANAGER_DIR"
exec "$PYTHON" ./manager.py
