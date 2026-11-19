"""An AI prompt stays in the prompt folder. A link is not that prompt."""
import pytest

from backend.llm import PROMPTS_DIR, load_prompt


def test_an_ai_prompt_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = "tenant-b-only-prompt"
    own = "home-own prompt text"
    other = tmp_path / "other"
    other.mkdir()
    (other / "note.txt").write_text(secret, encoding="utf-8")
    (other / "leaf.txt").write_text(secret, encoding="utf-8")
    before = sorted(path.name for path in other.iterdir())
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "linked").symlink_to(other, target_is_directory=True)
    (prompts / "leaf.txt").symlink_to(other / "leaf.txt")
    (prompts / "home.txt").write_text(own, encoding="utf-8")
    monkeypatch.setattr("backend.llm.PROMPTS_DIR", prompts)

    with pytest.raises(OSError, match="link"):
        load_prompt("linked/note")
    with pytest.raises(OSError, match="link"):
        load_prompt("leaf")
    with pytest.raises(OSError, match="link"):
        load_prompt("../other/note")
    assert (other / "note.txt").read_text(encoding="utf-8") == secret
    assert (other / "leaf.txt").read_text(encoding="utf-8") == secret
    assert sorted(path.name for path in other.iterdir()) == before

    found = load_prompt("home")
    assert found == own
    assert secret not in found

    monkeypatch.setattr("backend.llm.PROMPTS_DIR", PROMPTS_DIR)
    shipped = load_prompt("untrusted")
    assert "untrusted DATA" in shipped
    assert secret not in shipped
