"""InPost services for the App Hub InPost app (and automations).

The App Hub app never talks to InPost itself: it calls these services, which run
through the account's coordinator, so the OAuth session, the token rotation and
the 401 retry stay in one place (docs/INPOST_MOBILE_API.md).

- ``inpost_query``: read anything the InPost Mobile app shows (parcel, sent
  parcels, points, friends, returns, notifications, prices). Pickup codes and
  phone numbers are removed from the answer unless an admin asked.
- ``inpost_action``: write one thing (track a parcel, share, friends, returns,
  create a label, mark notifications). Admin only, ``dry_run`` shows the request.
- ``inpost_locker``: open a locker compartment to collect, send or return a
  parcel. Admin only, needs ``confirm: true`` and the position of the person.

Not here on purpose: storage extension and paid sending or returns (payment
gateway), subscriptions and shopping, Bluetooth opening. The list with reasons
is in docs/INPOST_MOBILE_API.md.
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

from .api import InPostError, ReauthRequired
from .const import CARRIER_INPOST, CONF_CARRIER, DOMAIN
from .inpost_management import (
    ACTION_FIELDS,
    FLOWS,
    QUERY_FIELDS,
    Missing,
    act,
    build_action,
    build_locker,
    locker,
    query,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_QUERY = "inpost_query"
SERVICE_ACTION = "inpost_action"
SERVICE_LOCKER = "inpost_locker"

# Removed from `inpost_query` answers unless the caller is an admin: they collect a parcel.
SECRET_KEYS = frozenset({"openCode", "qrCode", "quickSendCode", "returnCode", "phoneNumber"})

LOCKER_STEPS = ["open", "reopen", "closed", "status", "terminate", "claim", "confirm"]

_STR = cv.string
_LIST = vol.All(cv.ensure_list, [cv.string])

QUERY_SCHEMA = vol.Schema(
    {
        vol.Required("what"): vol.In(list(QUERY_FIELDS)),
        vol.Optional("account"): _STR,
        vol.Optional("shipment_number"): _STR,
        vol.Optional("uuid"): _STR,
        vol.Optional("name"): _STR,
        vol.Optional("search"): _STR,
        vol.Optional("post_code"): _STR,
        vol.Optional("latitude"): vol.Coerce(float),
        vol.Optional("longitude"): vol.Coerce(float),
        vol.Optional("max_distance"): vol.Coerce(float),
        vol.Optional("filter"): _STR,
        vol.Optional("country"): _STR,
        vol.Optional("type"): _STR,
        vol.Optional("limit"): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
    }
)

ACTION_SCHEMA = vol.Schema(
    {
        vol.Required("action"): vol.In(list(ACTION_FIELDS)),
        vol.Optional("account"): _STR,
        vol.Optional("dry_run", default=False): cv.boolean,
        vol.Optional("shipment_number"): _STR,
        vol.Optional("shipment_numbers"): _LIST,
        vol.Optional("friend_uuids"): _LIST,
        vol.Optional("notification_ids"): _LIST,
        vol.Optional("uuid"): _STR,
        vol.Optional("name"): _STR,
        vol.Optional("phone"): _STR,
        vol.Optional("phone_prefix"): _STR,
        vol.Optional("invitation_code"): _STR,
        vol.Optional("date"): _STR,
        vol.Optional("parcel_type"): vol.In(["TRACKED", "SENT"]),
        vol.Optional("property_key"): _STR,
        vol.Optional("organization_uuid"): _STR,
        vol.Optional("reason_uuid"): _STR,
        vol.Optional("parcel_size"): vol.In(["A", "B", "C", "S", "M", "L"]),
        vol.Optional("order_number"): _STR,
        vol.Optional("description"): _STR,
        vol.Optional("additional_info"): _STR,
        vol.Optional("sender_name"): _STR,
        vol.Optional("sender_email"): _STR,
        vol.Optional("sender_first_name"): _STR,
        vol.Optional("sender_last_name"): _STR,
        vol.Optional("sender_street"): _STR,
        vol.Optional("sender_building"): _STR,
        vol.Optional("sender_flat"): _STR,
        vol.Optional("sender_post_code"): _STR,
        vol.Optional("sender_city"): _STR,
        vol.Optional("receiver_first_name"): _STR,
        vol.Optional("receiver_last_name"): _STR,
        vol.Optional("receiver_email"): _STR,
        vol.Optional("receiver_phone"): _STR,
        vol.Optional("receiver_phone_prefix"): _STR,
        vol.Optional("delivery_point"): _STR,
        vol.Optional("price"): _STR,
        vol.Optional("reference"): _STR,
        vol.Optional("confirm", default=False): cv.boolean,
    }
)

LOCKER_SCHEMA = vol.Schema(
    {
        vol.Required("flow"): vol.In(list(FLOWS)),
        vol.Required("step"): vol.In(LOCKER_STEPS),
        vol.Optional("account"): _STR,
        vol.Optional("dry_run", default=False): cv.boolean,
        vol.Optional("confirm", default=False): cv.boolean,
        vol.Optional("session"): _STR,
        vol.Optional("shipment_number"): _STR,
        vol.Optional("shipment_numbers"): _LIST,
        vol.Optional("open_code"): _STR,
        vol.Optional("quick_send_code"): _STR,
        vol.Optional("box_machine"): _STR,
        vol.Optional("phone"): _STR,
        vol.Optional("phone_prefix"): _STR,
        vol.Optional("latitude"): vol.Coerce(float),
        vol.Optional("longitude"): vol.Coerce(float),
        vol.Optional("accuracy"): vol.Coerce(float),
        vol.Optional("expected"): vol.In(["OPENED", "CLOSED"]),
        vol.Optional("parcel_size"): _STR,
    }
)


def _coordinators(hass: HomeAssistant) -> list:
    return [
        e.runtime_data
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get(CONF_CARRIER, CARRIER_INPOST) == CARRIER_INPOST
        and e.state is ConfigEntryState.LOADED
        and getattr(e, "runtime_data", None) is not None
    ]


def _parcel(coordinator, number: str) -> dict | None:
    data = coordinator.data or {}
    for key in ("ready", "in_transit", "archived"):
        for row in data.get(key, []):
            if row.get("shipment") == number:
                return row
    return None


def _account(hass: HomeAssistant, data: dict[str, Any]):
    """The coordinator a call runs on: named account, owner of the parcel, or the only one."""
    coordinators = _coordinators(hass)
    if not coordinators:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="inpost_no_account")
    wanted = data.get("account")
    if wanted:
        for c in coordinators:
            entry = c.entry
            if wanted in (entry.entry_id, entry.title, str(entry.data.get("phone", ""))):
                return c
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="inpost_unknown_account",
            translation_placeholders={"account": wanted})
    number = data.get("shipment_number")
    if number:
        for c in coordinators:
            if _parcel(c, number):
                return c
    return coordinators[0]


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in SECRET_KEYS}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _fail(key: str, **placeholders: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN, translation_key=key, translation_placeholders=placeholders)


async def _is_admin(hass: HomeAssistant, call: ServiceCall) -> bool:
    # A call without a user (automation, script) runs as the system.
    user = await hass.auth.async_get_user(call.context.user_id) if call.context.user_id else None
    return user is None or user.is_admin


async def _run(hass: HomeAssistant, coordinator, fn, *args):
    try:
        return await hass.async_add_executor_job(lambda: coordinator._authorized(fn, *args))
    except Missing as err:
        raise _fail("inpost_missing_fields", fields=", ".join(err.fields)) from err
    except ReauthRequired as err:
        raise _fail("inpost_auth", error=str(err)) from err
    except InPostError as err:
        raise _fail("inpost_failed", error=str(err)) from err


def _phone_of(coordinator, row: dict | None) -> str:
    return str((row or {}).get("owner_phone") or coordinator.entry.data.get("phone") or "")


def _split_phone(phone: str) -> tuple[str | None, str]:
    phone = phone.replace(" ", "")
    if phone.startswith("+") and len(phone) > 9:
        return phone[:3], phone[3:]
    return None, phone


def async_register_inpost_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_QUERY):
        return

    async def handle_query(call: ServiceCall) -> ServiceResponse:
        data = dict(call.data)
        coordinator = _account(hass, data)
        result = await _run(
            hass, coordinator, lambda auth: query(coordinator._api, auth, data["what"], data))
        if not await _is_admin(hass, call):
            result = _strip(result)
        return {"what": data["what"], "result": result}

    async def handle_action(call: ServiceCall) -> ServiceResponse:
        data = dict(call.data)
        coordinator = _account(hass, data)
        action = data["action"]
        try:
            method, path, body = build_action(action, data)
        except Missing as err:
            raise _fail("inpost_missing_fields", fields=", ".join(err.fields)) from err
        if data["dry_run"]:
            return {"action": action, "dry_run": True, "request": {"method": method, "path": path, "body": body}}
        if action in ("send_parcel", "return_parcel", "return_organization") and not data["confirm"]:
            raise _fail("inpost_needs_confirm", action=action)
        result = await _run(hass, coordinator, lambda auth: act(coordinator._api, auth, action, data))
        await coordinator.async_request_refresh()
        return {"action": action, "done": True, "result": result}

    async def handle_locker(call: ServiceCall) -> ServiceResponse:
        data = dict(call.data)
        coordinator = _account(hass, data)
        flow, step = data["flow"], data["step"]
        row = _parcel(coordinator, data["shipment_number"]) if data.get("shipment_number") else None
        if flow == "collect" and row:
            data.setdefault("open_code", row.get("open_code"))
            prefix, number = _split_phone(data.get("phone") or _phone_of(coordinator, row))
            data.setdefault("phone", number)
            if prefix:
                data.setdefault("phone_prefix", prefix)
        try:
            validate = build_locker(flow, "validate" if step == "open" and not data.get("session") else step, data)
        except Missing as err:
            raise _fail("inpost_missing_fields", fields=", ".join(err.fields)) from err
        if data["dry_run"]:
            return {"flow": flow, "step": step, "dry_run": True,
                    "request": {"method": validate[0], "path": validate[1], "body": validate[2]}}
        if step == "open" and not data["confirm"]:
            raise _fail("inpost_needs_confirm", action=f"{flow} open")
        result = await _run(hass, coordinator, lambda auth: locker(coordinator._api, auth, flow, step, data))
        await coordinator.async_request_refresh()
        return result

    hass.services.async_register(DOMAIN, SERVICE_QUERY, handle_query, QUERY_SCHEMA, SupportsResponse.ONLY)
    # Writes change real parcels and open real compartments: admin only. Wall-panel
    # accounts can still read (without pickup codes) and see the list.
    async_register_admin_service(hass, DOMAIN, SERVICE_ACTION, handle_action, ACTION_SCHEMA, SupportsResponse.OPTIONAL)
    async_register_admin_service(hass, DOMAIN, SERVICE_LOCKER, handle_locker, LOCKER_SCHEMA, SupportsResponse.OPTIONAL)
