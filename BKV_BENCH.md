# BKV Local Bench Handoff

## Source and Scope

- Repository: Comma 3 IQ.Pilot.
- Base: upstream `release` (stable 1.0c), dated 2026-10-07.
- Base commit: `348658b0e7c0bb4538ae757f3b3a896fb3de8429`.
- Local-only branch: `BKVBench-20261007`.
- OS target: IQ.OS 4.9.9.1, as specified by this upstream release.
- Prepared October 7, 2026. No push, custom installer, or physical-device
  validation. Upstream lists Comma 3, 3X, and 4 support; this bench copy has
  not been device-validated on either.

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
   `selfdrived` ignores it in health checks and caches no stock DM event
   names, and `controlsd` cannot trigger the stock-DM force-decel path. Both
   are gated behind `STOCK_DRIVER_MONITORING_ENABLED = False` (same pattern
   as the private `c3iq` handoff branch). The onboarding DM tutorial does not
   wait for the stock face detector.
3. Stock seatbelt behavior is removed: the common car-event path no longer
   emits `seatbeltNotLatched`, and the steering-assistance behavior no longer
   backs off on `seatbeltUnlatched` (`iqpilot/sab/behavior.py`). The raw
   seatbelt signal stays parsed in car state so the replacement seatbelt
   monitor can consume it.
4. IR/LED output is off through every stock path:
   - `iqpilot/system/hardware/tici/hardware.py` `set_ir_power()` is a no-op.
   - `artifacts/package_runtime/panda/python/__init__.py`
     `Panda.set_ir_power()` always sends 0 to USB request `0xb0`.
   - The prebuilt native `pandad` binary's `Panda::set_ir_pwr` entry is
     patched to an immediate ARM64 `ret`. The ELF entry point and every other
     byte are stock, so CAN is untouched. Hashes and offsets are in
     `BKV_BENCH_NATIVE.json`. (The prior bench approach redirected the ELF
     entry to an exit stub; that is fully reverted.)
   - Bench startup resets `led:switch_2`/`led:torch_2` brightness when
     present and requires them on Comma 4-class hardware.

## Intact (stock behavior)

- Panda `can_send`/`can_send_many`, CAN receive, `set_safety_mode` (any mode),
  `set_can_enable`, and engaged heartbeats are unmodified stock.
- `pandad` runs normally: no `NOBOARD` export, no process blocking, no
  silent-mode forcing, no transceiver disabling, no fan override.
- The normal driving/engagement state machine, IQ-specific services
  (`iqlocd`, `iqmodeld`, SAB behaviors, etc.), and all upstream processes are
  available. The rig's CAN bus is treated like a real car.

## Bench Startup Contract

Prepare a compatible upstream OS and the verified IQ.Pilot runtime/bundles on
the bench device before transferring this local bench checkout. The launcher
will not download, install, or modify signed bundles. Stop the stock manager
and its children before starting the bench manager; the preflight refuses
startup if a leftover vehicle-control or stock-DM process is running, if no
Panda is detected, if a Panda is in bootstub, or if the native `pandad` hash
does not match the manifest.

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
- If the replacement should drive IR again, deliberately re-enable the clamp
  points listed above. A rebuilt native `pandad` changes its hash: re-audit
  the IR entry and update `BKV_BENCH_NATIVE.json` before bench startup will
  accept it.
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
manifest. The patched IR entries were also emulated under ARM64 and return
immediately with no memory writes or register side effects.

Hardware boot, camera streams, LED output, and the coworker's replacement
software still require validation on the bench device. Earlier stock IQ.Pilot
releases stalled at the boot logo on the bench Comma 3; treat first boot as
unvalidated. This is a bench build for the simulator rig; a road-use build
must retain working driver monitoring and seatbelt engagement checks.