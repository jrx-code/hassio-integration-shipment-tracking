"""Unit tests for api.filter_ignored() — the InPost zombie-record hide.

Pure-logic tests — no Home Assistant runtime needed:
    python3 -m pytest tests/test_ignored_shipments.py -q
"""
import sys
import types
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shipment_tracking"


def _load_flat(modname: str, path: Path):
    src = path.read_text()
    src = src.replace("from .const import", "from const import")
    mod = types.ModuleType(modname)
    sys.modules[modname] = mod
    exec(compile(src, str(path), "exec"), mod.__dict__)
    return mod


sys.path.insert(0, str(_PKG_DIR))
_load_flat("const", _PKG_DIR / "const.py")
_api = _load_flat("inpost_api", _PKG_DIR / "api.py")
filter_ignored = _api.filter_ignored


def _cat():
    return {
        "ready": [{"shipment": "R1"}, {"shipment": "R2"}],
        "in_transit": [{"shipment": "T1"}, {"shipment": "T2"}],
        "archived": [{"shipment": "A1"}],
    }


def test_empty_ignore_set_is_a_true_noop():
    cat = _cat()
    result = filter_ignored(cat, set())
    assert result is cat  # same object, not just equal — no copy for the common case


def test_drops_matching_shipment_from_every_bucket():
    cat = filter_ignored(_cat(), {"T1"})
    assert cat["ready"] == [{"shipment": "R1"}, {"shipment": "R2"}]
    assert cat["in_transit"] == [{"shipment": "T2"}]
    assert cat["archived"] == [{"shipment": "A1"}]


def test_ignoring_across_buckets_at_once():
    cat = filter_ignored(_cat(), {"R1", "A1", "nonexistent"})
    assert cat["ready"] == [{"shipment": "R2"}]
    assert cat["in_transit"] == [{"shipment": "T1"}, {"shipment": "T2"}]
    assert cat["archived"] == []


def test_original_cat_is_not_mutated_when_filtering_happens():
    original = _cat()
    filter_ignored(original, {"R1"})
    assert original["ready"] == [{"shipment": "R1"}, {"shipment": "R2"}]
