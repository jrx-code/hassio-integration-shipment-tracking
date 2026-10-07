"""Regression guard for the 2026-08-25 sensor.py carrier-dispatch bug.

sensor.py is the SENSOR platform for the whole shipment_tracking domain, not
just InPost — both CARRIER_INPOST and CARRIER_DPD list Platform.SENSOR in
PLATFORMS_BY_CARRIER (__init__.py), so HA forwards every carrier's config
entry to this same module. An un-dispatched async_setup_entry that always
built InPost sensor classes shipped and sat undetected because no DPD account
had actually been onboarded yet to hit it — InPostSharedSensor.native_value
calls coordinator.active(), which only InPostCoordinator defines, so the
first real DPD entry would have crashed its own platform setup with an
AttributeError.

No `homeassistant` package in this environment (see the rest of tests/ —
pure-logic / source-text checks only), so this is a source-text guard rather
than an import-and-call test: it fails loudly if the dispatch is ever
removed, rather than silently regressing until a DPD account is live again.
"""
from pathlib import Path

_SENSOR_PY = (
    Path(__file__).resolve().parents[1]
    / "custom_components" / "shipment_tracking" / "sensor.py"
)


def test_async_setup_entry_dispatches_dpd_before_building_inpost_sensors():
    src = _SENSOR_PY.read_text()
    assert "async def async_setup_entry" in src

    body = src.split("async def async_setup_entry", 1)[1]
    dpd_pos = body.find("CARRIER_DPD")
    dpd_call_pos = body.find("async_setup_dpd_sensors")
    inpost_pos = body.find("InPostReadySensor(")

    assert dpd_pos != -1, "async_setup_entry no longer checks CARRIER_DPD"
    assert dpd_call_pos != -1, "async_setup_entry no longer calls async_setup_dpd_sensors"
    assert inpost_pos != -1, "InPostReadySensor no longer built here (moved?)"
    assert dpd_call_pos < inpost_pos, (
        "DPD dispatch must come BEFORE the InPost sensor construction — "
        "otherwise a DPD entry falls through and builds InPost-shaped "
        "sensors against a DpdCoordinator"
    )


def test_sensor_dpd_module_is_imported():
    src = _SENSOR_PY.read_text()
    assert "from .sensor_dpd import async_setup_dpd_sensors" in src


def test_async_setup_entry_dispatches_dhl_before_building_inpost_sensors():
    src = _SENSOR_PY.read_text()
    body = src.split("async def async_setup_entry", 1)[1]
    dhl_pos = body.find("CARRIER_DHL")
    dhl_call_pos = body.find("async_setup_dhl_sensors")
    inpost_pos = body.find("InPostReadySensor(")

    assert dhl_pos != -1, "async_setup_entry no longer checks CARRIER_DHL"
    assert dhl_call_pos != -1, "async_setup_entry no longer calls async_setup_dhl_sensors"
    assert dhl_call_pos < inpost_pos, (
        "DHL dispatch must come BEFORE the InPost sensor construction — "
        "same DPD-shaped bug (DhlCoordinator has no InPost-only methods "
        "InPostReadySensor/InPostSharedSensor call)"
    )


def test_sensor_dhl_module_is_imported():
    src = _SENSOR_PY.read_text()
    assert "from .sensor_dhl import async_setup_dhl_sensors" in src
