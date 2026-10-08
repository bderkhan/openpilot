"""Host-only regression tests; never accesses real hardware or imported device extensions."""
import ast
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import bkv_bench as bench

ROOT = Path(__file__).resolve().parent
PACKAGE = "iqpilot" if (ROOT / "iqpilot").exists() else (
  "openpilot" if (ROOT / "openpilot/system/manager").exists() and not (ROOT / "openpilot/system").is_symlink() else ""
)
SYSTEM = ROOT / PACKAGE / "system"
PANDA = ROOT / ("artifacts/package_runtime/panda/python/__init__.py" if PACKAGE == "iqpilot" else "panda/python/__init__.py")


def definitions(path, selected, namespace, classes=False):
  tree = ast.parse(path.read_text())
  nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
  candidates = [n for c in tree.body if isinstance(c, ast.ClassDef) for n in c.body] if classes else tree.body
  nodes += [n for n in candidates if isinstance(n, ast.FunctionDef) and n.name in selected]
  module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
  exec(compile(module, str(path), "exec"), namespace)
  return namespace


class BenchTests(unittest.TestCase):
  def test_acknowledgment_is_explicit(self):
    for value in (None, "", "0", "true", "yes"):
      with self.subTest(value=value), self.assertRaises(RuntimeError):
        bench.require_acknowledgment({bench.ACK_ENV: value})
    bench.require_acknowledgment({bench.ACK_ENV: "1"})

  def test_unknown_processes_fail_closed(self):
    processes = [SimpleNamespace(name=name, enabled=True, should_run=lambda *a: True)
                 for name in ("pandad", "_pandad", "card", "controlsd", "selfdrived", "joystickd",
                              "dmonitoringd", "dmonitoringmodeld", "updated", "future_vehicle_writer")]
    bench.restrict_processes(processes)
    for process in processes:
      with self.subTest(name=process.name):
        self.assertFalse(process.enabled)
        self.assertFalse(process.should_run(True, None, None))
        self.assertFalse(process.should_run(False, None, None))
        with self.assertRaises(RuntimeError):
          bench.require_process(process.name)

  def test_perception_preserves_upstream_enable_flags(self):
    camera = SimpleNamespace(name="camerad", enabled=True)
    model = SimpleNamespace(name="modeld", enabled=False)
    bench.restrict_processes([camera, model])
    self.assertTrue(camera.enabled)
    self.assertFalse(model.enabled)
    bench.require_process(camera.name)

  def test_real_process_configuration_is_confined(self):
    class Process:
      def __init__(self, *args, **kwargs):
        self.name = args[0]
        self.enabled = kwargs.get("enabled", args[4] if len(args) > 4 else True)
        self.should_run = args[3] if len(args) > 3 else lambda *a: True

    tree = ast.parse((SYSTEM / "manager/process_config.py").read_text())
    nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    nodes += [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    paths = SimpleNamespace(mapd_root=lambda: "/tmp/mapd")
    namespace = dict(os=SimpleNamespace(getenv=lambda *a: None, path=SimpleNamespace(exists=lambda *a: False)),
                     platform=platform, Paths=paths, MAPD_PATH="/tmp/mapd", PC=False, TICI=True,
                     COMMA_HARDWARE=True, NativeProcess=Process, PythonProcess=Process,
                     DaemonProcess=Process, BundleProcess=Process, restrict_processes=bench.restrict_processes)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "process_config", "exec"), namespace)
    actual = namespace["managed_processes"]
    for name in ("pandad", "_pandad", "card", "controlsd", "selfdrived", "dmonitoringmodeld", "dmonitoringd", "updated"):
      with self.subTest(name=name):
        self.assertFalse(actual[name].enabled)
        self.assertFalse(actual[name].should_run(True, None, None))
    self.assertTrue(actual["camerad"].enabled)
    self.assertTrue(actual["ui"].enabled)
    for process in actual.values():
      if process.enabled:
        self.assertIn(process.name, bench.ALLOWED_PROCESSES)

  def test_concrete_start_methods_cannot_bypass_policy(self):
    tree = ast.parse((SYSTEM / "manager/process.py").read_text())
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name != "ManagerProcess"]:
      for method in [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "start"]:
        with self.subTest(cls=cls.name):
          namespace = {"require_process": bench.require_process}
          exec(compile(ast.fix_missing_locations(ast.Module(body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), method
          ], type_ignores=[])), "process.start", "exec"), namespace)
          with self.assertRaisesRegex(RuntimeError, "refuses process"):
            namespace["start"](SimpleNamespace(name="pandad"))

  def test_child_launchers_block_before_import_or_exec(self):
    namespace = definitions(SYSTEM / "manager/process.py", {"launcher", "nativelauncher"},
                            {"require_process": bench.require_process})
    with self.assertRaises(RuntimeError):
      namespace["launcher"]("anything", "card")
    with self.assertRaises(RuntimeError):
      namespace["nativelauncher"](["./pandad"], "/tmp", "_pandad")

  def panda_methods(self):
    namespace = definitions(PANDA, {"can_send", "can_send_many", "set_safety_mode",
                                   "set_can_enable", "set_ir_power", "send_heartbeat"},
                            {"CarParams": SimpleNamespace(SafetyModel=SimpleNamespace(silent=0)),
                             "CAN_SEND_TIMEOUT_MS": 10, "ensure_can_packet_version": lambda fn: fn}, classes=True)
    methods = {name: value for name, value in namespace.items() if callable(value) and name != "ensure_can_packet_version"}
    cls = type("Panda", (), dict(methods, REQUEST_OUT=0))
    namespace["Panda"] = cls
    panda = cls()
    panda._handle = Mock()
    return panda

  def test_can_transmission_never_reaches_hardware(self):
    panda = self.panda_methods()
    for fd in (False, True):
      with self.subTest(fd=fd), self.assertRaises(RuntimeError):
        panda.can_send(0x123, b"abc", 0, fd=fd)
      with self.subTest(fd=fd), self.assertRaises(RuntimeError):
        panda.can_send_many([[0x123, b"abc", 0]], fd=fd, timeout=0)
    with self.assertRaises(RuntimeError):
      panda.can_send_many([])
    panda._handle.bulkWrite.assert_not_called()
    panda._handle.controlWrite.assert_not_called()

  def test_only_silent_safety_and_disabled_transceivers(self):
    panda = self.panda_methods()
    for mode, param in ((1, 0), (2, 0), (17, 0), (0, 1)):
      with self.subTest(mode=mode, param=param), self.assertRaises(RuntimeError):
        panda.set_safety_mode(mode, param)
    with self.assertRaises(RuntimeError):
      panda.set_can_enable(0, True)
    panda._handle.controlWrite.assert_not_called()
    panda.set_safety_mode()
    panda.set_can_enable(0, False)
    self.assertEqual(panda._handle.controlWrite.call_args_list[0].args[1:4], (0xdc, 0, 0))
    self.assertEqual(panda._handle.controlWrite.call_args_list[1].args[1:4], (0xf4, 0, 0))

  def test_engaged_heartbeat_is_rejected(self):
    panda = self.panda_methods()
    with self.assertRaises(RuntimeError):
      panda.send_heartbeat()
    keys = [name for name in __import__("inspect").signature(panda.send_heartbeat).parameters]
    panda.send_heartbeat(**{name: False for name in keys})
    self.assertEqual(panda._handle.controlWrite.call_args.args[1:4], (0xf3, False, False))

  def test_stock_panda_ir_is_always_zero(self):
    panda = self.panda_methods()
    for power in (-1, 0, 50, 100, 65535):
      panda.set_ir_power(power)
      self.assertEqual(panda._handle.controlWrite.call_args.args[1:4], (0xb0, 0, 0))

  def fake_pandas(self, health=None, bootstub=False):
    panda = Mock()
    panda.bootstub = bootstub
    panda.get_type.return_value = b"cuatro"
    panda.health.return_value = health or dict(safety_mode=0, controls_allowed=False)
    panda.__enter__ = Mock(return_value=panda)
    panda.__exit__ = Mock(return_value=False)
    cls = Mock(return_value=panda)
    cls.list.return_value = ["test-board"]
    cls.HW_TYPE_CUATRO = b"cuatro"
    return cls, panda

  def test_hardware_quieting_turns_off_output_and_preserves_cooling(self):
    cls, panda = self.fake_pandas()
    self.assertTrue(bench.quiet_pandas(cls))
    cls.assert_called_once_with("test-board", cli=False, disable_checks=False)
    panda.set_safety_mode.assert_called_once_with()
    self.assertEqual([c.args for c in panda.set_can_enable.call_args_list], [(0, False), (1, False), (2, False)])
    panda.set_ir_power.assert_called_once_with(0)
    panda.set_fan_power.assert_called_once_with(100)

  def test_hardware_errors_stop_startup(self):
    for health in (dict(safety_mode=1, controls_allowed=False), dict(safety_mode=0, controls_allowed=True)):
      cls, _ = self.fake_pandas(health=health)
      with self.subTest(health=health), self.assertRaises(RuntimeError):
        bench.quiet_pandas(cls)
    cls, _ = self.fake_pandas(bootstub=True)
    with self.assertRaises(RuntimeError):
      bench.quiet_pandas(cls)
    cls.list.return_value = []
    with self.assertRaises(RuntimeError):
      bench.quiet_pandas(cls)

  def test_existing_vehicle_service_prevents_startup(self):
    with tempfile.TemporaryDirectory() as temp:
      root = Path(temp)
      pid = root / str(os.getpid() + 1000)
      pid.mkdir()
      command = pid / "cmdline"
      command.write_bytes(b"/data/openpilot/selfdrive/pandad/pandad\0")
      with self.assertRaises(RuntimeError):
        bench.require_no_vehicle_services(root)
      command.write_bytes(b"openpilot.selfdrive.car.card\0")
      with self.assertRaises(RuntimeError):
        bench.require_no_vehicle_services(root)
      command.write_bytes(b"openpilot.selfdrive.ui.ui\0")
      bench.require_no_vehicle_services(root)

  def test_led_write_failure_or_bad_readback_prevents_startup(self):
    with tempfile.TemporaryDirectory() as temp:
      root = Path(temp)
      for name in ("led:switch_2", "led:torch_2"):
        (root / name).mkdir()
        (root / name / "brightness").write_text("50\n")
      with patch.object(Path, "write_text", side_effect=PermissionError("LED write refused")):
        with self.assertRaises(PermissionError):
          bench.reset_direct_leds(root, required=True)
      with patch.object(Path, "write_text", return_value=2):
        with self.assertRaises(RuntimeError):
          bench.reset_direct_leds(root, required=True)

  def test_changed_native_binary_prevents_startup(self):
    with patch.dict(os.environ, {bench.ACK_ENV: "1"}), patch.dict("sys.modules", {"panda": SimpleNamespace(Panda=Mock())}):
      with patch.object(bench, "require_no_vehicle_services"), patch.object(bench.hashlib, "sha256") as sha:
        sha.return_value.hexdigest.return_value = "unexpected"
        with patch.object(bench, "quiet_pandas") as quiet, self.assertRaisesRegex(RuntimeError, "executable changed"):
          bench.initialize_bench()
        quiet.assert_not_called()

  def test_wrong_panda_package_prevents_startup(self):
    with patch.dict(os.environ, {bench.ACK_ENV: "1"}), patch.dict("sys.modules", {"panda": SimpleNamespace(Panda=Mock())}):
      with patch.object(bench, "require_no_vehicle_services"), patch.object(bench.inspect, "getfile", return_value="/tmp/other/panda.py"):
        with patch.object(bench, "quiet_pandas") as quiet, self.assertRaisesRegex(RuntimeError, "confined Panda API"):
          bench.initialize_bench()
        quiet.assert_not_called()

  def test_stock_host_ir_does_not_overwrite_replacement(self):
    if PACKAGE == "":
      self.skipTest("C3 has no Python host IR setter; its hardware path is Panda")
    hardware = ROOT / PACKAGE / ("common/hardware/comma/hardware.py" if PACKAGE == "openpilot" else "system/hardware/tici/hardware.py")
    namespace = definitions(hardware, {"set_ir_power"}, {}, classes=True)
    with patch("builtins.open", side_effect=AssertionError("Stock IR wrote hardware")):
      namespace["set_ir_power"](Mock(), 100)

  def test_bench_dm_tutorial_does_not_wait_for_stock_faces(self):
    if PACKAGE == "":
      self.skipTest("C3 uses the Qt interface, not the MICI tutorial")
    path = ROOT / PACKAGE / "selfdrive/ui/mici/layouts/onboarding.py"
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TrainingGuideDMTutorial")
    cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_update_state"]
    cls.bases = [ast.Name(id="Base", ctx=ast.Load())]
    namespace = dict(BENCH_ONLY=True, Base=type("Base", (), {"_update_state": lambda self: None}))
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), cls], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    widget = namespace["TrainingGuideDMTutorial"]()
    widget._good_button = Mock()
    widget._update_state()
    widget._good_button.set_enabled.assert_called_once_with(True)

  def test_led_reset_is_once_and_missing_c4_controls_fail_closed(self):
    with tempfile.TemporaryDirectory() as temp:
      root = Path(temp)
      with self.assertRaises(RuntimeError):
        bench.reset_direct_leds(root, required=True)
      bench.reset_direct_leds(root)
      for name in ("led:switch_2", "led:torch_2"):
        (root / name).mkdir()
        (root / name / "brightness").write_text("300\n")
      bench.reset_direct_leds(root, required=True)
      for path in root.glob("*/brightness"):
        self.assertEqual(path.read_text(), "0\n")

  def test_manager_and_panda_wrapper_fail_before_side_effects(self):
    namespace = definitions(SYSTEM / "manager/manager.py", {"manager_init"}, {})
    with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(RuntimeError, "Bench only"):
      namespace["manager_init"]()
    wrapper = ROOT / PACKAGE / "selfdrive/pandad/pandad.py"
    namespace = definitions(wrapper, {"main"}, {})
    with self.assertRaisesRegex(RuntimeError, "refuses process"):
      namespace["main"]()

  def test_launcher_refuses_unacknowledged_boot(self):
    env = dict(os.environ)
    env.pop(bench.ACK_ENV, None)
    result = subprocess.run(["bash", str(ROOT / "launch_chffrplus.sh")], env=env, capture_output=True, text=True)
    self.assertEqual(result.returncode, 78)
    self.assertIn("BENCH ONLY", result.stderr)

  def test_native_bridge_is_confined_and_matches_manifest(self):
    manifest = json.loads((ROOT / "BKV_BENCH_NATIVE.json").read_text())
    binary = (ROOT / manifest["binary"]).read_bytes()
    self.assertEqual(hashlib.sha256(binary).hexdigest(), manifest["bench_sha256"])
    self.assertEqual(struct.unpack_from("<Q", binary, 24)[0], manifest["entry_address"])
    offset = manifest["main_file_offset"]
    self.assertEqual(binary[offset:offset+12].hex(), manifest["exit_instructions"])
    self.assertEqual(manifest["verified_exit_status"], 78)

  def test_seatbelt_does_not_emit_event_but_other_events_remain(self):
    path = ROOT / PACKAGE / "selfdrive/car" / ("car_events.py" if PACKAGE == "openpilot" else "car_specific.py")
    class Events(list):
      def add(self, event):
        self.append(event)
    class Names:
      def __getattr__(self, name):
        return name
    namespace = definitions(path, {"create_common_events"},
                            {"Events": Events, "EventName": Names(), "GearShifter": Names(),
                             "MAX_CTRL_SPEED": 100, "DT_CTRL": 0.01,
                             "interfaces": {"test": SimpleNamespace(DRIVABLE_GEARS=())}}, classes=True)
    method = namespace["create_common_events"]
    attributes = {n.attr for n in ast.walk(ast.parse(path.read_text()))
                  if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in ("CS", "CS_prev")}
    state = SimpleNamespace(**{name: False for name in attributes})
    state.gearShifter = "drive"
    state.buttonEvents = []
    state.vEgo = 0
    state.cruiseState = SimpleNamespace(available=True, enabled=True, nonAdaptive=False)
    state.seatbeltUnlatched = True
    cp = SimpleNamespace(carFingerprint="test", pcmCruise=False, brand="mock", openpilotLongitudinalControl=False)
    owner = SimpleNamespace(CP=cp, steering_unpressed=0, no_steer_warning=False, silent_steer_warning=False)
    args = {"pcm_enable": False} if PACKAGE == "" else {}
    result = method(owner, state, state, **args)
    self.assertNotIn("seatbeltNotLatched", result)
    state.doorOpen = True
    state.steerFaultPermanent = True
    result = method(owner, state, state, **args)
    self.assertIn("doorOpen", result)
    self.assertIn("steerUnavailable", result)


if __name__ == "__main__":
  unittest.main(verbosity=2)
