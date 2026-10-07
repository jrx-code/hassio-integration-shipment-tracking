"""Unit tests for DPD status mapping (pure — no Home Assistant).

    python3 -m pytest tests/test_dpd_status.py -q
Raw statuses verified live 2026-08-06: READY_TO_SEND, RECEIVED_FROM_SENDER,
IN_TRANSPORT, RECEIVED_IN_DEPOT, HANDED_OVER_FOR_DELIVERY, DELIVERED.
"""
import importlib.util
from pathlib import Path

_CONST = Path(__file__).resolve().parents[1] / "custom_components" / "shipment_tracking" / "const.py"
_spec = importlib.util.spec_from_file_location("st_const", _CONST)
_c = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_c)


def test_verified_statuses_bucket_correctly():
    cases = {
        "READY_TO_SEND": "created",
        "RECEIVED_FROM_SENDER": "in_transport",
        "IN_TRANSPORT": "in_transport",
        "RECEIVED_IN_DEPOT": "in_transport",
        "HANDED_OVER_FOR_DELIVERY": "handed_out_for_delivery",
        "DELIVERED": "delivered",
    }
    for raw, bucket in cases.items():
        assert _c.dpd_canonical(raw) == bucket, raw


def test_active_vs_terminal():
    assert _c.dpd_is_active("IN_TRANSPORT")
    assert _c.dpd_is_active("HANDED_OVER_FOR_DELIVERY")
    assert not _c.dpd_is_active("DELIVERED")


def test_polish_labels():
    assert _c.dpd_status_pl("HANDED_OVER_FOR_DELIVERY") == "W doręczeniu"
    assert _c.dpd_status_pl("IN_TRANSPORT") == "W transporcie"
    assert _c.dpd_status_pl("DELIVERED") == "Dostarczona"


def test_unknown_and_keyword_fallback():
    assert _c.dpd_canonical("") == "unknown"
    assert _c.dpd_canonical("SOME_RETURN_EVENT") == "returned"
    assert _c.dpd_canonical("ORDER_CANCELLED") == "cancelled"
    assert _c.dpd_canonical("out_for_delivery") == "handed_out_for_delivery"
    assert not _c.dpd_is_active("RETURNED_TO_SENDER")
