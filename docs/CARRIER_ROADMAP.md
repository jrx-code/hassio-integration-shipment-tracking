# Carrier roadmap

Plan as of 2026-10-01: which carriers to add next, why, and what was ruled out.
Facts carry a source; anything not confirmed is marked *unverified*.
The candidate list came from a multi-model review; every claim it relied on was then
checked against primary sources where they loaded, secondary ones where they did not.

## Where we stand

| Mode | Carriers |
|---|---|
| Account (log in once, parcels appear by themselves) | InPost, DPD Polska, DHL Parcel Polska (Mój DHL), Pocztex |
| Track-by-number (numbers kept in Options) | FedEx, Orlen Paczka, Allegro One |
| Planned | GLS Poland, account mode ([#6](https://github.com/jrx-code/hassio-integration-shipment-tracking/issues/6)) |

The latest UKE courier market report (2025 data, published 2026-05-29, as reported by
logistyka.rp.pl on 2026-06-01) ranks operators:

- by parcel volume: InPost, DPD Polska, Allegro, Orlen Paczka, GLS;
- by revenue: InPost, DPD Polska, GLS, FedEx, UPS; Nova Post is 11th, ahead of DHL eCommerce.

With GLS done, UPS is the only top-five operator in either ranking without a module.

## Priorities

| Priority | Carrier | Mode | Why | Integration path |
|---|---|---|---|---|
| 1 | **UPS** | track-by-number | Top five by revenue (UKE 2025); amazon.pl lists UPS Polska among its carriers | Official Track API, OAuth2 client_credentials with the user's own developer app. Plan in the [README](../README.md#-roadmap) |
| 1 | **DHL by number** | track-by-number | One API for DHL Express, eCommerce and Parcel PL numbers, without an SMS login. Which of these the Mój DHL account module already shows is *unverified* | Official *Shipment Tracking - Unified* API: free, `DHL-API-Key` header, 250 calls/day and at most 1 call per 5 s on the default (development) tier. Its `service` parameter includes `parcel-pl`, `express`, `ecommerce` and `ecommerce-europe` |
| 1 | **GLS Poland** | account | Top five by volume and revenue | [#6](https://github.com/jrx-code/hassio-integration-shipment-tracking/issues/6) |
| 2 | **Aggregator (optional "other carrier")** | track-by-number | AliExpress/Cainiao, Temu, Shein and the long tail: none of them has a consumer tracking API | User's own key. Ship24 is the only aggregator left with a recurring free API tier (see below) |
| 2 | **Nova Post** | unknown | 11th by revenue (UKE 2025); own parcel lockers in Poland per its Polish terms of service (section 4.10.13), recipients collect through the app after logging in with their phone number | Not researched yet. Whether incoming parcels appear in the app by phone number is not stated in the terms |
| 3 | **Ambro Express** | track-by-number | Bulky goods, occasional | Only a SOAP API for business customers with an API key; the public tracking page is a plain HTML form |

### Aggregator pricing (checked 2026-10-01)

| Service | Free API | Paid |
|---|---|---|
| Ship24 | 10 shipments/month, plus 100 in the first month | PRO $39/month for 1,000 shipments, then $0.045 each |
| 17TRACK | One-time 200 numbers for accounts registered after 2026-01-07; the monthly free allocation was discontinued | Prepaid packages |
| AfterShip | No API on the free plan | API from Premium (a 2024 Home Assistant issue cites a $99/month minimum) |
| TrackingMore | No API on the free plan ("API service is only available for paid account") | Not checked |

An aggregator never gives account auto-discovery or a locker pickup code, so it can only sit
next to the native modules, never replace them. Tracking numbers leave the local network.

## Ruled out

| Carrier | Why not |
|---|---|
| Amazon (own fleet) | No evidence of an Amazon last-mile fleet in Poland: amazon.pl's help pages name Poczta Polska, DHL, InPost, UPS and DPD. Those are covered or planned |
| Vinted Go | Runs in FR, NL, BE, ES and PT, not in Poland. Vinted parcels in Poland go through InPost (contract until the end of 2027), GLS, Orlen Paczka, DPD and Poczta Polska |
| Packeta | No own network in Poland: Z-BOX lockers exist only in CZ, SK, HU and RO; Polish deliveries go through InPost, Pocztex PUNKT points and local couriers. Its tracking API is for merchants only |
| Cainiao lockers | Cainiao left the Polish locker network: DHL eCommerce took over APM Solutions, now DHL Box 24/7 (UOKiK approval, October 2025). No official consumer tracking API; parcels go through the aggregator row above |
| X-press Couriers | No longer a separate carrier: part of Allegro One since April 2022, mapped to `ALLEGRO` in Allegro's API since 2024-12-09. Covered by the Allegro One module |
| Geis, Raben | B2B freight, not household parcels |

## Sources

- UKE 2025 ranking: logistyka.rp.pl, 2026-06-01 (full report at bip.uke.gov.pl)
- DHL Shipment Tracking - Unified: <https://developer.dhl.com/api-reference/shipment-tracking>;
  pricing: support-developer.dhl.com, article 47001249492
- UPS: official OpenAPI specs at <https://github.com/UPS-API/api-documentation>
  (`Tracking.yaml`, `OAuthClientCredentials.yaml`)
- Ship24: <https://www.ship24.com/tracking-api>; 17TRACK: <https://api.17track.net/en/doc>;
  AfterShip: [home-assistant/core#106933](https://github.com/home-assistant/core/issues/106933)
- amazon.pl help: delivery and carrier contact pages (read through the search index; the pages
  themselves returned 503)
- Vinted Go markets: logistyka.rp.pl, 2026-01-26; InPost and Vinted: InPost press release, 2025-04-23
- Packeta: <https://www.packeta.pl/zbox>, <https://docs.packeta.com/docs/packet-tracking/tracking>
- Cainiao and APM: wirtualnemedia.pl, 2025-09-22; cashless.pl, 2025-10-10
- Nova Post terms (Poland, valid from 2026-07-17): <https://novapost.com/pl-pl/more/offer/>
- Ambro Express: <https://ambroexpress.pl/nasze-rozwiazania-i-integracje>
- X-press Couriers: developer.allegro.pl news, 2024-12-09
