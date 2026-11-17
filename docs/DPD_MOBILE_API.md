# DPD Mobile PL: protocol map for the app-hub DPD app

Source: DPD Mobile 2.10.18 (`pl.com.dpd.mobile.app.release`), Retrofit interfaces in
`pl.com.dpd.mobile.app.base.api.models.endpoints` (decompiled 2026-11-14 for
interoperability), plus live checks against the owner's account. Hosts: `dpdsso.dpd.com.pl`
(Keycloak realm `DPD`, client `DPDClientMDU`) and `mobapp.dpd.com.pl` (all `mdu*` services).

## Account model (verified live)

- SMS login = `PUT /api/phone-verifications/{phone}` + `POST /api/users`
  (`PhoneBasedUserRegistrationModel`). It creates a new Keycloak user; the previous
  phone-only user is disabled (`invalid_grant: User disabled`).
- A user with email + password (`PATCH /api/users/current`, model
  `UserEmailAndCredentialUpdateModel`, then `PUT /api/email-verifications/{sub}` and the
  mailed link) is not disabled by a later SMS login, but the phone number and every
  receiver parcel move to the newest SMS user. One phone = one client that sees parcels.
  Decision 2026-11-14: Home Assistant owns the number; the DPD Mobile app is not used.

## Endpoints

| Feature | Method + path | Body / params |
|---|---|---|
| Parcel list | `POST mdupackageservices/api/v1/packages?userContext=RECEIVER` | `{"alias":null,"sent":null}` |
| Parcel detail | `GET mdupackageservices/api/v1/packages/{waybill}` | `userContext` |
| Pickup PIN | `GET mdupackageservices/api/v1/packages/{waybill}/pin` | -> `shipmentPin`, `pinExpiryDate` |
| Alias | `PATCH mdupackageservices/api/v1/packages/{waybill}` | `UpdateAliasRequest` |
| Archive / restore | `POST mdupackageservices/api/v1/package-archive/{waybill}` | |
| Share | `PUT mdupackageservices/api/v1/packages/shared` | `SharePackageRequest` |
| Rating | `POST mdupackageservices/api/v1/packages/{waybill}/evaluations` | |
| Web management link | `GET mdupackageservices/api/v1/packages/{waybill}/management` | -> `link`, `token` |
| Allowed operations | `GET mdupackagemanagementservices/api/v1/parcels/{waybill}/allowed-operations` | `userContext`; response header `X-Validation-Token` |
| Delivery dates | `GET` / `POST .../parcels/{waybill}/delivery-dates` | header `X-Validation-Token`; POST `{deliveryDate:{date}}` |
| Redirect to Pickup point | `GET` / `POST .../parcels/{waybill}/parcel-shop-redirects` | requirements (`allowedPointTypes`, `depotNumber`, `rkRegion`, `udRegion`); POST `pudoId`, `rkRegion`, `udRegion`, `depotNumber` |
| Address change | `POST .../parcels/{waybill}/delivery-address-change` | `address`, `city`, `postalCode`, `deliveryNote` |
| Refuse parcel | `POST .../parcels/{waybill}/refusal` | `refuseReason` |
| Pickup points | `GET mdupudoservices/api/points/nearest`, `/points/like`, `/points` | lat/lon, types, services |
| Favourite points | `mduaccountservices/api/v1/accounts/self/favorite-points[/{pudo_id}]` | |
| Send: supported countries | `GET mdubrokerpackageservices/api/supported-countries` | |
| Send: basket | `POST mdubrokerpackageservices/api/package` | header `X-Authorization-Salesbar`; `PackageOrder` (`sender`, `receiver`, `pickup`, `code`, `amount`) |
| Send: Salesbar token | `mduaccountservices/api/v1/accounts/self/salesbar/{register,regulations,token}` | |
| Send: payment | `POST mdupaymentservices/api/payment` | `PaymentRequest` (`packageId`, `amount`, `channel`, `blikCode`, `returnUrl`) -> `paymentId`, `url` |
| Send: order | `PATCH mdubrokerpackageservices/api/package` | `orderUuid`, `paymentId` |
| Locker parcels | `mdulockerservices/api/v1/lockers/parcels`, `.../{waybill}/confirmations` | status reports after the box opened |
| Locker shipment | `POST mdulockerservices/api/v1/shipment/reserve`, `DELETE .../shipment/enduser` | send from a Pickup Station |
| Locker open data | `GET mduswipboxlockerservices/api/v1/swipbox/data` | opaque blob for the Swipbox Infinity BLE SDK |

## Locker opening

DPD Pickup Stations (Swipbox) open over Bluetooth LE from the phone: the app embeds
`com.swipbox.infinity.ble.sdk`, fetches `swipbox/data` and talks to the box locally, then
reports `RECEIVER_OPEN_COMPARTMENT`. There is no remote-open endpoint, so Home Assistant
cannot open a DPD box from home. The pickup PIN (`/pin`) still works at the box screen.

## Open points

- JSON field naming of request bodies (camelCase in the DTOs; the list responses use
  snake_case), to confirm on the first read-only call of each family.
- Which call returns `X-Validation-Token` (allowed-operations is the first in the flow).
- Write operations (date, redirect, refusal, sending) change a real delivery: each one is
  tested on a real parcel only with the owner's consent.
