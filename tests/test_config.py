from steward import config as cfg


def test_roundtrip_and_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv(cfg.ENV_CONFIG_ROOT, str(tmp_path))
    monkeypatch.delenv(cfg.ENV_API_KEY, raising=False)
    monkeypatch.delenv(cfg.ENV_LIBRARY_ID, raising=False)

    p = cfg.Profile(name="lab", library_id="123", api_key="k1",
                    data_dir="C:/ScriptoriumDemo/data",
                    backup_dir="C:/ScriptoriumDemo/backups")
    path = cfg.write_profile(p)
    assert path.is_file()

    loaded = cfg.load_profile("lab")
    assert loaded.library_id == "123"
    assert loaded.api_key == "k1"
    assert loaded.data_dir == "C:/ScriptoriumDemo/data"

    # default profile resolution
    assert cfg.load_profile(None).name == "lab"

    # env beats file
    monkeypatch.setenv(cfg.ENV_API_KEY, "env-key")
    monkeypatch.setenv(cfg.ENV_LIBRARY_ID, "999")
    over = cfg.load_profile("lab")
    assert over.api_key == "env-key"
    assert over.library_id == "999"


def test_backslashes_and_quotes_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv(cfg.ENV_CONFIG_ROOT, str(tmp_path))
    p = cfg.Profile(name="win", library_id="1",
                    api_key='ab\\cd"ef', data_dir="C:\\ScriptoriumDemo\\Zotero",
                    backup_dir="\\\\nas\\zotero-bak")
    cfg.write_profile(p)
    loaded = cfg.load_profile("win", apply_env=False)
    assert loaded.api_key == 'ab\\cd"ef'
    assert loaded.data_dir == "C:\\ScriptoriumDemo\\Zotero"
    assert loaded.backup_dir == "\\\\nas\\zotero-bak"


def test_invalid_profile_name_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv(cfg.ENV_CONFIG_ROOT, str(tmp_path))
    import pytest
    with pytest.raises(ValueError, match="invalid profile name"):
        cfg.write_profile(cfg.Profile(name="my.lab"))
    with pytest.raises(ValueError, match="invalid profile name"):
        cfg.write_profile(cfg.Profile(name="my lab"))


def test_load_tolerates_utf8_bom(tmp_path, monkeypatch):
    monkeypatch.setenv(cfg.ENV_CONFIG_ROOT, str(tmp_path))
    cfg.tool_dir().mkdir(parents=True)
    body = ('default_profile = "x"\n\n[profiles.x]\n'
            'data_dir = "C:/ScriptoriumDemo/Zotero"\n')
    cfg.config_path().write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))  # BOM + content
    assert cfg.load_profile("x", apply_env=False).data_dir == "C:/ScriptoriumDemo/Zotero"


def test_setup_does_not_persist_env_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv(cfg.ENV_CONFIG_ROOT, str(tmp_path))
    monkeypatch.setenv(cfg.ENV_API_KEY, "env-secret")
    file_only = cfg.load_profile("default", apply_env=False)
    assert file_only.api_key == ""          # env key must not leak into the wizard


def test_unknown_keys_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv(cfg.ENV_CONFIG_ROOT, str(tmp_path))
    p = cfg.Profile(name="x", library_id="1")
    p.sources = {"future_field": "kept"}
    cfg.write_profile(p)
    again = cfg.load_profile("x")
    assert again.sources.get("future_field") == "kept"
    cfg.write_profile(again)  # second rewrite must not drop it
    assert cfg.load_profile("x").sources.get("future_field") == "kept"
