from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
from typing import Any


def _require_macos() -> None:
    if platform.system() != "Darwin":
        raise RuntimeError("wake_mac_display only supports macOS.")


def _require_command(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required command not found: {name}")


def _run_command(cmd: list[str]) -> dict[str, Any]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "cmd": cmd,
    }


def _start_hold_command(cmd: list[str], startup_delay: float = 0.2) -> dict[str, Any]:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(startup_delay)

    returncode = proc.poll()
    if returncode is None:
        return {
            "ok": True,
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "cmd": cmd,
            "pid": proc.pid,
        }

    stdout, stderr = proc.communicate()
    return {
        "ok": returncode == 0,
        "returncode": returncode,
        "stdout": stdout.strip(),
        "stderr": stderr.strip(),
        "cmd": cmd,
        "pid": proc.pid,
    }


def wake_mac_display(hold_seconds: int = 3600, activate_finder: bool = True) -> dict[str, Any]:
    """
    Try to wake a macOS display from the command line and keep it awake briefly.

    Behavior:
    1. Sends a short `caffeinate -u` user-activity pulse.
    2. Optionally activates Finder so the GUI session becomes frontmost.
    3. Starts `caffeinate -d -u -t N` in the background to keep the display awake.

    Notes:
    - Success means the wake request was submitted to macOS.
    - It does not guarantee the panel will light up if the issue is brightness,
      lid state, external monitor state, or a deeper graphics/session problem.

    Args:
        hold_seconds: Number of seconds to prevent display idle sleep.
        activate_finder: Whether to bring Finder to the front.

    Returns:
        A dictionary containing per-step command results plus an overall `ok` flag.
    """
    if hold_seconds <= 0:
        raise ValueError("hold_seconds must be greater than 0.")

    _require_macos()
    _require_command("caffeinate")
    if activate_finder:
        _require_command("osascript")

    results: dict[str, Any] = {
        "user_activity": _run_command(["caffeinate", "-u", "-t", "2"]),
        "finder_activate": None,
        "display_hold": None,
    }

    if activate_finder:
        results["finder_activate"] = _run_command(
            ["osascript", "-e", 'tell application "Finder" to activate']
        )

    results["display_hold"] = _start_hold_command(
        ["caffeinate", "-d", "-u", "-t", str(hold_seconds)]
    )

    results["ok"] = all(
        step is None or step["ok"]
        for step in (
            results["user_activity"],
            results["finder_activate"],
            results["display_hold"],
        )
    )
    return results


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyautogui-mcp-wake",
        description="Attempt to wake a macOS display from the command line."
    )
    parser.add_argument(
        "--hold-seconds",
        type=int,
        default=3600,
        help="Seconds to keep the display from idling again. Default: 3600.",
    )
    parser.add_argument(
        "--no-activate-finder",
        action="store_true",
        help="Skip bringing Finder to the front.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    try:
        result = wake_mac_display(
            hold_seconds=args.hold_seconds,
            activate_finder=not args.no_activate_finder,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
