"""Unit tests for Orlen Paczka status mapping + normalize_parcel() — pure, no HA.

Response shape matches the public JSONP endpoint
nadaj.orlenpaczka.pl/parcel/api-status (same as jwilk/pacz). The sample
below is a synthetic but schema-faithful fixture — no live waybill was on
hand for a full history capture (2026-09-18 probe of an unknown id returned
{"err":1003}).

    python3 -m pytest tests/test_orlen_normalize.py -q
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
    src = src.replace("from .api_orlen import", "from api_orlen import")
    mod = types.ModuleType(modname)
    sys.modules[modname] = mod
    exec(compile(src, str(path), "exec"), mod.__dict__)
    return mod


def _load_coordinator_orlen():
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
    _load_flat("api_orlen", _PKG_DIR / "api_orlen.py")
    return _load_flat("coordinator_orlen", _PKG_DIR / "coordinator_orlen.py")


_coord = _load_coordinator_orlen()
_c = sys.modules["carriers_orlen_allegro"]

_SAMPLE = {
    "status": "Przesyłka oczekuje na odbiór",
    "number": "2100064143434",
    "full": True,
    "historyHtml": "",
    "history": [
        {"date": "19-08-2024, 15:18", "label": "Przesyłka oczekuje na odbiór "},
        {"date": "19-08-2024, 08:55", "label": "Przesyłka w drodze do punktu"},
        {"date": "16-08-2024, 10:29", "label": "Przesyłka nadana"},
    ],
    "label": "Przesyłka oczekuje na odbiór",
    "return": False,
    "truckNo": "Brak danych",
    "returnTruck": "Brak danych",
}


def test_keyword_canonical_buckets():
    assert _c.orlen_canonical("Przesyłka nadana") == "in_transport"
    assert _c.orlen_canonical("Przesyłka w drodze") == "in_transport"
    assert _c.orlen_canonical("Przesyłka oczekuje na odbiór") == "waiting_for_pickup"
    assert _c.orlen_canonical("Przesyłka została odebrana") == "delivered"
    assert _c.orlen_canonical("Przesyłka zwrócona do nadawcy") == "returned"
    assert _c.orlen_canonical("Anulowana") == "cancelled"
    assert _c.orlen_canonical("") == "unknown"


def test_is_active_terminal_buckets():
    assert _c.orlen_is_active("Przesyłka w drodze")
    assert _c.orlen_is_active("Przesyłka oczekuje na odbiór")
    assert not _c.orlen_is_active("Przesyłka została odebrana")
    assert not _c.orlen_is_active("Przesyłka zwrócona do nadawcy")
    assert not _c.orlen_is_active("Anulowana")


def test_normalize_parcel_from_sample():
    row = _coord.normalize_parcel(_SAMPLE)
    assert row["number"] == "2100064143434"
    assert row["canonical"] == "waiting_for_pickup"
    assert row["active"] is True
    assert row["updated"] == "2024-08-19 15:18"
    assert row["truck_no"] is None
    assert len(row["history"]) == 3
    assert row["history"][0]["status"] == "Przesyłka oczekuje na odbiór"


def test_status_pl_keeps_raw_for_unknown():
    assert _c.orlen_status_pl("Jakiś nowy status") == "Jakiś nowy status"
    assert _c.orlen_status_pl("") == "—"


def test_normalize_err_shaped_payload_does_not_crash():
    """API returns None for err 1003; normalize itself must tolerate the shape."""
    out = _coord.normalize_parcel({"err": 1003})
    assert out["number"] is None
    assert out["canonical"] == "unknown"
    assert out["status"] == "—"
    assert out["history"] == []


def test_normalize_empty_history_still_maps_status():
    thin = {
        "status": "Przesyłka nadana",
        "number": "2100000000001",
        "full": False,
        "history": [],
        "label": "Przesyłka nadana",
        "return": False,
        "truckNo": "ABC123",
        "returnTruck": "Brak danych",
    }
    row = _coord.normalize_parcel(thin)
    assert row["number"] == "2100000000001"
    assert row["canonical"] == "in_transport"
    assert row["active"] is True
    assert row["truck_no"] == "ABC123"
    assert row["history"] == []
    assert row["updated"] is None


def test_status_pl_known_keeps_raw_label():
    # Known buckets keep the carrier's free-text label (entity display).
    assert _c.orlen_status_pl("Przesyłka została odebrana") == "Przesyłka została odebrana"
