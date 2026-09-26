#!/usr/bin/env python3
"""Manual relay wiring check — walk every channel on for 1 s, then off, one by one.

This is a **hardware utility, not a pytest test** (hence the ``relay_``, not
``test_``, filename — pytest will not collect it, so it can never energise your
relays during a normal test run). Run it by hand on the Pi when you want to
confirm the GPIO -> relay wiring:

    python tests/relay_wiring_check.py            # walk the verified 16-ch map
    python tests/relay_wiring_check.py --on-time 2 --gap 1
    python tests/relay_wiring_check.py --board ssr
    python tests/relay_wiring_check.py --config /path/to/flower.yaml   # test your config's relays
    python tests/relay_wiring_check.py --yes      # skip the confirm prompt

For each channel it energises exactly one relay (announcing board / position /
BCM / physical pin), waits ``--on-time`` seconds so you can see the click + LED,
de-energises it, pauses ``--gap``, then moves on. Only one coil is ever on at a
time (keeps the Pi 5 V rail current low). Every exit path — normal end, Ctrl-C,
or error — runs ``all_off()`` so nothing is left latched.

On a machine without ``gpiozero`` (or with unassigned pins) each channel degrades
to a logged dry-run, so the sequence itself can be checked off-hardware.

Verified 2026-09-26 by camera-actuation sweep. The order below is the physical
LED-row order on each board; the CH1<->CH8 direction is whatever the board silk
says — watch which relay lights to map position -> channel number.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Run straight from the repo without installing: fall back to ../src on the path.
try:
    from flower import Config, RelayConfig, RelayBank
except ImportError:  # pragma: no cover - convenience for in-repo execution
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from flower import Config, RelayConfig, RelayBank

# -- verified GPIO -> relay map (BCM), in physical LED-row order per board -----
# Solid-state board ("8 Solid State Relay / Low Level Trigger"):
SSR_BCM = [24, 23, 22, 27, 17, 18, 15, 14]
# Mechanical board (blue SONGLE SRD-05VDC-SL-C, opto-isolated):
MECH_BCM = [10, 9, 11, 25, 8, 7, 1, 0]
# BCM -> physical header pin, for the announcement only (janK wires by phys pin).
BCM_TO_PHYS = {
    24: 18, 23: 16, 22: 15, 27: 13, 17: 11, 18: 12, 15: 10, 14: 8,
    10: 19, 9: 21, 11: 23, 25: 22, 8: 24, 7: 26, 1: 28, 0: 27,
}


def verified_relays(board: str) -> list[RelayConfig]:
    """Build the RelayConfig list for the verified wiring (all active-low)."""
    banks = {"ssr": SSR_BCM, "mech": MECH_BCM}
    if board != "all":
        banks = {board: banks[board]}
    cfgs: list[RelayConfig] = []
    for name, bcms in banks.items():
        for pos, bcm in enumerate(bcms, start=1):
            cfgs.append(RelayConfig(
                name=f"{name}{pos}",
                pin=bcm,
                active_low=True,
                description=f"{name.upper()} board pos{pos} (BCM{bcm}, phys{BCM_TO_PHYS[bcm]})",
            ))
    return cfgs


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--on-time", type=float, default=1.0,
                   help="seconds each relay stays energised (default 1.0)")
    p.add_argument("--gap", type=float, default=0.5,
                   help="seconds between channels, all off (default 0.5)")
    p.add_argument("--board", choices=("all", "ssr", "mech"), default="all",
                   help="which board(s) to walk (built-in map only; default all)")
    p.add_argument("--config", type=str, default=None,
                   help="test the relays from a flower YAML config instead of the built-in map")
    p.add_argument("--yes", "-y", action="store_true",
                   help="skip the confirmation prompt")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.config:
        relays = Config.load(args.config).relays
        source = f"config {args.config}"
    else:
        relays = verified_relays(args.board)
        source = f"built-in verified map (board={args.board})"

    if not relays:
        print("no relays to test", file=sys.stderr)
        return 1

    wired = sum(r.pin is not None for r in relays)
    print(f"Relay wiring check — {source}")
    print(f"  {len(relays)} channels ({wired} wired, {len(relays) - wired} dry-run), "
          f"on-time={args.on_time}s, gap={args.gap}s\n")

    if not args.yes:
        try:
            input("About to energise each relay in turn (one at a time). "
                  "Press Enter to start, Ctrl-C to abort... ")
        except (KeyboardInterrupt, EOFError):
            print("\naborted.")
            return 130

    bank = RelayBank.from_config(relays)
    n = len(relays)
    try:
        bank.all_off()  # known-safe starting point
        for i, relay in enumerate(bank, start=1):
            desc = f" — {relay.description}" if relay.description else ""
            print(f"[{i:2d}/{n}] {relay.name:<8} pin={relay.pin}{desc}  -> ON")
            relay.on()
            time.sleep(args.on_time)
            relay.off()
            print(f"          {relay.name:<8} -> off")
            if i < n:
                time.sleep(args.gap)
    except KeyboardInterrupt:
        print("\ninterrupted — switching everything off.")
        return 130
    finally:
        bank.all_off()
        bank.close()

    print("\ndone — all relays off.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
