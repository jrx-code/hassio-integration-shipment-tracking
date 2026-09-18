# Orlen Paczka & Allegro One

Added for issue #1. Configuration mirrors FedEx: alias at setup, tracking numbers in Options.

## Orlen Paczka

- Public JSONP (no auth): `https://nadaj.orlenpaczka.pl/parcel/api-status?id={number}&jsonp=callback`
- Official SOAP (`GiveMePackStatus`) needs PartnerID/PartnerKey — **not used**
- Add numbers in **Options → tracking numbers** (comma-separated)

## Allegro One

- Public edge (no OAuth): `https://edge.allegro.pl/ad/tracking?packageNo={id}`
- Headers: `Accept: application/vnd.allegro.internal.v1+json`, `Accept-Language: pl-PL`
- Use Allegro-internal waybills (`A…` / `AD…`), not UPS/DPD/Orlen subcontractor numbers
- Undocumented Accept type may change — treat as fragile

## Sensors

Same pattern as FedEx: active / delivered (archive) counts with parcel attributes.

## Tests

```bash
python3 -m pytest tests/test_orlen_normalize.py tests/test_allegro_one_normalize.py -q
```
