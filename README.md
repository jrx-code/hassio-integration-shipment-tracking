# InPost Paczkomaty — Home Assistant integration

Custom integration tracking InPost parcels natively in Home Assistant, via the
legacy SMS-auth mobile API (`api-inmobile-pl.easypack24.net`). One HA device per
InPost account; add multiple accounts as separate config entries.

Ported from the standalone MQTT poller (`private/inpost-poller`) — the verified
API client (SMS auth, ETag pagination, parcel categorisation) is reused as
`api.py`. `requirements: []` — pure stdlib.

## Entities (per account)

| Entity | State | Attributes |
|---|---|---|
| `binary_sensor` — Do odbioru | ON when any parcel is ready | `do_odbioru_count`, `w_drodze_count`, `do_odbioru[]`, `w_drodze[]` |
| `sensor` — Do odbioru | ready count | — |
| `sensor` — W drodze | in-transit count | — |
| `sensor` — Archiwum | archived count | `archiwum[]` (latest N, capped) |

Parcel attributes mirror the MQTT poller's shape (Polish keys, incl. `qr` payload
for a Lovelace-rendered pickup QR), so existing cards port over.

## Setup

Settings → Devices & Services → **Add Integration** → *InPost Paczkomaty*.
Wizard: alias → phone prefix (dropdown, default `+48`) → phone → SMS code.
When the refresh token expires, HA triggers a re-auth (new SMS).

Options (per entry): polling interval (default 15 min), archived-parcels cap,
ready-to-pickup notification flag.

## Install

- **HACS**: add this repo as a custom repository (category: Integration).
- **Manual**: copy `custom_components/inpost/` into your HA `config/custom_components/`.

## Brand icon

`custom_components/inpost/brand/` ships local `icon.png`/`logo.png` (+ `@2x`),
served by HA's `brands` component from the integration directory (no brands-repo
PR needed on HA 2026.x+).

## Status

Work in progress. API client verified live; config flow, coordinator and entities
load cleanly on HA 2026.7.4. End-to-end SMS flow pending live verification.
