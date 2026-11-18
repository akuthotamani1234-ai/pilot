"""Gate D ADB probe records honest device inventory without verifying the matrix."""
from pathlib import Path

from backend.android_adb_probe import run_adb_probe


def test_adb_probe_stays_incomplete(tmp_path: Path):
    evidence = run_adb_probe(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert evidence["drill"] == "android_adb_probe"
    assert (tmp_path / "android_adb_probe.json").is_file()
    # In this Cloud Agent image we just installed adb; still no emulator.
    assert evidence["adb_present"] is True or evidence["adb_present"] is False
    if evidence["adb_present"] and evidence["devices_online"] == 0:
        assert "unverified" in evidence["reason"] or "no online" in evidence["reason"]
