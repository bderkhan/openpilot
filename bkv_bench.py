"""Fixed, local-only bench policy. This branch cannot run vehicle control."""
import hashlib
import inspect
import json
import os
import re
from pathlib import Path

BENCH_ONLY = True
ACK_ENV = "BKV_ISOLATED_BENCH"
ALLOWED_PROCESSES = frozenset({
  "camerad", "webcamerad", "sensord", "ui", "raylib_ui", "logmessaged",
  "loggerd", "encoderd", "logcatd", "journald", "proclogd", "tombstoned",
  "modeld", "modeld_snpe", "modeld_tinygrad", "iqmodeld",
  "calibrationd", "locationd", "locationd_llk", "iqlocd", "radard", "plannerd",
})


def never_run(*args, **kwargs):
  return False


def restrict_processes(processes):
  # New upstream services are denied until explicitly reviewed for bench use.
  for process in processes:
    if process.name not in ALLOWED_PROCESSES:
      process.enabled = False
      process.should_run = never_run
  return processes


def require_process(name):
  if name not in ALLOWED_PROCESSES:
    raise RuntimeError(f"BKV bench refuses process: {name}")


def require_acknowledgment(environ=None):
  environ = os.environ if environ is None else environ
  if environ.get(ACK_ENV) != "1":
    raise RuntimeError("Bench only: isolate from vehicles and set BKV_ISOLATED_BENCH=1")


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


def quiet_pandas(panda_class):
  serials = panda_class.list()
  if not serials:
    raise RuntimeError("No Panda detected; cannot verify hardware isolation")
  direct_leds_required = False
  for serial in serials:
    with panda_class(serial, cli=False, disable_checks=False) as panda:
      if panda.bootstub:
        raise RuntimeError("Panda is in bootstub; bench startup will not flash firmware")
      panda.set_safety_mode()
      for bus in range(3):
        panda.can_clear(bus)
        panda.set_can_enable(bus, False)
      panda.set_ir_power(0)
      # No stock pandad is running, so retain full cooling throughout the test.
      panda.set_fan_power(100)
      direct_leds_required |= panda.get_type() == panda_class.HW_TYPE_CUATRO
      health = panda.health()
      if int(health["safety_mode"]) != 0 or health["controls_allowed"]:
        raise RuntimeError("Panda did not enter silent, non-actuating mode")
  return direct_leds_required


def initialize_bench():
  require_acknowledgment()
  require_no_vehicle_services()
  from panda import Panda

  root = Path(__file__).resolve().parent
  manifest = json.loads((root / "BKV_BENCH_NATIVE.json").read_text())
  if hashlib.sha256((root / manifest["binary"]).read_bytes()).hexdigest() != manifest["bench_sha256"]:
    raise RuntimeError("Native Panda executable changed; refusing bench startup")
  panda_root = root / "artifacts/package_runtime/panda" if (root / "iqpilot").exists() else root / "panda"
  if not Path(inspect.getfile(Panda)).resolve().is_relative_to(panda_root):
    raise RuntimeError("Bench must use this checkout's confined Panda API")

  required = quiet_pandas(Panda)
  reset_direct_leds(required=required)
  print("BKV BENCH ONLY: CAN disabled, stock DM/seatbelt events/IR disabled.", flush=True)


if __name__ == "__main__":
  initialize_bench()
