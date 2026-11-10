# tests/test_keys.py
import os
import stat
import hashlib
import pytest
from pathlib import Path

import keys


def test_add_returns_key_that_looks_up_with_scope():
    key = keys.add("myid", "guest")
    record = keys.lookup_file(key)
    assert isinstance(record, keys.KeyRecord)
    assert record.id == "myid"
    assert record.scope == "guest"
    # defaults for guest
    defaults = keys.DEFAULTS["guest"]
    assert record.per_minute == defaults["per_minute"]
    assert record.per_day_llm == defaults["per_day_llm"]
    assert record.per_day_stt_seconds == defaults["per_day_stt_seconds"]
    assert record.revoked is False


def test_file_holds_hash_not_key():
    key = keys.add("id2", "owner")
    file_path = Path(os.environ["MAVIS_KEYS_FILE"])
    text = file_path.read_text(encoding="utf-8")
    # the raw key must not appear in the file
    assert key not in text
    # but its sha256 hex digest must
    digest = hashlib.sha256(key.encode()).hexdigest()
    assert digest in text


def test_revoked_key_fails_next_lookup_without_restart():
    key = keys.add("id3", "guest")
    assert keys.lookup_file(key) is not None
    keys.revoke("id3")
    assert keys.lookup_file(key) is None


def test_unknown_none_and_nonstr_return_none():
    assert keys.lookup_file(None) is None
    assert keys.lookup_file(12345) is None
    assert keys.lookup_file("nonexistent-key") is None


def test_file_mode_is_600():
    keys.add("id4", "owner")
    file_path = Path(os.environ["MAVIS_KEYS_FILE"])
    mode = stat.S_IMODE(os.stat(file_path).st_mode)
    assert mode == 0o600


def test_duplicate_id_and_bad_scope_raise():
    keys.add("dup", "guest")
    with pytest.raises(ValueError):
        keys.add("dup", "guest")  # duplicate id
    with pytest.raises(ValueError):
        keys.add("new_id", "invalid_scope")  # unknown scope


def test_missing_file_lookup_none_and_has_records_false():
    file_path = Path(os.environ["MAVIS_KEYS_FILE"])
    if file_path.exists():
        file_path.unlink()
    assert keys.lookup_file("anything") is None
    assert keys.has_records() is False


def test_list_records_never_contains_key_material():
    raw_key = keys.add("secretid", "owner")
    records = keys.list_records()
    assert isinstance(records, list)
    for rec in records:
        assert isinstance(rec, keys.KeyRecord)
        # ensure no attribute equals the raw key material
        for field in rec.__dataclass_fields__:  # type: ignore[attr-defined]
            value = getattr(rec, field)
            assert str(value) != raw_key


def test_corrupt_file_rejects_file_keys_without_raising():
    key = keys.add("x", "guest")
    Path(os.environ["MAVIS_KEYS_FILE"]).write_text("{not json,", encoding="utf-8")
    assert keys.lookup_file(key) is None
    assert keys.has_records() is False


def test_entry_missing_revoked_still_loads_and_bad_entries_skipped():
    import json
    key = "k" * 43
    path = Path(os.environ["MAVIS_KEYS_FILE"])
    path.write_text(json.dumps({"keys": [
        {"hash": hashlib.sha256(key.encode()).hexdigest(), "id": "old",
         "scope": "guest", "per_minute": 10, "per_day_llm": 50, "per_day_stt_seconds": 300},
        {"hash": "abc", "id": "owner-env", "scope": "guest", "per_minute": 1,
         "per_day_llm": 1, "per_day_stt_seconds": 1},
        {"id": "nohash"},
    ]}), encoding="utf-8")
    assert keys.lookup_file(key).id == "old"
    assert [r.id for r in keys.list_records()] == ["old"]


def test_owner_env_id_is_reserved():
    with pytest.raises(ValueError):
        keys.add(keys.OWNER_ENV_ID, "guest")


def test_is_active_tracks_revoke():
    keys.add("y", "guest")
    assert keys.is_active("y")
    keys.revoke("y")
    assert not keys.is_active("y")
    assert not keys.is_active("nobody")
