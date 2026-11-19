from textureng.migrate import migrate_files


def test_copies_settings_and_history(tmp_path):
    old, new = tmp_path / "VoxPolish", tmp_path / "Textureng"
    old.mkdir()
    (old / "config.json").write_text('{"language": "tr"}', encoding="utf-8")
    (old / "history.db").write_bytes(b"db")
    (old / "voxpolish.log").write_text("log", encoding="utf-8")
    assert migrate_files(old, new) == ["config.json", "history.db"]
    assert (new / "config.json").read_text(encoding="utf-8") == '{"language": "tr"}'
    assert not (new / "voxpolish.log").exists()
    assert (old / "config.json").exists()  # the old folder is left alone


def test_does_not_overwrite_existing_settings(tmp_path):
    old, new = tmp_path / "VoxPolish", tmp_path / "Textureng"
    old.mkdir(); new.mkdir()
    (old / "config.json").write_text("old", encoding="utf-8")
    (new / "config.json").write_text("new", encoding="utf-8")
    assert migrate_files(old, new) == []
    assert (new / "config.json").read_text(encoding="utf-8") == "new"


def test_nothing_to_migrate(tmp_path):
    assert migrate_files(tmp_path / "missing", tmp_path / "Textureng") == []
