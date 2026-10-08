"""Fixed, local-only bench policy.

Stock CAN communication, Panda safety modes, and the normal vehicle-control and
engagement state machine stay fully intact so the physical simulator rig works.
Only the stock driver monitoring, stock seatbelt events, and stock IR/LED output
are removed, as requested, so the replacement monitoring/illumination software
can be developed against this build.
"""
import hashlib
import inspect
import json
import os
import re
from pathlib import Path

BENCH_ONLY = True
ACK_ENV = "BKV_ISOLATED_BENCH"
# The bench runs offline with the updater disabled, so upstream's
# connectivity/update lockout (which blocks going onroad after ~a month
# without a successful update check) must never apply here.
UPDATES_DISABLED = True
# Saved offline/update warnings from a previous stock install are cleared at
# bench startup so they neither block startup nor linger in the offroad UI.
STALE_UPDATE_KEYS = (
  "Offroad_ConnectivityNeeded", "Offroad_ConnectivityNeededPrompt",
  "Offroad_UpdateFailed", "LastUpdateException",
)
# Stock driver-monitoring processes never run on the bench. The updater stays
# off because the bench launcher never installs or swaps software. Every other
# upstream process, including pandad/card/controlsd/selfdrived, runs stock.
BENCH_DISABLED_PROCESSES = frozenset({
  "dmonitoringd", "dmonitoringmodeld", "updated",
})


def never_run(*args, **kwargs):
  return False


def restrict_processes(processes):
  # Only the requested removals are enforced; the simulator needs everything else.
  for process in processes:
    if process.name in BENCH_DISABLED_PROCESSES:
      process.enabled = False
      process.should_run = never_run
  return processes


def require_process(name):
  if name in BENCH_DISABLED_PROCESSES:
    raise RuntimeError(f"BKV bench refuses stock process: {name}")


def require_acknowledgment(environ=None):
  environ = os.environ if environ is None else environ
  if environ.get(ACK_ENV) != "1":
    raise RuntimeError("Bench only: isolate from driving and set BKV_ISOLATED_BENCH=1")


def reset_direct_leds(root=Path("/sys/class/leds"), required=False):
  paths = [root / "led:switch_2" / "brightness", root / "led:torch_2" / "brightness"]
  if required and not all(path.exists() for path in paths):
    raise RuntimeError("Comma 4 LED controls unavailable; refusing bench startup")
  for path in paths:
    if path.exists():
      path.write_text("0\n")
      if path.read_text().strip() != "0":
        raise RuntimeError(f"LED did not turn off: {path}")


def require_no_vehicle_services(root=Path("/proc")):
  # Preflight only: a leftover stock manager (or its children) must be stopped
  # before the bench manager starts, so two processes never fight over the
  # Panda or the same message topics. The bench build itself starts its own
  # normal pandad/card/controlsd after this check.
  if not root.is_dir():
    raise RuntimeError("Bench hardware preflight requires Linux /proc")
  blocked = re.compile(r"\b(pandad|card|controlsd|joystickd|maneuversd|dmonitoringd|dmonitoringmodeld)\b")
  for directory in root.iterdir():
    if not directory.name.isdigit() or int(directory.name) == os.getpid():
      continue
    try:
      command = (directory / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except FileNotFoundError:
      continue
    if blocked.search(command):
      raise RuntimeError(f"Stop existing vehicle/stock DM service before bench startup: PID {directory.name}")


def bench_panda_preflight(panda_class):
  # Opportunistic hardware pass: zero stock IR on any connected Pandas. Missing
  # hardware is NOT fatal — this mirrors a normal comma install, where manager
  # boots to the offroad UI and stock pandad handles harness detection, bootstub
  # firmware, safety modes, and CAN on its own schedule.
  serials = panda_class.list()
  direct_leds_required = False
  for serial in serials:
    with panda_class(serial, cli=False, disable_checks=False) as panda:
      if panda.bootstub:
        continue  # stock pandad handles bootstub firmware as in a normal install
      panda.set_ir_power(0)
      direct_leds_required |= panda.get_type() == panda_class.HW_TYPE_CUATRO
  return bool(serials), direct_leds_required


def clear_stale_update_alerts():
  try:
    if (Path(__file__).resolve().parent / "iqpilot").exists():
      from iqpilot.common.params import Params
    else:
      from openpilot.common.params import Params
  except Exception:
    return
  try:
    params = Params()
    for key in STALE_UPDATE_KEYS:
      params.remove(key)
  except Exception:
    pass


def initialize_bench():
  require_acknowledgment()
  require_no_vehicle_services()
  clear_stale_update_alerts()
  from panda import Panda

  root = Path(__file__).resolve().parent
  manifest = json.loads((root / "BKV_BENCH_NATIVE.json").read_text())
  if hashlib.sha256((root / manifest["binary"]).read_bytes()).hexdigest() != manifest["bench_sha256"]:
    raise RuntimeError("Native Panda executable changed; refusing bench startup")
  panda_root = root / "artifacts/package_runtime/panda" if (root / "iqpilot").exists() else root / "panda"
  if not Path(inspect.getfile(Panda)).resolve().is_relative_to(panda_root):
    raise RuntimeError("Bench must use this checkout's confined Panda API")

  required = bench_panda_preflight(Panda)
  reset_direct_leds(required=required)
  print("BKV BENCH ONLY: stock CAN/vehicle control intact; stock DM, seatbelt events, and IR disabled.", flush=True)


if __name__ == "__main__":
  initialize_bench()