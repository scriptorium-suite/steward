"""Configuration: ~/.config/scriptorium/steward/config.toml with profiles.

Precedence (scriptorium-spec specs/config-root.md):
    CLI flags > environment variables > config file > defaults.

The config file is OWNED by steward: hand-added keys inside a profile are
preserved, but unknown top-level keys are not.
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ENV_CONFIG_ROOT = "SCRIPTORIUM_CONFIG_DIR"
ENV_API_KEY = "ZOTERO_API_KEY"
ENV_LIBRARY_ID = "ZOTERO_LIBRARY_ID"
ENV_LIBRARY_TYPE = "ZOTERO_LIBRARY_TYPE"
ENV_LOCAL = "ZOTERO_LOCAL"

PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def config_root() -> Path:
    root = os.environ.get(ENV_CONFIG_ROOT)
    return Path(root) if root else Path.home() / ".config" / "scriptorium"


def tool_dir() -> Path:
    return config_root() / "steward"


def config_path() -> Path:
    return tool_dir() / "config.toml"


@dataclass
class Profile:
    name: str = "default"
    library_id: str = ""
    library_type: str = "user"
    api_key: str = ""
    local: bool = False
    data_dir: str = ""      # Zotero data directory (zotero.sqlite + storage/)
    backup_dir: str = ""    # where `steward backup` writes snapshots
    sources: dict = field(default_factory=dict)  # unknown profile keys preserved

    def missing(self, *names: str) -> list[str]:
        return [n for n in names if not getattr(self, n)]


def _apply_env(p: Profile) -> Profile:
    if os.environ.get(ENV_API_KEY):
        p.api_key = os.environ[ENV_API_KEY]
    if os.environ.get(ENV_LIBRARY_ID):
        p.library_id = os.environ[ENV_LIBRARY_ID]
    if os.environ.get(ENV_LIBRARY_TYPE):
        p.library_type = os.environ[ENV_LIBRARY_TYPE]
    if os.environ.get(ENV_LOCAL, "").lower() in ("1", "true", "yes"):
        p.local = True
    return p


def _read_toml(path: Path) -> dict:
    """Parse a TOML file, tolerating a UTF-8 BOM (common from Windows editors)."""
    if not path.is_file():
        return {}
    text = path.read_bytes().decode("utf-8-sig")  # -sig strips a leading BOM
    return tomllib.loads(text)


def load_profile(name: str | None = None, apply_env: bool = True) -> Profile:
    """Load a profile from config.toml, optionally applying env overrides.

    Works with no config file at all (pure-env operation).
    `apply_env=False` returns only what the file actually contains - the setup
    wizard uses this so env-sourced secrets are never persisted to disk.
    """
    path = config_path()
    doc = _read_toml(path)
    profiles = doc.get("profiles", {})
    name = name or doc.get("default_profile", "default")
    raw = profiles.get(name, {})
    if not isinstance(raw, dict):
        raw = {}
    known = {f_.name for f_ in Profile.__dataclass_fields__.values()}
    typed = {k: v for k, v in raw.items() if k in known and k != "name" and not isinstance(v, dict)}
    p = Profile(name=name, **typed)
    p.sources = {k: v for k, v in raw.items() if k not in known}
    return _apply_env(p) if apply_env else p


_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _toml_str(value: str) -> str:
    out = []
    for ch in value:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return _toml_str(v)
    raise ValueError(f"cannot serialize config value of type {type(v).__name__}: {v!r}")


def validate_profile_name(name: str) -> str:
    if not PROFILE_NAME_RE.match(name):
        raise ValueError(
            f"invalid profile name {name!r}: use letters, digits, '-' and '_' only")
    return name


def write_profile(p: Profile, set_default: bool = True) -> Path:
    """Write/update one profile in config.toml (rewrites the whole file)."""
    validate_profile_name(p.name)
    path = config_path()
    doc = _read_toml(path)
    profiles = doc.setdefault("profiles", {})
    entry = {
        "library_id": p.library_id,
        "library_type": p.library_type,
        "local": p.local,
        "data_dir": p.data_dir,
        "backup_dir": p.backup_dir,
    }
    if p.api_key:
        entry["api_key"] = p.api_key
    entry.update(p.sources)
    profiles[p.name] = entry
    if set_default or "default_profile" not in doc:
        doc["default_profile"] = p.name

    lines = [f"default_profile = {_toml_str(doc['default_profile'])}", ""]
    for pname, prof in profiles.items():
        if not isinstance(prof, dict):
            continue
        lines.append(f"[profiles.{_toml_str(pname)}]")
        for k, v in prof.items():
            lines.append(f"{k} = {_toml_value(v)}")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
