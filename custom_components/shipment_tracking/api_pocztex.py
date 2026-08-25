"""Poczta Polska SOAP tracking client (official web service, WS-Security).

Not a reverse-engineered consumer app — this is the documented
``tt.poczta-polska.pl/Sledzenie/services/Sledzenie`` web service, track-by-
number only (no account, no auto-discovery). stdlib urllib + xml.etree only
(blocking — callers run it in an executor). No third-party SOAP client.
"""
from __future__ import annotations

import ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from .const import POCZTEX_SOAP_URL, POCZTEX_WS_PASSWORD, POCZTEX_WS_USER

_NS = {
    "s": "http://schemas.xmlsoap.org/soap/envelope/",
    "ns": "http://sledzenie.pocztapolska.pl",
    "ax21": "http://ws.sledzenie.pocztapolska.pl/xsd",
}

_ENVELOPE = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns="http://sledzenie.pocztapolska.pl" xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
  <soapenv:Header>
    <wsse:Security>
      <wsse:UsernameToken>
        <wsse:Username>{user}</wsse:Username>
        <wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-username-token-profile-1.0#PasswordText">{password}</wsse:Password>
      </wsse:UsernameToken>
    </wsse:Security>
  </soapenv:Header>
  <soapenv:Body>
    <ns:sprawdzPrzesylkePl>
      <ns:numer>{numer}</ns:numer>
    </ns:sprawdzPrzesylkePl>
  </soapenv:Body>
</soapenv:Envelope>"""


class PocztexError(Exception):
    """Any Poczta Polska tracking-service failure."""


def _text(el: ET.Element | None, tag: str) -> str | None:
    if el is None:
        return None
    child = el.find(f"ax21:{tag}", _NS)
    return child.text if child is not None else None


class PocztexApi:
    """Blocking Poczta Polska SOAP client. Auth is a fixed public credential
    (see const.py), so there's no token to mint or refresh per call."""

    def __init__(self) -> None:
        self._ctx: ssl.SSLContext | None = None

    def track(self, numer: str) -> dict:
        """Track one number. Returns a dict with at least ``found`` — False
        means the number doesn't resolve (typo, or not their carrier)."""
        if self._ctx is None:
            self._ctx = ssl.create_default_context()
        body = _ENVELOPE.format(
            user=POCZTEX_WS_USER, password=POCZTEX_WS_PASSWORD, numer=numer
        ).encode()
        req = urllib.request.Request(
            POCZTEX_SOAP_URL,
            data=body,
            headers={"Content-Type": 'text/xml;charset=UTF-8', "SOAPAction": '""'},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=25, context=self._ctx) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            if e.code != 500:  # 500 = SOAP Fault, still parseable below
                raise PocztexError(f"HTTP {e.code}: {raw[:300]!r}") from e
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as err:
            raise PocztexError(f"unparseable response: {err}") from err

        fault = root.find(".//s:Fault", _NS)
        if fault is not None:
            msg = fault.findtext("faultstring") or "SOAP fault"
            raise PocztexError(msg)

        przesylka = root.find(".//ns:return", _NS)
        if przesylka is None:
            raise PocztexError("no <return> in response")

        status = _text(przesylka, "status")
        dane = przesylka.find("ax21:danePrzesylki", _NS)
        found = dane is not None and dane.get(
            "{http://www.w3.org/2001/XMLSchema-instance}nil"
        ) != "true"

        if not found:
            return {"numer": numer, "found": False, "status_code": status}

        events = []
        for z in dane.findall("ax21:zdarzenia/ax21:zdarzenie", _NS):
            events.append(
                {
                    "kod": _text(z, "kod"),
                    "nazwa": _text(z, "nazwa"),
                    "czas": _text(z, "czas"),
                    "konczace": _text(z, "konczace") == "true",
                }
            )
        return {
            "numer": numer,
            "found": True,
            "status_code": status,
            "zakonczono_obsluge": _text(dane, "zakonczonoObsluge") == "true",
            "data_nadania": _text(dane, "dataNadania"),
            "rodzaj_przesylki": _text(dane, "rodzPrzes"),
            "events": events,
        }
