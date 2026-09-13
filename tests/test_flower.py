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


def _api_server(tmp_path):
    """Start an ApiServer on an ephemeral port; return (base_url, controller, server)."""
    import threading
    from flower.server import ApiServer

    cfg = Config.default()
    cfg.data_dir = Path(tmp_path)
    cfg.timed_actions = [TimedActionConfig(key="water", relay="water_pump", duration_s=60)]
    ctrl = Controller(cfg)
    srv = ApiServer(ctrl, "127.0.0.1", 0, token="secret")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}", ctrl, srv


def _request(req):
    """Return (status, json-body), including for 4xx/5xx (urllib raises those)."""
    import json as _json
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, _json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, _json.load(e)


def _get(url, token="secret"):
    import urllib.request
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return _request(urllib.request.Request(url, headers=headers))


def _post(url, body, token="secret"):
    import json as _json
    import urllib.request
    data = _json.dumps(body).encode()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    return _request(urllib.request.Request(url, data=data, headers=headers, method="POST"))


def test_api_requires_token(tmp_path):
    import urllib.error
    import urllib.request
    base, _ctrl, srv = _api_server(tmp_path)
    try:
        try:
            urllib.request.urlopen(base + "/api/status")   # no Authorization header
            assert False, "expected 401"
        except urllib.error.HTTPError as e:
            assert e.code == 401
    finally:
        srv.shutdown()


def test_api_status_and_relay_and_command(tmp_path):
    base, ctrl, srv = _api_server(tmp_path)
    try:
        status, data = _get(base + "/api/status")
        assert status == 200
        assert "plug" in data["relays"] and data["relays"]["plug"] is False

        # direct relay hold
        status, res = _post(base + "/api/relay/plug", {"on": True})
        assert status == 200 and res["ok"] and res["on"] is True
        assert ctrl.settings.get("plug") is True
        assert ctrl.snapshot()["relays"]["plug"] is True

        # unknown relay -> 404 body
        _status, res = _post(base + "/api/relay/nope", {"on": True})
        assert "error" in res

        # one-shot command pulses the timed pump
        status, res = _post(base + "/api/command/water", {})
        assert status == 200 and res["ok"]
        assert ctrl.snapshot()["relays"]["water_pump"] is True   # energised by timed action

        # timeseries endpoint
        status, ts = _get(base + "/api/timeseries/moisture")
        assert status == 200 and "0" in ts and isinstance(ts["0"], list)
    finally:
        srv.shutdown()


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
