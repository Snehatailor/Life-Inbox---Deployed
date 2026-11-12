"""Start the desktop pet together with the server, when it is installed."""

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

PET_DIR = Path(__file__).resolve().parent.parent / "desktop-pet"


def electron_binary(pet_dir: Path = PET_DIR) -> Path | None:
    if sys.platform == "win32":
        # .bin/electron is a Unix shell script, which Windows cannot run.
        candidate = pet_dir / "node_modules" / "electron" / "dist" / "electron.exe"
    else:
        candidate = pet_dir / "node_modules" / ".bin" / "electron"
    return candidate if candidate.exists() else None


def launch_pet(port: int = 8000, pet_dir: Path = PET_DIR) -> bool:
    """Start the pet in the background. It keeps one copy running on its own."""
    if os.environ.get("LIFE_INBOX_LAUNCH_PET", "true").lower() in {"0", "false", "no"}:
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    binary = electron_binary(pet_dir)
    if binary is None:
        logger.warning("Desktop pet not installed (run `npm install` in desktop-pet).")
        return False
    env = {**os.environ, "LIFE_INBOX_URL": os.environ.get("LIFE_INBOX_URL", f"http://127.0.0.1:{port}")}
    try:
        subprocess.Popen(
            [str(binary), "."], cwd=pet_dir, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=sys.platform != "win32",
        )
    except OSError:
        logger.warning("Could not start the desktop pet.", exc_info=True)
        return False
    return True
