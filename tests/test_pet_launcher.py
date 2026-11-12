"""Finding the desktop pet's Electron binary on each platform."""

import sys

from app.pet_launcher import electron_binary, launch_pet


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    return path


def test_windows_uses_the_real_exe_not_the_shell_script(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    _touch(tmp_path / "node_modules" / ".bin" / "electron")
    assert electron_binary(tmp_path) is None
    exe = _touch(tmp_path / "node_modules" / "electron" / "dist" / "electron.exe")
    assert electron_binary(tmp_path) == exe


def test_mac_and_linux_use_the_bin_link(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert electron_binary(tmp_path) is None
    link = _touch(tmp_path / "node_modules" / ".bin" / "electron")
    assert electron_binary(tmp_path) == link


def test_launch_is_skipped_when_not_installed_or_turned_off(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert launch_pet(8000, tmp_path) is False
    monkeypatch.setenv("LIFE_INBOX_LAUNCH_PET", "false")
    assert launch_pet(8000, tmp_path) is False
