"""Unit tests for PocztexCoordinator.normalize_parcel() — pure, no HA.

The not-found dict shape matches the real "not found" response captured live
2026-08-25 (PocztexApi.track() against tt.poczta-polska.pl with a made-up
number: found=False, status_code="-1"). The found-case dict is NOT from a
real response — no live parcel was available to test against this session —
it's built to match the WSDL-documented DanePrzesylki/Zdarzenie schema; see
the disclaimer in coordinator_pocztex.py / const.py.

    python3 -m pytest tests/test_pocztex_normalize.py -q
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
    src = src.replace("from .api_pocztex import", "from api_pocztex import")
    mod = types.ModuleType(modname)
    sys.modules[modname] = mod
    exec(compile(src, str(path), "exec"), mod.__dict__)
    return mod


def _load_coordinator_pocztex():
    sys.path.insert(0, str(_PKG_DIR))

    class _DUC:
        def __class_getitem__(cls, item):
            return cls

    _stub("homeassistant")
    _stub("homeassistant.config_entries", ConfigEntry=object)
    _stub("homeassistant.core", HomeAssistant=object)
    _stub("homeassistant.helpers")
    _stub("homeassistant.helpers.update_coordinator", DataUpdateCoordinator=_DUC, UpdateFailed=Exception)

    _load_flat("const", _PKG_DIR / "const.py")
    _load_flat("api_pocztex", _PKG_DIR / "api_pocztex.py")
    return _load_flat("coordinator_pocztex", _PKG_DIR / "coordinator_pocztex.py")


_coord = _load_coordinator_pocztex()

# Real not-found response captured live 2026-08-25 (RR123456785PL, a made-up
# UPU-format test number — status=-1, danePrzesylki nil).
_NOT_FOUND = {"numer": "RR123456785PL", "found": False, "status_code": "-1"}

# Synthetic — matches the WSDL schema (DanePrzesylki/Zdarzenie fields) but
# not captured from a real parcel.
_FOUND = {
    "numer": "00123456789012345678",
    "found": True,
    "status_code": "0",
    "zakonczono_obsluge": False,
    "data_nadania": "2026-08-20",
    "rodzaj_przesylki": "Paczka Pocztex",
    "events": [
        {"kod": "01", "nazwa": "Przyjęto w urzędzie nadawczym", "czas": "2026-08-20T10:00:00", "konczace": False},
        {"kod": "05", "nazwa": "W doręczeniu", "czas": "2026-08-21T08:00:00", "konczace": False},
    ],
}

_DELIVERED = dict(_FOUND, zakonczono_obsluge=True, events=[
    *_FOUND["events"],
    {"kod": "09", "nazwa": "Doręczono", "czas": "2026-08-21T14:00:00", "konczace": True},
])


def test_not_found_maps_to_inactive_with_flag():
    row = _coord.normalize_parcel(_NOT_FOUND)
    assert row["found"] is False
    assert row["active"] is False
    assert row["status"] == "Nie znaleziono"
    assert row["history"] == []


def test_found_active_uses_last_event_as_status():
    row = _coord.normalize_parcel(_FOUND)
    assert row["found"] is True
    assert row["active"] is True
    assert row["status"] == "W doręczeniu"
    assert len(row["history"]) == 2
    assert row["history"][0]["status"] == "Przyjęto w urzędzie nadawczym"


def test_delivered_is_inactive():
    row = _coord.normalize_parcel(_DELIVERED)
    assert row["active"] is False
    assert row["status"] == "Doręczono"
