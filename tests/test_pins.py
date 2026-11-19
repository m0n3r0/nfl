"""Hermetic tests for the manual pin store (src/pins.py)."""

from __future__ import annotations

import json

import pytest

from src import pins


@pytest.fixture
def pin_path(tmp_path):
    return tmp_path / "pins.json"


def test_missing_file_means_no_pins(pin_path):
    assert pins.load_pins(pin_path) == {}
    assert pins.pinned_ids(pin_path) == set()


def test_toggle_roundtrip(pin_path):
    assert pins.toggle_pin("42", "Some Player", pin_path) is True
    assert pins.pinned_ids(pin_path) == {"42"}
    stored = pins.load_pins(pin_path)["42"]
    assert stored["name"] == "Some Player"
    assert stored["pinned_at"]  # timestamp recorded
    assert pins.toggle_pin("42", "Some Player", pin_path) is False
    assert pins.load_pins(pin_path) == {}


def test_toggle_is_independent_per_player(pin_path):
    pins.toggle_pin("1", "One", pin_path)
    pins.toggle_pin("2", "Two", pin_path)
    pins.toggle_pin("1", "One", pin_path)
    assert pins.pinned_ids(pin_path) == {"2"}


def test_save_is_atomic_and_leaves_no_tmp(pin_path):
    pins.save_pins({"9": {"name": "Nine", "pinned_at": "t"}}, pin_path)
    assert json.loads(pin_path.read_text(encoding="utf-8")) == {
        "pinned": {"9": {"name": "Nine", "pinned_at": "t"}}}
    assert not pin_path.with_name(pin_path.name + ".tmp").exists()


def test_corrupt_json_raises(pin_path):
    pin_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(pins.PinsError, match="not valid JSON"):
        pins.load_pins(pin_path)


@pytest.mark.parametrize("payload", [
    "[]",
    '{"pinned": []}',
    '{"pinned": {"5": "just a name"}}',
    '{"pinned": {"5": {"name": 7}}}',
    '{"nope": {}}',
])
def test_wrong_shape_raises(pin_path, payload):
    pin_path.write_text(payload, encoding="utf-8")
    with pytest.raises(pins.PinsError):
        pins.load_pins(pin_path)


def test_unreadable_path_raises(pin_path):
    pin_path.mkdir()  # a directory where the file should be -> OSError
    with pytest.raises(pins.PinsError, match="cannot read"):
        pins.load_pins(pin_path)


def test_toggle_refuses_empty_id(pin_path):
    with pytest.raises(pins.PinsError):
        pins.toggle_pin("   ", "Nobody", pin_path)


def test_toggle_refuses_to_overwrite_corrupt_file(pin_path):
    pin_path.write_text("{corrupt", encoding="utf-8")
    with pytest.raises(pins.PinsError):
        pins.toggle_pin("1", "One", pin_path)
    assert pin_path.read_text(encoding="utf-8") == "{corrupt"
