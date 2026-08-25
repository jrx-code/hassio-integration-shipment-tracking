"""Group ready parcels into pickup groups (multiskrytka-aware).

A *multiskrytka* (multiCompartment) is several parcels the courier stacked
together; the InPost app collects them with one action, so we represent the whole
group by ONE QR — the group *leader*. Verified against the live mobile API
(2026-08-03): every parcel, including multi-compartment members, carries its own
``openCode``/``qrCode`` (``P|+48<phone>|<code>``); the members share
``multiCompartment.uuid`` and exactly one member (the leader) carries the full
``shipmentNumbers`` list — surfaced here as ``multi_count`` being set.

The physical "does the leader QR open every locker" behaviour could NOT be
verified (no live ready multiskrytka at design time), so every member's own code
is kept as a fallback (``member_codes``).

Pure/stdlib only — unit-testable without Home Assistant.
"""
from __future__ import annotations


def pickup_groups(ready: list[dict]) -> list[dict]:
    """Collapse mapped ready parcels (api._map_parcel shape) into pickup groups.

    One group per standalone parcel and one per multiskrytka (keyed by
    ``multi_uuid``). Original ``ready`` order is preserved by each group's first
    appearance. Returns a list of:

        {
          "key": str,               # multi_uuid, else leader shipment number
          "count": int,             # parcels in the group (>1 => multiskrytka)
          "rep": dict,              # representative parcel (leader) — carries QR
          "members": list[dict],    # all parcels in the group (rep included)
        }
    """
    order: list = []          # str uuid (multiskrytka) or dict (standalone)
    by_uuid: dict[str, list[dict]] = {}
    for p in ready:
        uuid = p.get("multi_uuid")
        if uuid:
            if uuid not in by_uuid:
                by_uuid[uuid] = []
                order.append(uuid)
            by_uuid[uuid].append(p)
        else:
            order.append(p)

    groups: list[dict] = []
    for item in order:
        if isinstance(item, str):
            members = by_uuid[item]
            # Leader = the member holding the full shipmentNumbers list
            # (multi_count set); fall back to the first member if none does.
            rep = next((m for m in members if m.get("multi_count")), members[0])
        else:
            members = [item]
            rep = item
        groups.append(
            {
                "key": rep.get("multi_uuid") or rep.get("shipment"),
                "count": len(members),
                "rep": rep,
                "members": members,
            }
        )
    return groups


def group_qr_payload(group: dict) -> str | None:
    """QR payload (``P|+48<phone>|<code>``) for a group's leader, or None.

    Uses the API-provided ``qr`` verbatim (it is exactly the payload we would
    otherwise reconstruct); returns None only if the leader has no QR, in which
    case the slot renders nothing / goes unavailable.
    """
    return (group.get("rep") or {}).get("qr")


def group_qr_data_url(group: dict) -> str | None:
    """Render a group's leader QR to a ``data:image/png;base64,...`` URL.

    For dashboard templates that embed the QR inline (``<img src="{{ p.qr_url }}">``
    / ``![QR]({{ p.qr_url }})``) — the native replacement for the old poller's
    per-parcel ``qr_url``. ~440 B per code, so a handful of groups stays well under
    the recorder's per-state attribute limit.

    BLOCKING (segno render) — call from an executor, never the event loop. segno
    is imported lazily so pickup.py stays importable (and unit-testable) without it.
    """
    payload = group_qr_payload(group)
    if not payload:
        return None
    import base64
    import io

    import segno

    buf = io.BytesIO()
    segno.make(payload, error="m").save(buf, kind="png", scale=6, border=2)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
