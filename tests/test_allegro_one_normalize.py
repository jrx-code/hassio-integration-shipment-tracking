"""Unit tests for Allegro One status mapping + normalize_parcel() — pure, no HA.

_SAMPLE is trimmed from a live GET https://edge.allegro.pl/ad/tracking
?packageNo=A000YR4D27 response captured 2026-09-18 (Accept:
application/vnd.allegro.internal.v1+json, Accept-Language: pl-PL).

    python3 -m pytest tests/test_allegro_one_normalize.py -q
"""
import sys
import types
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shipment_tracking"


def _stub(name: str, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def _load_flat(modname: str, path: Path):
    src = path.read_text()
    src = src.replace("from .const import", "from const import")
    src = src.replace("from .carriers_orlen_allegro import", "from carriers_orlen_allegro import")
    src = src.replace("from .api_allegro_one import", "from api_allegro_one import")
    mod = types.ModuleType(modname)
    sys.modules[modname] = mod
    exec(compile(src, str(path), "exec"), mod.__dict__)
    return mod


def _load_coordinator_allegro_one():
    sys.path.insert(0, str(_PKG_DIR))

    class _DUC:
        def __class_getitem__(cls, item):
            return cls

    _stub("homeassistant")
    _stub("homeassistant.config_entries", ConfigEntry=object)
    _stub("homeassistant.core", HomeAssistant=object)
    _stub("homeassistant.exceptions", ConfigEntryAuthFailed=Exception)
    _stub("homeassistant.helpers")
    _stub(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=_DUC,
        UpdateFailed=Exception,
    )

    _load_flat("carriers_orlen_allegro", _PKG_DIR / "carriers_orlen_allegro.py")
    _load_flat("const", _PKG_DIR / "const.py")
    _load_flat("api_allegro_one", _PKG_DIR / "api_allegro_one.py")
    return _load_flat("coordinator_allegro_one", _PKG_DIR / "coordinator_allegro_one.py")


_coord = _load_coordinator_allegro_one()
_c = sys.modules["carriers_orlen_allegro"]

# Live capture 2026-09-18 — order as returned (unsorted); normalize sorts.
_SAMPLE = {
    "number": "A000YR4D27",
    "status": [
        {"eventTimestamp": "2024-08-19T15:18:24.572Z", "description": "Przesyłka została doręczona"},
        {"eventTimestamp": "2024-08-19T08:55:20.959Z", "description": "Przesyłka oczekuje na odbiór"},
        {"eventTimestamp": "2024-08-19T08:53:25Z", "description": "Przesyłka została wydana do doręczenia"},
        {"eventTimestamp": "2024-08-16T18:11:47Z", "description": "Przesyłka została odebrana przez kuriera"},
        {"eventTimestamp": "2024-08-16T10:29:03.598Z", "description": "Przesyłka została przygotowana przez nadawcę"},
    ],
}


def test_keyword_canonical_buckets():
    assert _c.allegro_one_canonical("Przesyłka została przygotowana przez nadawcę") == "created"
    assert _c.allegro_one_canonical("Przesyłka została odebrana przez kuriera") == "in_transport"
    assert _c.allegro_one_canonical("Przesyłka została wydana do doręczenia") == "handed_out_for_delivery"
    assert _c.allegro_one_canonical("Przesyłka oczekuje na odbiór") == "waiting_for_pickup"
    assert _c.allegro_one_canonical("Przesyłka została doręczona") == "delivered"
    assert _c.allegro_one_canonical("Parcel has been delivered") == "delivered"
    assert _c.allegro_one_canonical("") == "unknown"


def test_is_active_terminal_buckets():
    assert _c.allegro_one_is_active("Przesyłka oczekuje na odbiór")
    assert _c.allegro_one_is_active("Przesyłka została wydana do doręczenia")
    assert not _c.allegro_one_is_active("Przesyłka została doręczona")


def test_normalize_parcel_from_live_sample():
    row = _coord.normalize_parcel(_SAMPLE)
    assert row["number"] == "A000YR4D27"
    assert row["canonical"] == "delivered"
    assert row["active"] is False
    assert row["updated"] == "2024-08-19T15:18:24.572Z"
    assert row["status"] == "Przesyłka została doręczona"
    assert len(row["history"]) == 5
    # newest first
    assert row["history"][0]["status"] == "Przesyłka została doręczona"
    assert row["history"][-1]["status"] == "Przesyłka została przygotowana przez nadawcę"


def test_in_transit_sample_is_active():
    mid = {
        "number": "A000YR4D27",
        "status": [
            {"eventTimestamp": "2024-08-16T18:11:47Z", "description": "Przesyłka została odebrana przez kuriera"},
            {"eventTimestamp": "2024-08-16T10:29:03.598Z", "description": "Przesyłka została przygotowana przez nadawcę"},
        ],
    }
    row = _coord.normalize_parcel(mid)
    assert row["canonical"] == "in_transport"
    assert row["active"] is True


def test_normalize_empty_status_list():
    row = _coord.normalize_parcel({"number": "A000EMPTY0", "status": []})
    assert row["number"] == "A000EMPTY0"
    assert row["canonical"] == "unknown"
    assert row["status"] == "—"
    assert row["active"] is True  # unknown is not terminal
    assert row["history"] == []
    assert row["updated"] is None


def test_returned_and_cancelled_keywords():
    assert _c.allegro_one_canonical("Przesyłka została zwrócona do nadawcy") == "returned"
    assert _c.allegro_one_canonical("Przesyłka anulowana") == "cancelled"
    assert not _c.allegro_one_is_active("Przesyłka została zwrócona do nadawcy")
    assert not _c.allegro_one_is_active("Przesyłka anulowana")


def test_status_pl_keeps_raw_for_unknown():
    assert _c.allegro_one_status_pl("Brand new mystery status") == "Brand new mystery status"
    assert _c.allegro_one_status_pl("") == "—"
