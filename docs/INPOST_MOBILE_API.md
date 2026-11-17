# InPost Mobile protocol map

Source: InPost Mobile 4.23.1 (`pl.inpost.inmobile`, versionCode 42301000), decompiled with
jadx 1.5.1 from the APK installed on the owner's phone. Nothing here was captured from other
people's accounts. 304 Retrofit endpoints in 72 interfaces; this file lists the ones the App
Hub InPost app uses and says what stays out and why.

Host: `https://api-inmobile-pl.easypack24.net` (`DEFAULT_BASE`). Auth: `Authorization: Bearer`
from the OAuth2 + PKCE session the integration already holds, plus `X-App-Id: pl.inpost.inmobile`.
Route existence was probed without a token on 2026-11-16: `v2/collect/validate`, `v1/collect/validate`,
`v2/friends`, `v1/returns/tickets` answer 401 (route exists); the generated OpenAPI client under
`/remote-opening/...` answers 404 on this host, so the Retrofit paths below are the live ones.

Verification status: **read** = shape taken from the decompiled model, **live** = answered on a
real account through the integration. Every row is `read` until a live check is written next to it.

## Parcels (`ParcelApi`, `PostParcelApi`)

| Method | Path | Body or query | Notes |
|---|---|---|---|
| GET | `v4/parcels/tracked` | ETag paging | already used by the poller |
| GET | `v4/parcels/tracked/{shipmentNumber}` | header `notification-id` optional | one parcel |
| GET | `v4/parcels/multi/{multiCompartmentUuid}` | | parcels sharing one locker session |
| POST | `v4/parcels/observed` | `{shipmentNumber, parcelType: TRACKED\|SENT}` | track a foreign parcel by number |
| DELETE | `v4/parcels/observed/{shipmentNumber}` | | stop tracking |
| POST | `v4/parcels/properties` | `{shipmentNumber, propertyKey}` | only key found: `EASY_ACCESS_ZONE_PREFERRED` |
| POST | `v4/parcels/shared` | `{parcels:[{shipmentNumber, friendUuids}]}` | already used (share) |
| GET | `v4/parcels/sent` | | parcels the user sends |
| GET | `v4/parcels/sent/{shipmentNumber}` | | one sent parcel, `quickSendCode`, `qrCode` |
| POST | `v4/parcels` | `CreatePostParcelRequest` | create a label, see below |
| POST | `v5/parcels` | same plus `paymentMethod`, `invoice` | paid shipment, not covered |

`CreatePostParcelRequest`: `deliveryType`, `parcelSize`, `price`, `sender{companyName, firstName,
lastName, email, address{postCode, city, province, street, buildingNumber, flatNumber, country,
postOffice}}`, `receiver{companyName, firstName, lastName, email, phoneNumber{prefix, value}}`,
`deliveryPoint{boxMachineName, address{...}}`, `customerReference`, `discountData{coupon, price,
discountValue, priceWithDiscount, freeShipment}`, `destinationCountryCode`, `sourceCountryCode`,
`currency`, `labelFormat`. Answer: `{shipmentNumber, parcelDiscounted}`.

## Opening a locker compartment (`CompartmentApi`, `SendRemoteApi`, `ReturnRemoteApi`)

Three flows share one shape. A **session** is created by `validate`, then the compartment is
opened inside it.

| Flow | validate | open | reopen | closed | confirm / terminate | status |
|---|---|---|---|---|---|---|
| collect | `POST v2/collect/validate` | `v1/collect/compartment/open` | `.../reopen` | `.../closed` | `v1/collect/terminate` | `v1/collect/compartment/status` |
| send | `POST v1/send/validate` | `v1/send/compartment/open` | `.../reopen` | `.../closed` | `v1/send/confirm`, `v1/send/cancel` | `v1/send/compartment/status` |
| return | `POST v1/return/validate` | `v1/return/compartment/open` | `.../reopen` | `.../closed` | `v1/return/confirm`, `v1/return/cancel` | `v1/return/compartment/status` |

- collect validate: `{parcel:{shipmentNumber, openCode, receiverPhoneNumber{prefix,value}}, geoPoint:{latitude, longitude, accuracy}}` -> `{sessionUuid, sessionExpirationTime}`.
- send validate: `{parcel:{shipmentNumber, quickSendCode}, geoPoint, boxMachineName}`.
- open, reopen, closed, terminate: `{sessionUuid}`; return open is `{sessionUuid, parcelSize}`.
- open answer: `{compartment:{name, location:{side, column, row}}, openCompartmentWaitingTime, actionTime, confirmActionTime}`.
- status: `{sessionUuid, expectedStatus: OPENED|CLOSED}` -> `{compartment, status}`.
- claim (`v1/collect/compartment/claim`): `{sessionUuid, shipmentNumbers[]}` takes further parcels of a multi-compartment pickup.

`geoPoint` is the position of the person at the locker. The services take it from the caller
(the Companion app's tracker of the person) and never invent one. The server decides whether the
position is acceptable; whether it checks distance was not observed.

## Friends and sharing (`FriendApi`)

`GET v2/friends` (no trailing slash), `GET v2/friends/{shipmentNumber}` (friends the parcel can go to,
pending invitations, already shared with), `POST v2/friends` `{phoneNumber{prefix,value}, name}` ->
`{status, friendInvitationDetails}`, `PATCH v2/friends/{uuid}` `{name}`, `DELETE v2/friends/{uuid}`,
`POST v2/invitations/validate` `{invitationCode}`, `POST v2/invitations/accept` `{invitationCode, friendName}`.

## Points (`MapApi`)

`GET v4/points/{boxMachineName}`; `GET v4/points` with `relativePoint=lat,lng`, `maxDistance`, `filter`,
`country`, or with `query`, `relativePostCode`, `country`, `perPage`. Point: `name`, `status`, `location`,
`locationDescription`, `openingHours`, `addressDetails`, `pointType`, `location247`.

## Returns (`ReturnsApi`)

`GET v1/returns/tickets`, `GET v1/returns/tickets/{uuid}`, `GET v1/returns/parcels` (returnable parcels),
`GET v1/returns/organizations?query=` and `v2/...`, `GET v1/returns/reasons/{uuid}`, `GET v1/returns/forms/{uuid}`,
`POST v1/returns/parcels/tickets` `{shipmentNumber, orderNumber, organizationUuid, reasonUuid, parcelSize, sender{firstName,
lastName, name, email}, description}`, `POST v1/returns/tickets` (same without `shipmentNumber`, plus `additionalInfo`, `address`,
`contractNumber`, `referrer`, `originalParcelNumber`, `referrerSourceId`), `POST v1/returns/tickets/paid` (not covered).
Ticket: `uuid`, `rma`, `shipmentNumber`, `status`, `returnCode`, `qrCode`, `expiryDate`.

## Notifications, preferences, prices

`GET v3/notifications?type=`, `POST v1/notifications/read` `{notificationIds[]}`, `POST v1/notifications/readAll` `{date}`,
`GET v1/preferences`, `GET/POST v1/preferences/notifications`, `GET v3/prices/parcels?sourceCountryCode=` (country price list and
`expandAvizo{price, time}`).

## Not covered, with the reason

| Function | Endpoint family | Why |
|---|---|---|
| Storage extension (expand avizo) | `v2/orders/expand-avizo` | takes a payment method and invoice; a payment gateway flow, not a plain call |
| Paid send and paid return | `v5/parcels`, `v1/returns/tickets/paid` | same, plus card or BLIK confirmation |
| Cash on delivery, checkout, basket, BLIK, Dotpay | `Basket*`, `Checkout*`, `Payment*`, `CashOnDelivery*` | payments |
| InPost Plus subscriptions, coupons, loyalty (InCoins), shopping | `izi/app/shopping/*`, `Loyalty*`, `Coupon*` | commerce, not parcel handling |
| Bluetooth and NFC opening | SDK in the app | needs the phone next to the locker |
| Registration, profile, company, terms, logout, push token | `Registration*`, `Profile*`, `Company*`, `CloudMessagingApi` | account administration of the mobile client |
| AI chat, voicebot, streaming | `Nimbus*`, `Voicebot*` | assistant of the app |

## Safety rules the services follow

- Writes (`inpost_action`, `inpost_locker`) are admin services, like the DPD writes.
- A locker open needs `confirm: true` and the position of the person; without them the service refuses.
- `dry_run: true` returns the request that would be sent and sends nothing.
- A refresh token is never read outside the integration's own session: a second client using it rotates
  the token and signs Home Assistant out (the DPD case of 2026-11-14).
