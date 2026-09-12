# flower

A small, hardware-agnostic controller for a Raspberry Pi plant rig — watering,
lighting, and environmental sensing. Refactored from the `PLANT_SOURCE`
prototype scripts into composable, testable classes.

## Why this rewrite

The prototype worked but was a set of scripts with copy-pasted loops, hard-coded
`/home/jank/python` paths, hard-coded GPIO pins, inverted-relay foot-guns, and a
`while True:` doing everything. `flower` keeps the *ideas* and drops the sharp
edges:

| Prototype | flower |
|---|---|
| `LED('GPIO4', initial_value=True)`, `.off()` = on | `Relay.on()` = load on; polarity hidden by `active_low` |
| pins hard-coded in every script | pins in config, **default `None` (unassigned)** |
| `heat_on.py`, `water_on.py`, ... (a dozen scripts) | `flower set heat true` → one settings file |
| copy-pasted moisture/rht/room load+trim+`dumpfn` | `TimeSeriesStore` (rolling window, **atomic** write + backup) |
| repeated "start / stop after N s" valve blocks | `TimedAction` |
| `manage-flower.py` 280-line loop | `Controller.step()` |

## Install

```bash
pip install -e .                 # core (dev machine, dry-run)
pip install -e '.[hardware]'     # on the Pi: gpiozero+lgpio, pyserial, bme280pi
pip install -e '.[dev]' && pytest
```

Everything imports and runs **without hardware**: unassigned pins and absent
libraries degrade to a logged dry-run, so you can develop and test off the Pi.

## Use

```bash
flower init-config config.yaml   # writes a default config (all pins unassigned)
flower relays --config config.yaml
flower status --config config.yaml   # one sense/actuate cycle, printed
flower run    --config config.yaml   # the loop
flower set water true            # drop a one-shot command (runs the pump timed)
flower get                       # inspect the command/settings file
```

## Configuration

A YAML file describes the rig. **GPIO pins are left unassigned until hardware is
wired** — so the default config runs the whole controller in simulation. Wire a
relay, set its `pin`, done. Example:

```yaml
data_dir: data
retention_days: 7
sample_interval_s: 10
auto_heat_below_c: 22        # engage 'heat' below 22 C; null disables
bme280: { enabled: true, address: 0x76 }
arduino: { port: null, baud: 9600, n_moisture: 5 }   # port null = not connected
relays:
  - { name: heat,          pin: null, active_low: true }
  - { name: water_pump,    pin: null, active_low: true }
  - { name: fill_valve,    pin: null, active_low: true }
  # ... plug, pc_power, steppers, fan
timed_actions:
  - { key: water, relay: water_pump,   duration_s: 75 }   # pump runs 75 s
  - { key: fill,  relay: fill_valve,   duration_s: 600 }
```

## Architecture

```
Controller.step():
  BME280Sensor.read()      -> room.json     (air T / RH / pressure)
  ArduinoSensorHub.read()  -> moisture.json + rht.json   (5 moisture + RHT)
  read_cpu_temperature()   -> rht.json[cpu]
  SettingsStore            -> flags/commands in, consumed here
  RelayBank                <- direct flags, auto-heat, timed actions
```

Sensor firmware lives in `firmware/flower_sensors.ino` (Mega/Nano: analog
moisture + BME280 → serial line); `firmware/i2c_scanner.ino` is a bus-scan helper.

## Status / scope

v0.1 covers the control core (sensors, relays, stores, controller, CLI). Camera
capture/stream, the MongoDB (`mongo.numphys.org`) logging, and the numphys
settings-sync from the prototype are **not** ported yet — parked until the core
loop is running on real hardware (see `manager/README.md` phases). Pins stay
unassigned until we wire the bank.
