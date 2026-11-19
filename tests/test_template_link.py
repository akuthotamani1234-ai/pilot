"""A copied test template is this product's file. A link is not copied into the run."""
import json

from backend.agents.script_generator import script_generator_agent
from backend.blueprint_progress import progress


def test_a_test_template_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.agents.script_generator as script_generator

    secret = b"tenant-b-only-template"
    other = tmp_path / "other"
    other.mkdir()
    (other / "conftest.py").write_bytes(secret)
    (other / "pytest.ini").write_bytes(secret)
    (other / "keep.txt").write_bytes(secret)

    linked = tmp_path / "templates-linked"
    linked.mkdir()
    (linked / "conftest.py").symlink_to(other / "conftest.py")
    (linked / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    monkeypatch.setattr(script_generator, "TEMPLATES", linked)
    state = {"run_dir": "", "app_map": [], "test_cases": [], "url": "https://shop.test", "log": []}
    run = tmp_path / "run"
    run.mkdir()
    refused = script_generator_agent({**state, "run_dir": str(run)})
    assert refused["scripts"] == [] and "link" in refused["log"][-1]
    assert not (run / "generated_tests" / "conftest.py").exists()
    assert (other / "conftest.py").read_bytes() == secret
    assert (other / "keep.txt").read_bytes() == secret

    ini_link = tmp_path / "templates-ini"
    ini_link.mkdir()
    (ini_link / "conftest.py").write_text("home-own-template\n", encoding="utf-8")
    (ini_link / "pytest.ini").symlink_to(other / "pytest.ini")
    monkeypatch.setattr(script_generator, "TEMPLATES", ini_link)
    ini_run = tmp_path / "ini-run"
    ini_run.mkdir()
    refused_ini = script_generator_agent({**state, "run_dir": str(ini_run)})
    assert refused_ini["scripts"] == [] and "link" in refused_ini["log"][-1]
    assert not (ini_run / "generated_tests" / "pytest.ini").exists()
    assert (other / "pytest.ini").read_bytes() == secret
    assert (other / "keep.txt").read_bytes() == secret

    real_templates = tmp_path / "templates"
    real_templates.mkdir()
    (real_templates / "conftest.py").write_text("home-own-template\n", encoding="utf-8")
    (real_templates / "pytest.ini").write_text("[pytest]\npython_files = test_*.py\n", encoding="utf-8")
    monkeypatch.setattr(script_generator, "TEMPLATES", real_templates)
    real = tmp_path / "real"
    real.mkdir()
    saved = script_generator_agent({**state, "run_dir": str(real)})
    script = real / "generated_tests" / "conftest.py"
    ini = real / "generated_tests" / "pytest.ini"
    assert script.is_file() and not script.is_symlink()
    assert script.read_text(encoding="utf-8") == "home-own-template\n"
    assert ini.read_text(encoding="utf-8").startswith("[pytest]")
    assert secret not in script.read_bytes() and secret not in ini.read_bytes()
    assert saved["scripts"] == []
    assert (other / "keep.txt").read_bytes() == secret
    assert (other / "conftest.py").read_bytes() == secret


def test_template_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-template-link")
    assert row["status"] == "done"
    gate_g = next(gate for gate in snap["gates"] if gate["id"] == "G")
    assert gate_g["status"] != "done"
    assert snap["complete"] is False
    assert "tenant-b-only-template" not in json.dumps(snap)
