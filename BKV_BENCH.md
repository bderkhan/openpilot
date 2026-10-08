# BKV Local Bench Handoff

## Source and Scope

- Repository: Comma 3 sunnypilot.
- Base: upstream `staging-tici`, v0.10.1, dated 2025-10-13.
- Base commit: `1f7233cb983f3c13fdbba47a86f8fbc796ad9211`.
- Local-only branch: `BKVBench-20261007`.
- OS target: AGNOS 12.8, as specified by this upstream release.
- Prepared October 7, 2026. No push, custom installer, or physical-device validation.
- Intended only for an isolated simulator with a real comma device. Never connect
  a vehicle harness or enable real steering, braking, or acceleration.

The purpose is to test replacement driver monitoring, model-based seatbelt
detection for cars without a suitable belt signal, and replacement day/night
illumination control. This is NOT an engagement-capable driving build.

## Changes

1. `bkv_bench.py` restricts manager processes to reviewed camera, perception,
   UI, planning, and logging services. New/unrecognized processes default to
   disabled. Stock `dmonitoringd` and `dmonitoringmodeld` are not launched.
   MICI onboarding, where present, does not wait for the disabled stock face
   detector. No replacement monitor has been included or marked validated.
2. `card`, `controlsd`, `selfdrived`, `pandad`, `_pandad`, joystick and
   maneuver services are disabled. There are no synthetic healthy-DM publishers
   or fake engagement messages. The normal driving/engagement state machine is
   intentionally unavailable.
3. The common car-event path no longer emits stock seatbelt events. Raw vehicle
   seatbelt fields and message schemas remain intact for observations/model
   comparisons. Other car-event logic remains unchanged.
4. Python Panda CAN-send APIs raise instead of transmitting. Non-silent safety
   modes, enabling CAN transceivers, and engaged heartbeats are rejected.
5. Manager init requires explicit bench acknowledgment and refuses startup if
   an existing vehicle-control or stock DM process is detected. It verifies the
   native Panda binary before opening hardware.
6. All detected Pandas are put into silent safety mode, their transmit queues
   cleared and CAN transceivers disabled. Startup checks that safety mode is
   silent and controls are not allowed. Missing/incompatible hardware is fatal;
   startup never flashes firmware as a fallback.
7. IR is set to zero once through Panda. Comma 4 direct LED switch/torch controls
   are reset to zero and read back. Missing C4 controls, failed writes, or
   unexpected readback fail startup. Stock Python host LED setters are no-ops;
   stock Panda IR requests are clamped to zero.
8. The native prebuilt `pandad` executable exits with status 78. Its ELF entry
   is redirected to a short exit stub at `main`. Original and modified SHA-256
   values and byte locations are recorded in `BKV_BENCH_NATIVE.json`. Both the
   Python wrapper and process launchers reject attempts to start the bridge.
9. Where available, C++ IR setters are no-ops; the C4 native bridge source
   entry point also returns 78 so a rebuild cannot restore that bridge.
10. `launch_chffrplus.sh` routes directly into `launch_bkv_bench.sh`. The bench
    launcher does not upgrade the OS, install an overlay, register with cloud
    services, or start an updater. Manager init avoids network registration.
    An OS-version mismatch produces a clear refusal instead of an update loop.

Upstream source, schemas and model artifacts that are not active writers remain
for compatibility. Disabled services stay visible as stopped in manager state.
Normal upstream branches are unchanged. Earlier private cleanup branches were
also left untouched; this document does not certify those builds for road use.

## Bench Startup Contract

Prepare a compatible upstream OS and Python/runtime dependencies on the isolated
device before transferring this local bench checkout. The launcher will not
download or install them. IQ.Pilot additionally needs its matching verified
runtime/bundles already provisioned; this bench launcher does not install or
modify signed bundles.

Stop the stock manager and its children before starting the bench manager.
Do not run two managers or two publishers for the same topic.

From the root of this checkout on the prepared bench device:

```bash
BKV_ISOLATED_BENCH=1 bash launch_bkv_bench.sh
```

The acknowledgment is NOT a mode switch back to driving. The fixed source
interlocks apply independently of that environment variable.

The simulator must publish compatible `deviceState`, `carParams`, and simulated
CAN/data inputs expected by the selected perception services. In the latest C4
release camera topic names include `cabinCameraState`; adapt the harness to this
release's schemas instead of copying the older C3 message layout. The bench
does not emulate a detected physical car or enable normal openpilot engagement.
Use simulated message transport, not the real Panda CAN-transmit API. Camera
processes still follow their upstream onroad/driver-view conditions.

Stock `hardwared` is excluded so it does not compete with the simulator's
`deviceState` publisher. Since native fan control is excluded, startup requests
100% fan speed. Supervise cooling and temperature externally throughout tests;
this is not a replacement thermal controller.

Your coworker's replacement monitor/illumination process is not included here.
Add it as a separate non-actuating process only after reviewing it, explicitly
allow it in the bench policy, and test its message compatibility. Do not restore
vehicle-control/Panda processes. Host stock LED setters do not repeatedly reset
a replacement controller after startup; the replacement controller must own its
own tested illumination path.

Before returning a device to any stock driving build, remove this bench runtime,
power-cycle it, and verify the stock firmware/software safety behavior. These
bench changes are not a permanent hardware modification or firmware flash.

## Verification

```bash
python3 bkv_bench_tests.py
```

The host suite exercises production process configuration and method bodies with
mocked hardware, blocked CAN attempts, startup failure cases, LED writes, native
binary hashes/entry point and seatbelt events. It does not import or execute
ARM64 device extensions on the Mac. Native exit instructions were separately
verified under ARM64 emulation, with all bytes outside the entry/header patch
unchanged from upstream.

Hardware boot, camera streams, actual zero LED output, temperatures, and the
coworker's replacement software still require bench validation on the device.
Any upstream binary replacement/rebuild changes its hash and is rejected at
startup until its non-actuation behavior is reviewed and the manifest updated.
