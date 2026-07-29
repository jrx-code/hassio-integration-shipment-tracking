<div align="center">

<img src=".github/assets/hero.svg" alt="InPost for Home Assistant" width="880">

<br>

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jrx-code&repository=hassio-integration-inpost&category=integration)

![HACS Custom](https://img.shields.io/badge/HACS-Custom-FFCD00?style=flat-square)
![Home Assistant](https://img.shields.io/badge/Home_Assistant-2024.1+-18BCF2?style=flat-square&logo=homeassistant&logoColor=white)
![stdlib only](https://img.shields.io/badge/deps-stdlib_only-3776AB?style=flat-square&logo=python&logoColor=white)
![License](https://img.shields.io/github/license/jrx-code/hassio-integration-inpost?style=flat-square&color=FFCD00)
![Made in Poland](https://img.shields.io/badge/made_in-🇵🇱_Poland-white?style=flat-square)

**Track your InPost parcels natively in Home Assistant — ready-to-pickup, in-transit and archive, as first-class entities.**

</div>

---

## ✨ Features

- 📥 **Do odbioru** — how many parcels are ready to pick up, with sender, locker, pickup code, expiry and QR payload in attributes
- 🚚 **W drodze** — parcels on the way, with human-readable Polish statuses
- 🗄️ **Archiwum** — recently delivered / closed parcels (capped, configurable)
- 👥 **Multi-account** — add several InPost numbers, each as its own device
- 🔑 **SMS login, no scraping** — official legacy mobile auth; the refresh token is stored encrypted by HA
- 🧩 **Zero dependencies** — pure Python stdlib (`requirements: []`)
- 🎨 **Native branding** — proper InPost icon in the integrations list

## 📦 Entities (per account)

| Entity | State | Key attributes |
|---|---|---|
| `sensor` · **Do odbioru** | number ready to pick up | `do_odbioru_count`, `w_drodze_count`, `do_odbioru[]` (nadawca, kod odbioru, paczkomat, adres, termin, `qr`), `w_drodze[]` |
| `sensor` · **W drodze** | number in transit | — |
| `sensor` · **Archiwum** | number archived | `archiwum[]` (latest N) |

> The `qr` payload lets a Lovelace card render the compartment-opening QR client-side.

## 🚀 Installation

### HACS (recommended)

1. HACS → **⋮** → *Custom repositories* → add `https://github.com/jrx-code/hassio-integration-inpost` as **Integration** — or just click the **Open in HACS** badge above.
2. Install **InPost Paczkomaty**, then restart Home Assistant.

### Manual

Copy `custom_components/inpost/` into your Home Assistant `config/custom_components/` and restart.

## ⚙️ Configuration

**Settings → Devices & Services → Add Integration → InPost Paczkomaty**

```
1.  Alias        →  e.g. "Peer A"
2.  Prefix       →  dropdown, default +48
3.  Phone        →  9 digits
4.  SMS code     →  6 digits sent to that number
```

When the refresh token expires, Home Assistant starts a re-auth (a fresh SMS). Per-entry **options**: polling interval (default 15 min), archived-parcels cap, ready-to-pickup notification flag.

## 🔧 Under the hood

- **Legacy SMS auth** on the mobile API — no captcha, unlike the OAuth backend (Cloudflare Turnstile).
- **ETag pagination** on `/v4/parcels/tracked` — InPost (ab)uses `ETag`/`If-None-Match` as a page cursor; a naive single GET misses recent parcels.
- Blocking `urllib` client driven from Home Assistant's executor; `304` responses keep the last snapshot.

## ⚠️ Disclaimer

Unofficial integration, not affiliated with or endorsed by InPost. It talks to the InPost mobile API on your behalf using your own account; use it at your own discretion. InPost name and logo belong to their respective owner.

## 📄 License

[MIT](LICENSE) © JI ENGINEERING
