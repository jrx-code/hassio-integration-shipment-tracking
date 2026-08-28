"""Unit tests for DhlCoordinator.normalize_parcel() and const.py's DHL
canonical mapping — pure, no HA.

_REAL_SHIPMENT is the actual body of one entry from a live POST
/user/shipment/v2.1/list/incoming/active/1 call, captured 2026-08-26
against a real account (1 delivered parcel — no in-transit example was
available, so only the TT_DOR/"delivered" branch of dhl_canonical() is
exercised against real data; everything else falls back to "unknown" by
design, see the caveat in const.py).

    python3 -m pytest tests/test_dhl_normalize.py -q
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
    src = src.replace("from .api_dhl import", "from api_dhl import")
    mod = types.ModuleType(modname)
    sys.modules[modname] = mod
    exec(compile(src, str(path), "exec"), mod.__dict__)
    return mod


def _load_coordinator_dhl():
    sys.path.insert(0, str(_PKG_DIR))

    class _DUC:
        def __class_getitem__(cls, item):
            return cls

    class _State:
        """Stand-in for ConfigEntryState — identity is all the code needs."""

        LOADED = "loaded"
        SETUP_IN_PROGRESS = "setup_in_progress"

    _stub("homeassistant")
    _stub("homeassistant.config_entries", ConfigEntry=object, ConfigEntryState=_State)
    _stub("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
    _stub("homeassistant.exceptions", ConfigEntryAuthFailed=Exception)
    _stub("homeassistant.helpers")
    _stub("homeassistant.helpers.update_coordinator", DataUpdateCoordinator=_DUC, UpdateFailed=Exception)

    _load_flat("const", _PKG_DIR / "const.py")
    _load_flat("api_dhl", _PKG_DIR / "api_dhl.py")
    return _load_flat("coordinator_dhl", _PKG_DIR / "coordinator_dhl.py")


_coord = _load_coordinator_dhl()

# Real POST /user/shipment/v2.1/list/incoming/active/1 entry, captured live 2026-08-26.
_REAL_SHIPMENT = {
    "shipmentNumber": "30413196282",
    "customTitle": None,
    "sender": "Amazon EU SARL",
    "receiver": None,
    "status": "TT_DOR",
    "packageType": "Courier",
    "parcelExpirationDate": None,
    "cod": {"packagePaymentStatus": None},
    "permissions": {
        "canArchiveShipment": True, "canRemoveShipment": True,
        "canRedirectShipment": False, "showResignedFromShipment": False,
        "showLostShipment": False, "showDisposedhipment": False,
        "canCreateReturn": True,
    },
    "menuTimelineLabel": {
        "status": "Delivered", "label": "ReceiptDate", "dateText": None,
        "dateUtc": "2026-08-26T09:54:29Z", "dateToUtc": None, "showHour": True,
    },
    "inAppPaymentStatus": None,
    "returnInfo": {"isReturn": False},
    "returnAuthorizationInfo": None,
    "isShippingCache": False,
    "hasActiveIntervention": False,
    "hasClosedIntervention": False,
    "isHeartActionShipment": False,
}


def test_normalize_parcel_maps_known_status():
    row = _coord.normalize_parcel(_REAL_SHIPMENT)
    assert row["number"] == "30413196282"
    assert row["sender"] == "Amazon EU SARL"
    assert row["status_raw"] == "TT_DOR"
    # DHL's own wording, from menuTimelineLabel.status ("Delivered"), not the
    # TT_DOR code — their bundle never translates TT_ codes at all.
    assert row["status_timeline"] == "Delivered"
    assert row["status"] == "Doręczona"
    assert row["canonical"] == "delivered"
    assert row["active"] is False
    assert row["updated"] == "2026-08-26T09:54:29Z"
    assert row["package_type"] == "Courier"
    assert row["shared"] is False


def test_normalize_parcel_shared_flag():
    row = _coord.normalize_parcel(_REAL_SHIPMENT, shared=True)
    assert row["shared"] is True


def test_unknown_status_falls_back_to_raw_not_a_guess():
    const = sys.modules["const"]
    assert const.dhl_canonical("TT_SOMETHING_NEW") == "unknown"
    assert const.dhl_status_pl("TT_SOMETHING_NEW") == "TT_SOMETHING_NEW"
    assert const.dhl_is_active("TT_SOMETHING_NEW") is True


# ------------------- status vocabulary from DHL's own bundle -------------------
# menuTimelineLabel.status keys and their Polish labels were read out of the Mój
# DHL web app's shipped chunks (2026-08-28). The TT_ codes are NOT translated
# anywhere in that bundle, which is why the timeline key is what we key on.


def test_timeline_status_wins_over_the_tt_code():
    """TT_LK was the live example that used to leak a raw code into the panel."""
    const = sys.modules["const"]
    assert const.dhl_status_pl("TT_LK", "Route") == "W drodze"
    assert const.dhl_canonical("TT_LK", "Route") == "in_transport"
    assert const.dhl_is_active("TT_LK", "Route") is True
    # …and without the timeline the unknown code still refuses to guess.
    assert const.dhl_status_pl("TT_LK") == "TT_LK"


def test_handed_to_a_locker_is_waiting_for_pickup_not_delivered():
    """The whole point of the tile's "do odbioru" phase: a parcel sitting in a
    locker is not finished, it is waiting for someone to walk over."""
    const = sys.modules["const"]
    for key in ("DeliveredToLocker", "DeliveredToPoint"):
        assert const.dhl_canonical("", key) == "waiting_for_pickup"
        assert const.dhl_is_active("", key) is True
    assert const.dhl_status_pl("", "DeliveredToLocker") == "Doręczona do automatu"


def test_collected_and_returned_are_terminal():
    const = sys.modules["const"]
    for key in ("Delivered", "RetrievedFromLocker", "RetrievedFromPoint",
                "ParcelReturnedToSender", "Resignated", "Disposed"):
        assert const.dhl_is_active("", key) is False, key


def test_trouble_states_stay_visible():
    """A late, refused or lost parcel must not slip into the archive."""
    const = sys.modules["const"]
    for key in ("DeliveryDelay", "UnsuccessfulAttemptAtDelivery",
                "SecondUnsuccessfulAttemptAtDelivery", "Lost",
                "DeliveryProblem", "WaitingForShipperDecision", "ContactDHL"):
        assert const.dhl_canonical("", key) == "exception", key
        assert const.dhl_is_active("", key) is True, key


def test_unknown_timeline_key_shows_the_key_not_a_guess():
    const = sys.modules["const"]
    assert const.dhl_status_pl("TT_DOR", "SomeBrandNewState") == "SomeBrandNewState"
    assert const.dhl_canonical("TT_DOR", "SomeBrandNewState") == "delivered"


def test_every_label_has_a_known_bucket():
    const = sys.modules["const"]
    for key, (bucket, label) in const._DHL_TIMELINE.items():
        assert bucket in const.DHL_CANONICAL_PL, (key, bucket)
        assert label and label.strip() == label, key


def test_prefix_has_no_plus_sign():
    """Confirmed live 2026-08-26: "+48" gets HTTP 422 "Prefix is incorrect",
    only bare "48" is accepted. Regression guard against reintroducing the
    "+" that cost the first live attempt."""
    src = (_PKG_DIR / "api_dhl.py").read_text()
    assert '"prefix": "48"' in src
    assert '"prefix": "+48"' not in src


# --------------------- rotating cookie jar, persisted ---------------------
# The first restart after DHL went live came up "DHL session expired" on both
# accounts: entry.data still held the LOGIN-time jar, and DHL rotates the whole
# set on every /auth/refresh — replaying the stored one live returned 401 with
# and without its expired access-token. These guard the fix (persist the jar
# whenever it moves) and the one condition that makes the write safe.


class _FakeEntry:
    def __init__(self, cookies, state):
        self.data = {"device_id": "dev-1", "cookies": cookies}
        self.options = {}
        self.entry_id = "e1"
        self.state = state


class _FakeConfigEntries:
    def __init__(self):
        self.updates = []

    def async_update_entry(self, entry, **kwargs):
        self.updates.append(kwargs)
        entry.data = kwargs.get("data", entry.data)


class _FakeHass:
    def __init__(self):
        self.config_entries = _FakeConfigEntries()


def _coordinator(stored, jar, state):
    """A DhlCoordinator with __init__ bypassed — only _persist_cookies is
    under test, and the real __init__ wants a live DataUpdateCoordinator."""
    c = _coord.DhlCoordinator.__new__(_coord.DhlCoordinator)
    c.hass = _FakeHass()
    c.entry = _FakeEntry(stored, state)
    api = _coord.DhlApi()
    api.import_cookies(jar)
    c._api = api
    return c


_STARY = [{"name": "access-remember", "value": "old", "domain": "mojdhl.pl",
           "path": "/", "secure": True}]
_NOWY = [{"name": "access-remember", "value": "new", "domain": "mojdhl.pl",
          "path": "/", "secure": True}]


def test_rotated_jar_is_written_back_to_entry_data():
    loaded = _coord.ConfigEntryState.LOADED
    c = _coordinator(_STARY, _NOWY, loaded)
    c._persist_cookies()
    assert len(c.hass.config_entries.updates) == 1
    zapisane = c.hass.config_entries.updates[0]["data"]["cookies"]
    assert [x["value"] for x in zapisane] == ["new"]
    # device_id must survive the merge — entry.data is not replaced wholesale.
    assert c.hass.config_entries.updates[0]["data"]["device_id"] == "dev-1"


def test_unchanged_jar_writes_nothing():
    loaded = _coord.ConfigEntryState.LOADED
    c = _coordinator(_STARY, _STARY, loaded)
    c._persist_cookies()
    assert c.hass.config_entries.updates == []


def test_no_write_while_the_entry_is_still_setting_up():
    """Persisting from the first refresh is what left DPD's coordinator empty
    until a reload (coordinator_dpd.py) — this path stays closed."""
    setting_up = _coord.ConfigEntryState.SETUP_IN_PROGRESS
    c = _coordinator(_STARY, _NOWY, setting_up)
    c._persist_cookies()
    assert c.hass.config_entries.updates == []


def test_reload_listener_ignores_data_only_updates():
    """The cookie write happens every poll; _async_reload_on_update must not
    turn that into a reload every poll."""
    src = (_PKG_DIR / "__init__.py").read_text()
    assert 'getattr(entry, "runtime_data", None), "setup_options"' in src
    assert "coordinator.setup_options = dict(entry.options)" in src
