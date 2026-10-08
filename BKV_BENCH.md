# BKV Local Bench Handoff

## Source and Scope

- Repository: Comma 4 sunnypilot.
- Base: upstream `staging`, v2026.003.000, dated 2026-09-18.
- Base commit: `81d7957c0a5fd0fc0874245e7c109e296f2a507f`.
- Local-only branch: `BKVBench-20261007`.
- OS target: AGNOS 19.7, as specified by this upstream release.
- Prepared October 7, 2026. No push, custom installer, or physical-device validation.

Intended for the lab bench: a real comma device and Panda connected to the
physical Toyota-mimicking simulator rig. Stock CAN communication, Panda safety
modes, vehicle actuation, and the normal engagement state machine are fully
intact so the simulator works end to end. Only the stock driver monitoring,
stock seatbelt events, and stock IR/LED output are removed so the replacement
monitoring/illumination software can be developed against this build.

## Removed (as requested)

1. Stock `dmonitoringd` and `dmonitoringmodeld` never start. The bench policy
   (`bkv_bench.py`) disables exactly three processes: the two stock DM
   processes and `updated`. Every other upstream process runs stock,
   including `pandad`, `card`, `controlsd`, `selfdrived`, `hardwared`, and
   `joystickd`. There is no allowlist; unknown upstream processes are not
   blocked.
2. Missing stock `driverMonitoringState` cannot break the run:
   `selfdrived` ignores it in health checks and skips the stock DM
   lockout/alert-event block, and `controlsd` cannot trigger the stock-DM
   force-decel/escalation path. Both are gated behind
   `STOCK_DRIVER_MONITORING_ENABLED = False` (same pattern as the private
   `Comma4BKV` handoff branch). The onboarding DM tutorial does not wait for
   the stock face detector, and circular alerts are no longer hidden when
   `driverStateV2` is absent.
3. The common car-event path no longer emits stock seatbelt events
   (`seatbeltNotLatched`). The raw seatbelt signal stays parsed in car state
   so the replacement seatbelt monitor can consume it.
4. IR/LED output is off through every stock path:
   - `openpilot/common/hardware/comma/hardware.py`/`hardware.h`
     `set_ir_power()` are no-ops.
   - `openpilot/selfdrive/pandad/panda.cc` `Panda::set_ir_pwr()` is a no-op
     (source-level, for rebuilds), and `main.cc` starts normally.
   - `panda/python/__init__.py` `Panda.set_ir_power()` always sends 0 to
     USB request `0xb0`.
   - The prebuilt native `pandad` binary's `Panda::set_ir_pwr` and
     `HardwareComma::set_ir_power` entries are patched to immediate ARM64
     `ret` instructions, mirroring the proven `Comma4BKV` binary patches.
     The ELF entry point and every other byte are stock, so CAN is untouched.
     Hashes and offsets are in `BKV_BENCH_NATIVE.json`.
   - `launch_chffrplus.sh`/bench startup resets `led:switch_2` and
     `led:torch_2` brightness to zero once before manager starts.

## Intact (stock behavior)

- Panda `can_send`/`can_send_many`, CAN receive, `set_safety_mode` (any mode),
  `set_can_enable`, and engaged heartbeats are unmodified stock.
- `pandad` runs normally: no `NOBOARD` export, no process blocking, no
  silent-mode forcing, no transceiver disabling, no fan override.
- The normal driving/engagement state machine, alerts, and all upstream
  services are available. The rig's CAN bus is treated like a real car.
- Chestnut/big-model support, the model selector, and all other new v2026.003
  upstream behavior are unmodified.

## Bench Startup Contract

Prepare a compatible upstream OS and Python/runtime dependencies on the bench
device before transferring this local bench checkout. The launcher will not
download or install them. Stop the stock manager and its children before
starting the bench manager; the preflight refuses startup if a leftover
vehicle-control or stock-DM process is running, if no Panda is detected, if a
Panda is in bootstub, if the native `pandad` hash does not match the
manifest, or if the Comma 4 LED controls cannot be reset and verified.

From the root of this checkout on the prepared bench device:

```bash
BKV_ISOLATED_BENCH=1 bash launch_bkv_bench.sh
```

The bench launcher still never upgrades the OS, swaps an overlay, registers
with cloud services, or starts the updater; manager init skips network
registration. An OS-version mismatch produces a clear refusal instead of an
update loop. The acknowledgment is a bench gate, not a mode switch.

Because stock `hardwared` and `card` run normally against the real comma
device and the rig's CAN, no synthetic `deviceState`/`carParams` publishers
are needed; do not run a second publisher for topics the device already owns.

## Handoff notes for the replacement DM/seatbelt/IR implementation

- If the replacement monitor publishes `driverMonitoringState`, re-enable the
  health requirement and event ingestion intentionally by flipping
  `STOCK_DRIVER_MONITORING_ENABLED` in `selfdrived.py`/`controlsd.py`, and
  remove the stock DM names from `BENCH_DISABLED_PROCESSES` in `bkv_bench.py`.
- If the replacement should drive the LEDs again, deliberately re-enable the
  clamp points listed above and coordinate with the startup reset so the
  initial reset does not clear the replacement's brightness. A rebuilt native
  `pandad` changes its hash: re-audit both LED setter entries and update
  `BKV_BENCH_NATIVE.json` before bench startup will accept it.
- The stock DM source files remain in-tree for reference; they are inactive.

## Verification

```bash
python3 bkv_bench_tests.py
```

The host suite exercises the production process configuration and method
bodies with mocked hardware: stock CAN/safety-mode/heartbeat behavior, IR
zero-clamping, disabled stock-DM processes, stock DM runtime gating, seatbelt
event removal, bench preflight failure cases, LED writes, the onboarding
bypass, the launcher acknowledgment, and the native binary hash/patch
manifest. The patched IR/LED entries were also emulated under ARM64 and return
immediately with no memory writes or register side effects.

Hardware boot, camera streams (note this release uses `cabinCameraState`
topic names), LED output, and the coworker's replacement software still
require validation on the bench device. This is a bench build for the
simulator rig; a road-use build must retain working driver monitoring and
seatbelt engagement checks.