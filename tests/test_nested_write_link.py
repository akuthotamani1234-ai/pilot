"""A nested run file stays in its folder. A directory link is not that file."""
from backend.finalization import path_unless_linked, write_text_unless_linked


def test_a_nested_run_file_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = "tenant-b-only-nested"
    other = tmp_path / "other"
    other.mkdir()
    (other / "page.html").write_text(secret, encoding="utf-8")
    before = sorted(path.name for path in other.iterdir())
    run = tmp_path / "run"
    run.mkdir()
    (run / "linked").symlink_to(other, target_is_directory=True)

    assert path_unless_linked(run, "linked/page.html") is None
    assert write_text_unless_linked(run, "linked/page.html", "home-own page") is False
    assert (other / "page.html").read_text(encoding="utf-8") == secret
    assert sorted(path.name for path in other.iterdir()) == before

    assert path_unless_linked(run, "page.html") == run / "page.html"
    assert write_text_unless_linked(run, "page.html", "home-own page") is True
    assert (run / "page.html").read_text(encoding="utf-8") == "home-own page"
    assert secret not in (run / "page.html").read_text(encoding="utf-8")
    assert (other / "page.html").read_text(encoding="utf-8") == secret
