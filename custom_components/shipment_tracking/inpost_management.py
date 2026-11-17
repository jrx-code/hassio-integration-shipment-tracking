"""InPost Mobile functions beyond polling (docs/INPOST_MOBILE_API.md).

Pure, blocking functions: they take an `InPostApi` and a ready `Authorization`
value and return plain dicts. The services in services_inpost.py run them in the
executor through the account's coordinator, so the session, the token rotation
and the 401 retry stay in one place.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .api import InPostApi

EASY_ACCESS_KEY = "EASY_ACCESS_ZONE_PREFERRED"
FLOWS = ("collect", "send", "return")
STEPS = ("open", "reopen", "closed", "status", "terminate", "claim")


class Missing(ValueError):
    """Required fields of an action are absent; `.fields` names them."""

    def __init__(self, fields: list[str]) -> None:
        super().__init__(", ".join(fields))
        self.fields = fields


def need(data: dict[str, Any], *keys: str) -> None:
    missing = [k for k in keys if data.get(k) in (None, "", [])]
    if missing:
        raise Missing(missing)


def _seg(value: Any) -> str:
    return quote(str(value), safe="")


def _phone(prefix: str | None, value: str | None) -> dict[str, str]:
    return {"prefix": prefix or "+48", "value": str(value or "").replace(" ", "")}


# ---------------------------------------------------------------- reads

QUERY_FIELDS: dict[str, tuple[str, ...]] = {
    "parcel": ("shipment_number",),
    "multi_parcel": ("uuid",),
    "sent": (),
    "sent_parcel": ("shipment_number",),
    "point": ("name",),
    "points": (),
    "friends": (),
    "parcel_friends": ("shipment_number",),
    "return_tickets": (),
    "return_ticket": ("uuid",),
    "returnable": (),
    "return_organizations": (),
    "return_reasons": ("uuid",),
    "return_form": ("uuid",),
    "notifications": (),
    "prices": (),
    "preferences": (),
    "notification_preferences": (),
}


def query(api: InPostApi, auth: str, what: str, p: dict[str, Any]) -> Any:
    need(p, *QUERY_FIELDS[what])
    get = lambda path, q=None: api.request("GET", path, auth, query=q)  # noqa: E731
    if what == "parcel":
        return get(f"/v4/parcels/tracked/{_seg(p['shipment_number'])}")
    if what == "multi_parcel":
        return get(f"/v4/parcels/multi/{_seg(p['uuid'])}")
    if what == "sent":
        return get("/v4/parcels/sent")
    if what == "sent_parcel":
        return get(f"/v4/parcels/sent/{_seg(p['shipment_number'])}")
    if what == "point":
        return get(f"/v4/points/{_seg(p['name'])}")
    if what == "points":
        if p.get("latitude") is not None and p.get("longitude") is not None:
            return get("/v4/points", {
                "relativePoint": f"{p['latitude']},{p['longitude']}",
                "maxDistance": p.get("max_distance"),
                "filter": p.get("filter"),
                "country": p.get("country", "PL"),
            })
        need(p, "search")
        return get("/v4/points", {
            "query": p["search"],
            "relativePostCode": p.get("post_code"),
            "filter": p.get("filter"),
            "country": p.get("country", "PL"),
            "perPage": p.get("limit", 20),
        })
    if what == "friends":
        return get("/v2/friends")
    if what == "parcel_friends":
        return get(f"/v2/friends/{_seg(p['shipment_number'])}")
    if what == "return_tickets":
        return get("/v1/returns/tickets")
    if what == "return_ticket":
        return get(f"/v1/returns/tickets/{_seg(p['uuid'])}")
    if what == "returnable":
        return get("/v1/returns/parcels")
    if what == "return_organizations":
        return get("/v2/returns/organizations", {"query": p.get("search", "")})
    if what == "return_reasons":
        return get(f"/v1/returns/reasons/{_seg(p['uuid'])}")
    if what == "return_form":
        return get(f"/v1/returns/forms/{_seg(p['uuid'])}")
    if what == "notifications":
        return get("/v3/notifications", {"type": p.get("type")})
    if what == "prices":
        return get("/v3/prices/parcels", {"sourceCountryCode": p.get("country", "PL")})
    if what == "preferences":
        return get("/v1/preferences")
    return get("/v1/preferences/notifications")


# ---------------------------------------------------------------- writes

ACTION_FIELDS: dict[str, tuple[str, ...]] = {
    "track": ("shipment_number",),
    "untrack": ("shipment_number",),
    "easy_access": ("shipment_number",),
    "share": ("shipment_numbers", "friend_uuids"),
    "friend_invite": ("phone", "name"),
    "friend_rename": ("uuid", "name"),
    "friend_remove": ("uuid",),
    "invitation_validate": ("invitation_code",),
    "invitation_accept": ("invitation_code", "name"),
    "notifications_read": ("notification_ids",),
    "notifications_read_all": ("date",),
    "return_parcel": ("shipment_number", "organization_uuid", "reason_uuid", "parcel_size", "sender_name", "sender_email"),
    "return_organization": ("organization_uuid", "reason_uuid", "parcel_size", "order_number", "sender_name", "sender_email"),
    "send_parcel": (
        "parcel_size", "delivery_point", "receiver_first_name", "receiver_last_name",
        "receiver_email", "receiver_phone", "sender_first_name", "sender_last_name",
        "sender_email", "sender_street", "sender_building", "sender_post_code", "sender_city",
    ),
}


def build_action(what: str, p: dict[str, Any]) -> tuple[str, str, dict | None]:
    """The (method, path, body) an action would send. Pure, so dry_run can show it."""
    need(p, *ACTION_FIELDS[what])
    if what == "track":
        return "POST", "/v4/parcels/observed", {
            "shipmentNumber": p["shipment_number"], "parcelType": p.get("parcel_type", "TRACKED")}
    if what == "untrack":
        return "DELETE", f"/v4/parcels/observed/{_seg(p['shipment_number'])}", None
    if what == "easy_access":
        return "POST", "/v4/parcels/properties", {
            "shipmentNumber": p["shipment_number"], "propertyKey": p.get("property_key", EASY_ACCESS_KEY)}
    if what == "share":
        return "POST", "/v4/parcels/shared", {"parcels": [
            {"shipmentNumber": str(n), "friendUuids": list(p["friend_uuids"])}
            for n in p["shipment_numbers"]]}
    if what == "friend_invite":
        return "POST", "/v2/friends", {
            "phoneNumber": _phone(p.get("phone_prefix"), p["phone"]), "name": p["name"]}
    if what == "friend_rename":
        return "PATCH", f"/v2/friends/{_seg(p['uuid'])}", {"name": p["name"]}
    if what == "friend_remove":
        return "DELETE", f"/v2/friends/{_seg(p['uuid'])}", None
    if what == "invitation_validate":
        return "POST", "/v2/invitations/validate", {"invitationCode": p["invitation_code"]}
    if what == "invitation_accept":
        return "POST", "/v2/invitations/accept", {
            "invitationCode": p["invitation_code"], "friendName": p["name"]}
    if what == "notifications_read":
        return "POST", "/v1/notifications/read", {"notificationIds": list(p["notification_ids"])}
    if what == "notifications_read_all":
        return "POST", "/v1/notifications/readAll", {"date": p["date"]}
    if what in ("return_parcel", "return_organization"):
        body = {
            "organizationUuid": p["organization_uuid"],
            "reasonUuid": p["reason_uuid"],
            "parcelSize": p["parcel_size"],
            "sender": {"name": p["sender_name"], "email": p["sender_email"]},
            "description": p.get("description", ""),
            "orderNumber": p.get("order_number"),
        }
        if what == "return_parcel":
            body["shipmentNumber"] = p["shipment_number"]
            return "POST", "/v1/returns/parcels/tickets", body
        body["additionalInfo"] = p.get("additional_info")
        return "POST", "/v1/returns/tickets", body
    # send_parcel
    return "POST", "/v4/parcels", {
        "deliveryType": p.get("delivery_type", "parcel_locker"),
        "parcelSize": p["parcel_size"],
        "price": p.get("price", "0.00"),
        "sender": {
            "firstName": p["sender_first_name"], "lastName": p["sender_last_name"],
            "email": p["sender_email"],
            "address": {
                "street": p["sender_street"], "buildingNumber": p["sender_building"],
                "flatNumber": p.get("sender_flat"), "postCode": p["sender_post_code"],
                "city": p["sender_city"], "country": p.get("sender_country", "PL"),
            },
        },
        "receiver": {
            "firstName": p["receiver_first_name"], "lastName": p["receiver_last_name"],
            "email": p["receiver_email"],
            "phoneNumber": _phone(p.get("receiver_phone_prefix"), p["receiver_phone"]),
        },
        "deliveryPoint": {"boxMachineName": p["delivery_point"]},
        "customerReference": p.get("reference"),
        "destinationCountryCode": p.get("destination_country", "PL"),
        "sourceCountryCode": p.get("source_country", "PL"),
        "currency": p.get("currency", "PLN"),
        "labelFormat": p.get("label_format", "Pdf"),
    }


def act(api: InPostApi, auth: str, what: str, p: dict[str, Any]) -> Any:
    method, path, body = build_action(what, p)
    return api.request(method, path, auth, body=body)


# ---------------------------------------------------------------- lockers

def build_locker(flow: str, step: str, p: dict[str, Any]) -> tuple[str, str, dict]:
    """The (method, path, body) of one locker step.

    `open` on `collect` and `send` is two calls (validate, then open); that case
    is handled in `locker`, this function only describes a single request.
    """
    if step == "validate":
        if flow == "collect":
            need(p, "shipment_number", "open_code", "phone", "latitude", "longitude")
            return "POST", "/v2/collect/validate", {
                "parcel": {
                    "shipmentNumber": p["shipment_number"], "openCode": str(p["open_code"]),
                    "receiverPhoneNumber": _phone(p.get("phone_prefix"), p["phone"]),
                },
                "geoPoint": _geo(p),
            }
        if flow == "send":
            need(p, "shipment_number", "quick_send_code", "box_machine", "latitude", "longitude")
            return "POST", "/v1/send/validate", {
                "parcel": {"shipmentNumber": p["shipment_number"], "quickSendCode": str(p["quick_send_code"])},
                "geoPoint": _geo(p),
                "boxMachineName": p["box_machine"],
            }
        need(p, "shipment_number", "latitude", "longitude")
        return "POST", "/v1/return/validate", {
            "parcel": {"shipmentNumber": p["shipment_number"]}, "geoPoint": _geo(p)}
    need(p, "session")
    body: dict[str, Any] = {"sessionUuid": p["session"]}
    if step == "status":
        need(p, "expected")
        body["expectedStatus"] = p["expected"]
        return "POST", f"/v1/{flow}/compartment/status", body
    if step == "claim":
        need(p, "shipment_numbers")
        body["shipmentNumbers"] = list(p["shipment_numbers"])
        return "POST", "/v1/collect/compartment/claim", body
    if step == "terminate":
        return "POST", {"collect": "/v1/collect/terminate", "send": "/v1/send/cancel",
                        "return": "/v1/return/cancel"}[flow], body
    if step == "confirm":
        return "POST", f"/v1/{flow}/confirm", body
    if step == "open" and flow == "return":
        need(p, "parcel_size")
        body["parcelSize"] = p["parcel_size"]
    return "POST", f"/v1/{flow}/compartment/{step}", body


def _geo(p: dict[str, Any]) -> dict[str, float]:
    return {"latitude": float(p["latitude"]), "longitude": float(p["longitude"]),
            "accuracy": float(p.get("accuracy", 20.0))}


def locker(api: InPostApi, auth: str, flow: str, step: str, p: dict[str, Any]) -> dict[str, Any]:
    """Run one locker step. `open` without a session validates first."""
    result: dict[str, Any] = {"flow": flow, "step": step}
    q = dict(p)
    if step == "open" and not q.get("session"):
        method, path, body = build_locker(flow, "validate", q)
        v = api.request(method, path, auth, body=body)
        q["session"] = v.get("sessionUuid")
        result["session"] = q["session"]
        result["session_expires"] = v.get("sessionExpirationTime")
    method, path, body = build_locker(flow, step, q)
    result["answer"] = api.request(method, path, auth, body=body)
    result.setdefault("session", q.get("session"))
    return result
