"""Command-line interface: ``flower <command>``.

Replaces the scatter of one-shot scripts (``heat_on.py``, ``water_on.py``, ...)
with a single tool that talks to the same settings file the controller reads.

    flower init-config config.yaml     # write a default (all-pins-unassigned) config
    flower run    [--config c.yaml]     # start the sense/actuate loop
    flower status [--config c.yaml]     # one read + what it would actuate
    flower relays [--config c.yaml]     # list channels and their (unassigned) pins
    flower set heat true                # drop a command flag (was heat_on.py)
    flower get [key]                    # read the settings/command file
"""

from __future__ import annotations

import argparse
import json
import logging

from . import __version__
from .config import Config
from .controller import Controller
from .store.settings import SettingsStore


def _load_config(args) -> Config:
    return Config.load(args.config) if getattr(args, "config", None) else Config.default()


def _coerce(text: str):
    low = text.lower()
    if low in ("true", "false"):
        return low == "true"
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return text


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="flower", description=__doc__.splitlines()[0])
    p.add_argument("--config", help="path to a config YAML (default: built-in defaults)")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    p.add_argument("--version", action="version", version=f"flower {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("run", help="start the controller loop")
    sub.add_parser("status", help="one sense/actuate step, print a snapshot")
    sub.add_parser("relays", help="list configured relay channels")

    p_serve = sub.add_parser("serve", help="run the controller loop + HTTP control API")
    p_serve.add_argument("--host", help="bind address (default from config)")
    p_serve.add_argument("--port", type=int, help="bind port (default from config)")
    p_serve.add_argument("--token", help="API bearer token (else FLOWER_API_TOKEN, else generated)")

    p_init = sub.add_parser("init-config", help="write a default config file")
    p_init.add_argument("path", help="output YAML path")

    p_set = sub.add_parser("set", help="set a settings/command flag")
    p_set.add_argument("key")
    p_set.add_argument("value")

    p_get = sub.add_parser("get", help="read the settings file")
    p_get.add_argument("key", nargs="?")

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    if args.cmd == "init-config":
        Config.default().save(args.path)
        print(f"wrote default config to {args.path} (all GPIO pins unassigned)")
        return 0

    cfg = _load_config(args)

    if args.cmd == "run":
        Controller(cfg).run()
        return 0

    if args.cmd == "serve":
        import os
        import secrets
        import threading
        from .server import serve

        host = args.host or cfg.api.host
        port = args.port or cfg.api.port
        token = args.token or os.environ.get("FLOWER_API_TOKEN") or cfg.api.token
        if not token:
            token = secrets.token_urlsafe(18)
            print(f"No API token configured — generated one for this run:\n  {token}\n"
                  "  (put it in config `api.token` or FLOWER_API_TOKEN to keep it stable,\n"
                  "   and paste it into the admin_flower app)")
        controller = Controller(cfg)
        threading.Thread(target=controller.run, daemon=True).start()
        print(f"flower serving on http://{host}:{port}  (Ctrl+C to stop)")
        try:
            serve(controller, host, port, token)
        except KeyboardInterrupt:
            pass
        finally:
            controller.stop()
            controller.shutdown()
        return 0

    if args.cmd == "status":
        print(json.dumps(Controller(cfg).step(), indent=2, default=str))
        return 0

    if args.cmd == "relays":
        for r in cfg.relays:
            pin = r.pin if r.pin is not None else "unassigned"
            print(f"  {r.name:14s} pin={pin!s:>10}  active_low={r.active_low}  {r.description}")
        return 0

    store = SettingsStore(cfg.data_dir / "settings.json")
    if args.cmd == "set":
        store.set(args.key, _coerce(args.value))
        print(f"{args.key} = {store.get(args.key)!r}")
        return 0

    if args.cmd == "get":
        data = store.load()
        print(json.dumps(data.get(args.key) if args.key else data, indent=2))
        return 0

    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
