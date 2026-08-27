<div align="center">

<img src=".github/assets/hero.svg" alt="Shipment Tracking for Home Assistant" width="880">

<br>

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jrx-code&repository=hassio-integration-shipment-tracking&category=integration)

![HACS Custom](https://img.shields.io/badge/HACS-Custom-FFCD00?style=flat-square)
![Home Assistant](https://img.shields.io/badge/Home_Assistant-2024.1+-18BCF2?style=flat-square&logo=homeassistant&logoColor=white)
![deps: segno](https://img.shields.io/badge/deps-segno-3776AB?style=flat-square&logo=python&logoColor=white)
![License](https://img.shields.io/github/license/jrx-code/hassio-integration-shipment-tracking?style=flat-square&color=FFCD00)
![Made in Poland](https://img.shields.io/badge/made_in-🇵🇱_Poland-white?style=flat-square)

**Track your parcels natively in Home Assistant — InPost, DPD, FedEx, Pocztex and DHL today, more carriers planned — ready-to-pickup, in-transit and archive, as first-class entities.**

</div>

---

## ✨ Features

- 📥 **Do odbioru** (InPost) — how many parcels are ready to pick up, with sender, locker, pickup code, expiry and QR payload in attributes
- 🚚 **W drodze** (both carriers) — parcels on the way, with human-readable Polish statuses
- 🗄️ **Archiwum / dostarczone** — recently delivered / closed parcels (capped, configurable)
- 👥 **Multi-account** — add several accounts per carrier, each as its own device
- 🤝 **App-to-app sharing** (InPost only) — hand a ready parcel to another configured InPost account (a paired "friend"), on a button press or automatically
- 🔑 **Official mobile/web auth, no scraping** — InPost/DPD/DHL use SMS login (DHL's stores a session-cookie snapshot instead of a refresh token, verified to survive a real sliding 30-min window). Pocztex is the exception: its Keycloak session has a hard 30-minute cap that no amount of refreshing can extend, so its config entry stores the account password and re-logs-in every poll instead
- 🧩 **Almost dependency-free** — stdlib `urllib` client for both carriers; the only requirement is `segno`, for rendering InPost pickup QR codes
- 🎯 **One framework, one entity shape per carrier** — adding a new carrier module doesn't touch the others

## 📦 Entities

### InPost (per account)

| Entity | State | Key attributes |
|---|---|---|
| `sensor` · **Do odbioru** | number ready to pick up — **own + shared with me** | `do_odbioru_count`, `w_drodze_count`, `do_odbioru[]` (nadawca, kod odbioru, paczkomat, adres, termin, `qr`), `w_drodze[]` |
| `sensor` · **W drodze** | number in transit — **own parcels only** | — |
| `sensor` · **Udostępnione** | active parcels **shared with this account** by someone else | `udostepnione[]` (numer, nadawca, status, `od`, kod odbioru, paczkomat, `podglad`), `moje_udostepnione[]` (the other direction, with `dla`), both `_count`s |
| `sensor` · **Archiwum** | number archived | `archiwum[]` (latest N) |
| `image` · **QR do odbioru** (×6 slots) | pickup QR per group (multiskrytka collapses to one) | — |

> The `qr` payload lets a Lovelace card render the compartment-opening QR client-side.
> Each `do_odbioru[]` row also reports its sharing state: `wlasciciel` (`OWN` /
> `FRIEND` / `OBSERVED`), `udostepniona_do` and `mozna_udostepnic`.

### DPD (per account)

| Entity | State | Key attributes |
|---|---|---|
| `sensor` · **W drodze** | number of active (not yet delivered) parcels | `active_count`, `delivered_count`, `w_drodze[]` (numer, nadawca, status, aktualizacja), `dostarczone[]` (latest N) |

### DHL (per account)

| Entity | State | Key attributes |
|---|---|---|
| `sensor` · **W drodze** | number of active (not yet delivered) parcels — own plus parcels shared to this account | `active_count`, `delivered_count`, `w_drodze[]` (numer, nadawca, status, aktualizacja, udostepniona), `dostarczone[]` (latest N) |

Only one canonical status is confirmed live (`TT_DOR` → "Dostarczona") — the
research account had a single, already-delivered parcel. Any other status
code shows up as its raw DHL string rather than a guessed translation; see
`const.py`'s DHL section.

### FedEx (per configured tracking-number list)

| Entity | State | Key attributes |
|---|---|---|
| `sensor` · **W drodze** | number of active (not yet delivered) tracking numbers | `active_count`, `delivered_count`, `w_drodze[]` (numer, status, nadawca_miasto, nadawca_kraj, usluga), `dostarczone[]` (latest N) |

No auto-discovery — FedEx's official Track API is track-by-number only, so
the tracked numbers are a manually maintained list in this entry's
**options**, not an account. A number stays tracked (and counted) whether
delivered or not until removed from that list.

### Pocztex (per account)

| Entity | State | Key attributes |
|---|---|---|
| `sensor` · **W drodze** | number of active (not yet delivered) parcels | `active_count`, `delivered_count`, `w_drodze[]` (numer, status, postep, aktualizacja), `dostarczone[]` (latest N) |

Poczta Polska's own `state` field is already a Polish label — shown as-is,
no canonical-status mapping needed. `postep` is the raw 0-100 progress
percentage the API returns; anything under 100 counts as active.

## 🤝 Sharing a parcel with another account (InPost only)

Configure two InPost accounts and each device gains one entity per *other*
InPost account:

| Entity | What it does |
|---|---|
| `button` · **Udostępnij → \<alias\>** | shares every active parcel not already shared with that account |
| `switch` · **Auto-udostępnianie → \<alias\>** | keeps doing it for each new parcel, on every poll |

Sharing covers **every active parcel, in transit included** — InPost allows it
long before the parcel reaches the locker, so the peer follows the whole journey
and gets the pickup code the moment it exists.

The recipient's account then lists those parcels normally — including pickup code
and QR — so their sensors, QR image entities and cards need no extra wiring.

The three InPost counters are designed not to overlap, so two mirrored accounts
never report the same parcel twice:

```
Do odbioru    = own ready      + shared-with-me ready
W drodze      = own in transit
Udostępnione  = shared with me, active
```

Prerequisites and limits:

- The two InPost accounts must already be **paired in the InPost mobile app**
  (Settings → *Sparuj użytkownika*, invitation code). Pairing cannot be done over
  this API; until it is done, both entities stay *unavailable*.
- InPost decides per parcel whether sharing is allowed (`operations.canShareParcel`);
  parcels it refuses are skipped.
- **Sharing is not undone here.** Turning the switch off stops new shares; it does
  not withdraw parcels already shared. Withdrawing is an app-side action.
- Adding a further account needs no manual step: the new one gets its sharing
  entities straight away, and every already-running account is reloaded once so
  it gains the entities aimed at the newcomer. Removing an account takes those
  entities back from its peers the same way.
- DPD has no equivalent app-to-app sharing API — the button/switch entities
  only ever appear on InPost devices.

## 🚀 Installation

### HACS (recommended)

1. HACS → **⋮** → *Custom repositories* → add `https://github.com/jrx-code/hassio-integration-shipment-tracking` as **Integration** — or just click the **Open in HACS** badge above.
2. Install **Shipment Tracking (InPost, DPD, FedEx, Pocztex, DHL)**, then restart Home Assistant.

### Manual

Copy `custom_components/shipment_tracking/` into your Home Assistant `config/custom_components/` and restart.

## ⚙️ Configuration

**Settings → Devices & Services → Add Integration → Shipment Tracking**, then pick a carrier:

```
InPost:
1.  Alias        →  e.g. "Home"
2.  Prefix       →  dropdown, default +48
3.  Phone        →  9 digits
4.  SMS code     →  6 digits sent to that number

DPD:
1.  Alias        →  optional
2.  Phone        →  9 digits
3.  SMS code     →  sent to that number (DPD Mobile)

DHL:
1.  Alias        →  optional
2.  Phone        →  9 digits
3.  SMS code     →  sent to that number (Mój DHL)

FedEx:
1.  Alias           →  optional
2.  API Key          →  Client ID from a project in your FedEx developer org
3.  Secret Key       →  Client Secret
4.  Account number   →  optional, informational
    (tracking numbers are added afterwards, in Options)

Pocztex:
1.  Alias        →  optional
2.  E-mail       →  existing Pocztex Mobile account (app-only registration)
3.  Password
```

When a session expires, Home Assistant starts a re-auth for that carrier —
a fresh SMS for InPost/DPD/DHL, the password form again for Pocztex. Per-entry
**options**: polling interval (default 15 min), archived/delivered-parcels
cap; FedEx additionally has its tracking-number list there, InPost an
ignored-shipment-numbers list (hides a stuck/zombie record InPost's own app
stopped showing — see [Entities](#-entities) above).

## 🔧 Under the hood

- **Legacy SMS auth** on InPost's mobile API — no captcha, unlike the OAuth backend (Cloudflare Turnstile).
- **DPD SMS auth** via Keycloak (`dpdsso.dpd.com.pl`, realm `DPD`) against the DPD Mobile PL backend — not the GEOPOST myDPD/email+password platform.
- **DHL SMS auth** behind an Altcha proof-of-work captcha, solved client-side (brute-force `SHA-256(salt+n)==challenge`, a fraction of a second — not an image to click through). Session lives in httpOnly cookies set at login, refreshed with a genuine sliding 30-minute window on every poll.
- **Pocztex email+password auth** via Keycloak authorization_code+PKCE (`idm.pocztex.pl`, realm `ppsa`) — direct password grant is disabled for this client, so it drives the same browser-less PKCE dance a login page would. Its session has a hard, non-sliding 30-minute cap: refreshing a token doesn't extend it, so this carrier re-logs-in every poll instead (the config entry stores the account password for that, not just a refresh token).
- **FedEx** uses the official `developer.fedex.com` Track API (OAuth2 client_credentials) — the one carrier here that isn't a reverse-engineered consumer app.
- **ETag pagination** on InPost's `/v4/parcels/tracked` — InPost (ab)uses `ETag`/`If-None-Match` as a page cursor; a naive single GET misses recent parcels.
- Blocking `urllib` clients for every carrier, driven from Home Assistant's executor; InPost `304` responses keep the last snapshot.
- Every carrier's unique_ids and device identifiers are carrier-prefixed
  (`inpost_<phone>_...`, `dpd_<phone>_...`, `dhl_<entry_id>_...`, ...) so the
  same phone number used on two carriers never collides.

## ⚠️ Disclaimer

Unofficial integration, not affiliated with or endorsed by InPost, DPD, FedEx, DHL, or Poczta Polska/Pocztex. For InPost/DPD/Pocztex/DHL it talks to each carrier's consumer mobile/web API on your behalf using your own account; FedEx uses their official, documented developer API instead. Use it at your own discretion. All carrier names and logos belong to their respective owners.

## 📄 License

[MIT](LICENSE) © JI ENGINEERING
