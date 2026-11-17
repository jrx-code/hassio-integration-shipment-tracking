"""DPD parcel services for the App Hub DPD app (and automations).

Reads and writes the DPD Mobile management endpoints for one parcel of a
configured DPD account, so a dashboard can do what the DPD Mobile app does
(docs/DPD_MOBILE_API.md). The App Hub app never talks to DPD itself: it calls
these services, which run through the account's coordinator.

- ``dpd_parcel_options``: allowed operations, delivery dates, redirect
  requirements and the pickup PIN of a parcel (read only, response).
- ``dpd_parcel_action``: change the date, redirect to a Pickup point, change the
  address or refuse the parcel. Each one changes a real delivery, so it is an
  admin service; ``dpd_parcel_options`` returns the pickup PIN to admins only.
- ``dpd_points``: Pickup points and boxes near a place (read only, response).

Opening a DPD box is not here on purpose: DPD Mobile opens Swipbox lockers over
Bluetooth LE next to the box, there is no remote-open endpoint. The PIN from
``dpd_parcel_options`` works on boxes with a PIN pad.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service

from .api_dpd import DpdAuthError, DpdError
from .const import CARRIER_DPD, CONF_CARRIER, DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_OPTIONS = "dpd_parcel_options"
SERVICE_ACTION = "dpd_parcel_action"
SERVICE_POINTS = "dpd_points"

# DPD operation codes from allowed-operations, mapped to the action names.
OPERATIONS = {
    "change_date": "DELIVERY_DATE_AND_TIME_CHANGE",
    "redirect": "DIRECT_TO_PARCEL_SHOP",
    "change_address": "DELIVERY_ADDRESS_CHANGE",
    "refuse": "REFUSE_PARCEL",
}

OPTIONS_SCHEMA = vol.Schema({vol.Required("waybill"): cv.string})
POINTS_SCHEMA = vol.Schema(
    {
        vol.Required("latitude"): vol.Coerce(float),
        vol.Required("longitude"): vol.Coerce(float),
        vol.Optional("count", default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
        vol.Optional("radius_km", default=3): vol.All(vol.Coerce(int), vol.Range(min=1, max=3)),
        vol.Optional("waybill"): cv.string,
    }
)
ACTION_SCHEMA = vol.Schema(
    {
        vol.Required("waybill"): cv.string,
        vol.Required("action"): vol.In(list(OPERATIONS)),
        vol.Optional("date"): cv.string,
        vol.Optional("point_id"): cv.string,
        vol.Optional("address"): cv.string,
        vol.Optional("city"): cv.string,
        vol.Optional("postal_code"): cv.string,
        vol.Optional("note", default=""): cv.string,
        vol.Optional("reason"): cv.string,
    }
)


def _coordinators(hass: HomeAssistant) -> list:
    return [
        e.runtime_data
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get(CONF_CARRIER) == CARRIER_DPD
        and e.state is ConfigEntryState.LOADED
        and getattr(e, "runtime_data", None) is not None
    ]


def _owner(hass: HomeAssistant, waybill: str):
    for coordinator in _coordinators(hass):
        if coordinator.knows(waybill):
            return coordinator
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="dpd_unknown_parcel",
        translation_placeholders={"waybill": waybill},
    )


def _parcel_options(coordinator, waybill: str, with_pin: bool) -> dict[str, Any]:
    api = coordinator.api
    access = coordinator.access_token()
    codes, token = api.allowed_operations(access, waybill)
    result: dict[str, Any] = {
        "waybill": waybill,
        "operations": [name for name, code in OPERATIONS.items() if code in codes],
        "operation_codes": codes,
        "dates": [],
        "redirect": None,
        # The PIN collects the parcel at a box or a point, so only an admin gets it.
        "pin": api.get_pin(access, waybill) if with_pin else None,
        "pin_hidden": not with_pin,
    }
    if OPERATIONS["change_date"] in codes:
        result["dates"] = api.delivery_dates(access, waybill, token)
    if OPERATIONS["redirect"] in codes:
        req = api.redirect_requirements(access, waybill, token)
        result["redirect"] = {
            "point_types": req.get("allowedPointTypes") or [],
            "services": req.get("requiredServices") or [],
        }
    return result


def _parcel_action(coordinator, data: dict[str, Any]) -> dict[str, Any]:
    api = coordinator.api
    waybill = data["waybill"]
    action = data["action"]
    access = coordinator.access_token()
    codes, token = api.allowed_operations(access, waybill)
    if OPERATIONS[action] not in codes:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="dpd_operation_not_allowed",
            translation_placeholders={"waybill": waybill, "action": action},
        )

    def need(*keys: str) -> None:
        missing = [k for k in keys if not data.get(k)]
        if missing:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="dpd_missing_fields",
                translation_placeholders={"fields": ", ".join(missing)},
            )

    if action == "change_date":
        need("date")
        if data["date"] not in api.delivery_dates(access, waybill, token):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="dpd_date_not_offered",
                translation_placeholders={"date": data["date"]},
            )
        api.change_delivery_date(access, waybill, token, data["date"])
    elif action == "redirect":
        need("point_id")
        req = api.redirect_requirements(access, waybill, token)
        api.redirect_to_point(access, waybill, token, data["point_id"], req)
    elif action == "change_address":
        need("address", "city", "postal_code")
        api.change_delivery_address(
            access, waybill, token, data["address"], data["city"], data["postal_code"], data.get("note", "")
        )
    elif action == "refuse":
        need("reason")
        api.refuse_parcel(access, waybill, token, data["reason"])
    return {"waybill": waybill, "action": action, "done": True}


def _points(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    coordinators = _coordinators(hass)
    if not coordinators:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="dpd_no_account")
    coordinator = _owner(hass, data["waybill"]) if data.get("waybill") else coordinators[0]
    access = coordinator.access_token()
    points = coordinator.api.nearest_points(
        access, data["latitude"], data["longitude"], data["count"], data["radius_km"]
    )
    return {"points": points}


async def _run(hass: HomeAssistant, fn, *args):
    try:
        return await hass.async_add_executor_job(fn, *args)
    except DpdAuthError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="dpd_auth", translation_placeholders={"error": str(err)}
        ) from err
    except DpdError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="dpd_failed", translation_placeholders={"error": str(err)}
        ) from err


def async_register_dpd_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_OPTIONS):
        return

    async def options(call: ServiceCall) -> ServiceResponse:
        coordinator = _owner(hass, call.data["waybill"])
        user = await hass.auth.async_get_user(call.context.user_id) if call.context.user_id else None
        # A call without a user (automation, script) runs as the system and gets the PIN.
        with_pin = user is None or user.is_admin
        return await _run(hass, _parcel_options, coordinator, call.data["waybill"], with_pin)

    async def action(call: ServiceCall) -> ServiceResponse:
        coordinator = _owner(hass, call.data["waybill"])
        result = await _run(hass, _parcel_action, coordinator, dict(call.data))
        await coordinator.async_request_refresh()
        return result

    async def points(call: ServiceCall) -> ServiceResponse:
        return await _run(hass, _points, hass, dict(call.data))

    hass.services.async_register(DOMAIN, SERVICE_OPTIONS, options, OPTIONS_SCHEMA, SupportsResponse.ONLY)
    # Writes change a real delivery, so only an admin may run them (non-admin users
    # such as the wall-panel accounts can still read the options and the points).
    async_register_admin_service(hass, DOMAIN, SERVICE_ACTION, action, ACTION_SCHEMA, SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_POINTS, points, POINTS_SCHEMA, SupportsResponse.ONLY)
