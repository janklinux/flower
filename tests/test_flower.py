"""Tests that run with no hardware present (dry-run mode)."""

from pathlib import Path

from flower import (
    ArduinoSensorHub,
    Config,
    Controller,
    Relay,
    RelayBank,
    SettingsStore,
    TimeSeriesStore,
)
from flower.config import RelayConfig, TimedActionConfig


def test_default_config_has_no_pins_assigned():
    """The whole point during bring-up: nothing is wired, so no pin is set."""
    cfg = Config.default()
    assert cfg.relays, "expected the 8 named relay channels"
    assert all(r.pin is None for r in cfg.relays)
    assert cfg.arduino.port is None


def test_config_roundtrip(tmp_path):
    cfg = Config.default()
    cfg.relays[0].pin = 4
    cfg.arduino.port = "/dev/serial/by-id/example"
    path = tmp_path / "c.yaml"
    cfg.save(path)
    back = Config.load(path)
    assert back.relays[0].pin == 4
    assert back.arduino.port == "/dev/serial/by-id/example"


def test_relay_dry_run_tracks_state_without_gpio():
    r = Relay("water_pump", pin=None)          # unassigned -> dry run
    assert r.is_on is False
    r.on()
    assert r.is_on is True
    r.off()
    assert r.is_on is False


def test_relay_bank_all_off():
    bank = RelayBank.from_config([RelayConfig(name="a"), RelayConfig(name="b")])
    bank["a"].on()
    assert bank.state() == {"a": True, "b": False}
    bank.all_off()
    assert bank.state() == {"a": False, "b": False}


def test_arduino_parse_plain_line():
    reading = ArduinoSensorHub.parse("512 480 530 300 0 44.5 21.3 1013.2", n_moisture=5)
    assert reading.moisture == [512, 480, 530, 300, 0]
    assert reading.humidity == 44.5
    assert reading.temperature == 21.3
    assert reading.pressure == 1013.2


def test_arduino_parse_labelled_and_bad_lines():
    labelled = ArduinoSensorHub.parse("data: 1 2 3 4 5 40 20 1000", n_moisture=5)
    assert labelled.moisture == [1, 2, 3, 4, 5]
    assert ArduinoSensorHub.parse("", n_moisture=5) is None
    assert ArduinoSensorHub.parse("1 2 3", n_moisture=5) is None      # too few tokens


def test_timeseries_trim_and_roundtrip(tmp_path):
    store = TimeSeriesStore(tmp_path / "ts.json", ["a"], max_points=3)
    for v in range(5):
        store.append("a", v)
    store.save()
    reloaded = TimeSeriesStore(tmp_path / "ts.json", ["a"], max_points=3)
    assert reloaded.data["a"] == [2, 3, 4]     # trimmed to the last 3
    assert (tmp_path / "ts.json.save").exists()  # backup written


def test_timeseries_recovers_from_corrupt_primary(tmp_path):
    p = tmp_path / "ts.json"
    store = TimeSeriesStore(p, ["a"], max_points=10)
    store.append("a", 42)
    store.save()
    p.write_text("{ this is not json")          # corrupt the primary
    recovered = TimeSeriesStore(p, ["a"], max_points=10)
    assert recovered.data["a"] == [42]          # fell back to .save backup


def test_settings_set_get_reset(tmp_path):
    s = SettingsStore(tmp_path / "s.json", initial={"pcpower": True})
    assert s.get("pcpower") is True
    s.set("heat", True)
    assert s.get("heat") is True
    assert s.pop("heat") is True
    assert s.get("heat") is None
    s.reset_to_initial()
    assert s.load() == {"pcpower": True}


def test_controller_step_dry_run(tmp_path):
    cfg = Config.default()
    cfg.data_dir = Path(tmp_path)
    cfg.auto_heat_below_c = 22.0
    cfg.timed_actions = [TimedActionConfig(key="water", relay="water_pump", duration_s=75)]
    ctrl = Controller(cfg)

    ctrl.settings.set("plug", True)             # direct flag holds a relay
    ctrl.settings.set("water", True)            # one-shot pulses the pump
    snap = ctrl.step()

    assert snap["relays"]["plug"] is True
    assert snap["relays"]["water_pump"] is True  # pump energised by the timed action
    assert ctrl.settings.get("water") is False   # command consumed
    # data files were written
    assert (Path(tmp_path) / "settings.json").exists()
