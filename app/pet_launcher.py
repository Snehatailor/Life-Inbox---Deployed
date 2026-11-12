"""Start and stop the desktop pet (desktop-pet/, an Electron app).

The pet is a window on the screen of the computer that runs the server, so it
only makes sense when Life Inbox runs on your own computer. It needs
`npm install` in desktop-pet/ once; without that, everything here is a no-op.

On/off is remembered in data/desktop_pet.json. The server starts the pet at
startup only when it is switched on (the default) and installed.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PET_DIR = Path(__file__).resolve().parent.parent / "desktop-pet"
PREFERENCE_FILE = Path(__file__).resolve().parent.parent / "data" / "desktop_pet.json"

_process: Optional[subprocess.Popen] = None
_lock = threading.Lock()


def electron_binary(pet_dir: Path = PET_DIR) -> Path | None:
    if sys.platform == "win32":
        # .bin/electron is a Unix shell script, which Windows cannot run.
        candidate = pet_dir / "node_modules" / "electron" / "dist" / "electron.exe"
    else:
        candidate = pet_dir / "node_modules" / ".bin" / "electron"
    return candidate if candidate.exists() else None


def _env_allows_launch() -> bool:
    return os.environ.get("LIFE_INBOX_LAUNCH_PET", "true").lower() not in {"0", "false", "no"}


def pet_enabled(preference_file: Optional[Path] = None) -> bool:
    """The saved on/off switch. On unless someone turned it off."""
    preference_file = preference_file or PREFERENCE_FILE
    try:
        return bool(json.loads(preference_file.read_text(encoding="utf-8")).get("enabled", True))
    except (OSError, ValueError, AttributeError):
        return True


def save_pet_enabled(enabled: bool, preference_file: Optional[Path] = None) -> None:
    preference_file = preference_file or PREFERENCE_FILE
    preference_file.parent.mkdir(parents=True, exist_ok=True)
    preference_file.write_text(json.dumps({"enabled": bool(enabled)}), encoding="utf-8")


def pet_running() -> bool:
    return _process is not None and _process.poll() is None


def _start(port: int, pet_dir: Path) -> bool:
    global _process
    binary = electron_binary(pet_dir)
    if binary is None:
        logger.warning("Desktop pet not installed (run `npm install` in desktop-pet).")
        return False
    if pet_running():
        return True
    env = {**os.environ, "LIFE_INBOX_URL": os.environ.get("LIFE_INBOX_URL", f"http://127.0.0.1:{port}")}
    try:
        _process = subprocess.Popen(
            [str(binary), "."], cwd=pet_dir, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=sys.platform != "win32",
        )
    except OSError:
        logger.warning("Could not start the desktop pet.", exc_info=True)
        _process = None
        return False
    return True


def launch_pet(port: int = 8000, pet_dir: Path = PET_DIR) -> bool:
    """Startup hook: start the pet if it is installed and switched on."""
    if not _env_allows_launch():
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    if not pet_enabled():
        return False
    with _lock:
        return _start(port, pet_dir)


def start_pet(port: int = 8000, pet_dir: Path = PET_DIR) -> bool:
    """Switch the pet on now (the button)."""
    with _lock:
        return _start(port, pet_dir)


def stop_pet() -> bool:
    """Switch the pet off now. Returns True if a running pet was stopped."""
    global _process
    with _lock:
        if not pet_running():
            _process = None
            return False
        process = _process
        _process = None
    try:
        process.terminate()
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    except OSError:
        pass
    return True


def pet_status(pet_dir: Path = PET_DIR) -> dict:
    return {
        "installed": electron_binary(pet_dir) is not None,
        "enabled": pet_enabled(),
        "running": pet_running(),
    }
