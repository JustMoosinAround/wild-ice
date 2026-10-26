from pathlib import Path

import pytest

from wildice.config import ConfigError, load_config


def test_loads_repo_config():
    cfg = load_config(Path("config.yaml"))
    assert cfg.filters.max_road_miles == 2
    assert cfg.filters.max_trail_miles == 1
    assert cfg.ice.skate_cm == 10
    assert cfg.snow.cover_cm == 2
    assert cfg.imagery.min_valid_fraction == 0.7
    assert cfg.region.bbox == (59.3, -152.5, 62.8, -144.0)
    assert cfg.season_start == "10-01"
    assert cfg.imagery.monthly_request_budget == 9000


def test_missing_key_raises(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("ice: {alpha: 2.0}\n")
    with pytest.raises(ConfigError, match="filters"):
        load_config(p)


def test_missing_nested_key_names_it(tmp_path):
    text = Path("config.yaml").read_text().replace("  skate_cm: 10\n", "")
    p = tmp_path / "c.yaml"
    p.write_text(text)
    with pytest.raises(ConfigError, match="skate_cm"):
        load_config(p)


def test_pinned_ids_are_tuple(tmp_path):
    text = Path("config.yaml").read_text().replace("pinned: []", "pinned: [w1, r2]")
    p = tmp_path / "c.yaml"
    p.write_text(text)
    cfg = load_config(p)
    assert cfg.pinned == ("w1", "r2")
    assert cfg.hidden == ()


def test_low_sun_window_keys():
    cfg = load_config(Path("config.yaml"))
    assert cfg.imagery.low_sun_start == "11-25"
    assert cfg.imagery.low_sun_end == "01-15"


def test_low_sun_key_required(tmp_path):
    text = Path("config.yaml").read_text().replace('  low_sun_end: "01-15"\n', "")
    p = tmp_path / "c.yaml"
    p.write_text(text)
    with pytest.raises(ConfigError, match="low_sun_end"):
        load_config(p)
