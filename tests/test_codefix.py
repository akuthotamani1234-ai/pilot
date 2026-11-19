"""A suggested page fix stays inside this run's saved HTML."""
from backend.codefix import Context, code_for


def test_a_page_fix_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = "tenant-b-only-html"
    other = tmp_path / "other" / "run"
    (other / "html").mkdir(parents=True)
    secret_page = f'<img src="logo.png"> {secret}\n'
    (other / "html" / "home.html").write_text(secret_page, encoding="utf-8")
    (other / "keep.txt").write_text(secret, encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(tmp_path / "other", target_is_directory=True)
    page = {"url": "https://shop.test/", "slug": "home", "status": 200}
    failure = {"test": "broken_image", "source": "crawler", "error": "logo.png", "page_url": page["url"]}
    state = {"run_dir": str(linked / "run"), "app_map": [page], "test_cases": []}
    ctx = Context(state)
    assert code_for([failure], ctx) is None
    assert secret not in ctx.html(page)
    assert (other / "html" / "home.html").read_text(encoding="utf-8") == secret_page
    assert not (other / "fresh").exists()
    assert (other / "keep.txt").read_text(encoding="utf-8") == secret

    real = tmp_path / "real"
    (real / "html").mkdir(parents=True)
    (real / "html" / "home.html").symlink_to(other / "html" / "home.html")
    linked_file = Context({"run_dir": str(real), "app_map": [page], "test_cases": []})
    assert code_for([failure], linked_file) is None
    assert secret not in linked_file.html(page)
    assert not (real / "fresh").exists()
    assert (other / "html" / "home.html").read_text(encoding="utf-8") == secret_page

    (real / "html" / "home.html").unlink()
    (real / "html" / "home.html").write_text('<img src="logo.png"> home-own\n', encoding="utf-8")
    own = Context({"run_dir": str(real), "app_map": [page], "test_cases": []})
    got = code_for([failure], own)
    assert got is not None
    assert "home-own" in got["before"]
    assert secret not in got["before"]
    assert (other / "html" / "home.html").read_text(encoding="utf-8") == secret_page
    assert (other / "keep.txt").read_text(encoding="utf-8") == secret
