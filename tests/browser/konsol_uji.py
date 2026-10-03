"""Starts the copied console on `--port`, with its three lines on `--port-line`.

Line ports are hard-wired to 8001-8003 in `_CONSOLE_LINE_DEFAULTS`, and a developer's
lines may hold those. `Settings.console_lines` reads that table at call time, so it is
rewritten here BEFORE `console_main` is imported (its module body builds the app).
"""

from __future__ import annotations

import argparse

import uvicorn

import palmgrade.core.config as config


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--port-line", required=True, help="three ports, comma separated")
    args = ap.parse_args()
    ports = [int(p) for p in args.port_line.split(",")]
    config._CONSOLE_LINE_DEFAULTS = tuple(
        (kode, nama, port, machine_id)
        for (kode, nama, _lama, machine_id), port in zip(config._CONSOLE_LINE_DEFAULTS, ports, strict=True)
    )
    uvicorn.run("palmgrade.console_main:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
