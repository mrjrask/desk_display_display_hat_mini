import paths
import storage_overrides


def test_env_override_beats_shared_hint(monkeypatch, tmp_path):
    preferred = tmp_path / "preferred"
    hinted = tmp_path / "hinted"
    hint_file = tmp_path / "hint.txt"

    hinted.mkdir()
    hint_file.write_text(str(hinted), encoding="utf-8")

    monkeypatch.setenv("DESK_DISPLAY_SCREENSHOT_DIR", str(preferred))
    monkeypatch.setattr(paths, "_SHARED_HINT_PATH", hint_file)
    monkeypatch.setattr(paths, "_iter_candidate_roots", lambda: iter([]))
    monkeypatch.setattr(storage_overrides, "SCREENSHOT_DIR", None, raising=False)

    storage_paths = paths.resolve_storage_paths(logger=None)

    assert storage_paths.screenshot_dir == preferred
    assert hint_file.read_text(encoding="utf-8") == str(preferred)
