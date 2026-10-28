import json
from dataclasses import replace
from pathlib import Path

from wildice.config import load_config
from wildice.prefs import load_prefs

# start from no pins/hides so the tests don't depend on the owner's config
cfg = replace(load_config(Path("config.yaml")), pinned=(), hidden=())


def put(d, name, lake_id, action):
    (d / name).write_text(json.dumps({"lake_id": lake_id, "action": action}), encoding="utf-8")


def test_prefs_apply_in_order(tmp_path):
    put(tmp_path, "001.json", "w1", "pin")
    put(tmp_path, "002.json", "w2", "hide")
    put(tmp_path, "003.json", "w1", "unpin")
    assert load_prefs(cfg, tmp_path) == (frozenset(), frozenset({"w2"}))


def test_prefs_config_base(tmp_path):
    c = replace(cfg, pinned=("w9",))
    assert load_prefs(c, tmp_path) == (frozenset({"w9"}), frozenset())


def test_prefs_unhide_and_missing_dir(tmp_path):
    c = replace(cfg, hidden=("w3",))
    put(tmp_path, "a.json", "w3", "unhide")
    assert load_prefs(c, tmp_path) == (frozenset(), frozenset())
    assert load_prefs(c, tmp_path / "nope") == (frozenset(), frozenset({"w3"}))


def test_prefs_bad_files_skipped_and_warned(tmp_path, caplog):
    import logging
    (tmp_path / "001.json").write_text("{not json", encoding="utf-8")
    put(tmp_path, "002.json", "w1", "pinn")
    put(tmp_path, "003.json", "w2", "pin")
    put(tmp_path, "004.json", "w3", "hide")
    with caplog.at_level(logging.WARNING, logger="wildice.prefs"):
        got = load_prefs(cfg, tmp_path)
    assert got == (frozenset({"w2"}), frozenset({"w3"}))
    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("001.json" in m for m in msgs)
    assert any("002.json" in m and "pinn" in m for m in msgs)
    assert len(msgs) == 2
