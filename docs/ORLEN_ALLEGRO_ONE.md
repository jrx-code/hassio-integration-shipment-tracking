# Orlen Paczka & Allegro One

Added for [issue #1](https://github.com/jrx-code/hassio-integration-shipment-tracking/issues/1).
Configuration mirrors **FedEx**: alias at setup, tracking numbers in **Options**
(comma-separated). No SMS, no OAuth client credentials, no partner secrets.

## Orlen Paczka

### Public JSONP (what this integration uses)

- Endpoint: `https://nadaj.orlenpaczka.pl/parcel/api-status?id={number}&jsonp=callback`
- No authentication. Same consumer track-by-number surface used by orlenpaczka.pl
  (and tools such as jwilk/pacz).
- Live probe 2026-09-18: unknown id → `{"err":1003}`.

### Partner SOAP (not used, by design)

Orlen also exposes a Partner SOAP API (`GiveMePackStatus` and related) that
requires **PartnerID / PartnerKey**. This integration deliberately does **not**
use that path — it would force operators to obtain and store partner secrets
for a use case that public JSONP already covers for track-by-number.

## Allegro One

### Edge tracking endpoint (what this integration uses)

- Endpoint: `GET https://edge.allegro.pl/ad/tracking?packageNo={id}`
- Required headers observed in the wild:
  - `Accept: application/vnd.allegro.internal.v1+json`
  - `Accept-Language: pl-PL`
- Verified live 2026-09-18 against waybill `A000YR4D27` (full PL status history).
- Use Allegro-internal waybills (`A…` / `AD…`). Subcontractor numbers from UPS,
  DPD, Orlen Paczka, etc. belong on those carriers — not here.

### Official Allegro OAuth API (not used, by design)

Allegro publishes an official `api.allegro.pl` carriers / shipments API behind
OAuth. This integration does **not** use it. The public edge endpoint is enough
for track-by-number without registering an Allegro app or storing refresh tokens.

## ⚠️ Terms of use / operational risk (read before production)

**Allegro edge is undocumented / internal.**

- The `Accept: application/vnd.allegro.internal.v1+json` media type is an
  **internal** Allegro content type, not a documented public contract.
- Allegro may change, rate-limit, or remove the edge tracking endpoint **without
  notice** and **without official support**.
- There is **no SLA**, changelog, or support channel for this Accept type.
- By enabling Allegro One in production, **you (the Home Assistant operator)
  accept that risk**: breakage, silent empty results, or auth/header changes
  are expected failure modes. Prefer the official OAuth API if you need a
  supported integration surface (that path is out of scope for this PR).

**Orlen public JSONP** is likewise a consumer web surface, not a partner
contract — more stable in practice than Allegro edge, but still unofficial
for Home Assistant use. Prefer Partner SOAP only if you already have partner
credentials and want a contractual API (not implemented here).

**Neither carrier's official brand assets are vendored** in this PR. Sensors
use Material Design Icons (`mdi:truck-delivery`) until optional badge PNGs are
added under `logos/` following the existing carrier-badge pattern (see
`logos.py` — `AVAILABLE` currently omits `orlen` / `allegro_one`, so
`entity_picture` stays unset and the mdi icon is shown).

## Sensors

Same pattern as FedEx: one **W drodze** sensor with active / delivered
(archive) counts and parcel rows in attributes.

## Tests (no Home Assistant required)

Normalize / status-mapping helpers are pure functions. Stub HA in the test
loaders and run:

```bash
python3 -m pytest tests/test_orlen_normalize.py tests/test_allegro_one_normalize.py -q
```
