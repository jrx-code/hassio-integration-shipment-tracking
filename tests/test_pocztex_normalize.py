"""Unit tests for PocztexCoordinator.normalize_parcel() — pure, no HA.

Both entries in _REAL_RESPONSE are the actual body of a live GET
/api/customer/tracking call, captured 2026-08-25 against a real account
(2 delivered parcels — no in-transit example was available, so the
progress<100="active" reading in pocztex_is_active() is untested on that
branch; see the caveat in const.py).

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
    _stub("homeassistant.const", CONF_PASSWORD="password")
    _stub("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
    _stub("homeassistant.exceptions", ConfigEntryAuthFailed=Exception)
    _stub("homeassistant.helpers")
    _stub("homeassistant.helpers.update_coordinator", DataUpdateCoordinator=_DUC, UpdateFailed=Exception)

    _load_flat("const", _PKG_DIR / "const.py")
    _load_flat("api_pocztex", _PKG_DIR / "api_pocztex.py")
    return _load_flat("coordinator_pocztex", _PKG_DIR / "coordinator_pocztex.py")


_coord = _load_coordinator_pocztex()

# Real GET /api/customer/tracking response body, captured live 2026-08-25.
_REAL_RESPONSE = [
    {
        "id": 4845650, "label": None, "createdAt": "2026-08-25T21:20:38.512+00:00",
        "archived": False, "direction": "RECIPIENT", "state": "Doręczona",
        "pickupDate": None, "consignmentNumber": "PX2319493690", "facilityType": None,
        "progressPercentage": 100, "archiveCheck": "2026-08-25T21:20:38.512+00:00",
        "stateDate": "2026-08-03T11:15:52.000+00:00", "stateCode": "P_D",
        "pni": None, "paymentRetryTime": None,
    },
    {
        "id": 4845649, "label": None, "createdAt": "2026-08-25T21:20:38.507+00:00",
        "archived": False, "direction": "RECIPIENT", "state": "Doręczona",
        "pickupDate": None, "consignmentNumber": "PX2320519593", "facilityType": None,
        "progressPercentage": 100, "archiveCheck": "2026-08-25T21:20:38.507+00:00",
        "stateDate": "2026-08-13T12:31:53.000+00:00", "stateCode": "P_D",
        "pni": None, "paymentRetryTime": None,
    },
]

# Synthetic — no in-transit example was available live.
_IN_TRANSIT = dict(_REAL_RESPONSE[0], state="W doręczeniu", progressPercentage=60,
                    stateCode="P_T", consignmentNumber="PX9999999999")


def test_normalize_real_delivered_parcels():
    rows = [_coord.normalize_parcel(p) for p in _REAL_RESPONSE]
    assert rows[0]["number"] == "PX2319493690"
    assert rows[0]["status"] == "Doręczona"
    assert rows[0]["active"] is False
    assert rows[1]["number"] == "PX2320519593"


def test_normalize_synthetic_in_transit_is_active():
    row = _coord.normalize_parcel(_IN_TRANSIT)
    assert row["active"] is True
    assert row["progress"] == 60


def test_pocztex_is_active_boundary():
    c = sys.modules["const"]
    assert c.pocztex_is_active(0) is True
    assert c.pocztex_is_active(99) is True
    assert c.pocztex_is_active(100) is False
    assert c.pocztex_is_active(None) is True
