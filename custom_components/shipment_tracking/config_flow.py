"""Config & options flow for Śledzenie przesyłek (InPost, DPD, FedEx, Pocztex)."""
from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import InPostApi, InPostError
from .api_dhl import DhlApi, DhlAuthError, DhlError
from .api_dpd import DpdApi, DpdError, normalize_phone
from .api_fedex import FedexApi, FedexError
from .api_pocztex import PocztexApi, PocztexAuthError, PocztexError
from .const import (
    CARRIER_DHL,
    CARRIER_DPD,
    CARRIER_FEDEX,
    CARRIER_INPOST,
    CARRIER_LABELS,
    CARRIER_POCZTEX,
    CARRIERS,
    CONF_ACCOUNT_NUMBER,
    CONF_ALIAS,
    CONF_ARCHIVE_LIMIT,
    CONF_CARRIER,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_COOKIES,
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_IGNORED_SHIPMENTS,
    CONF_NOTIFY,
    CONF_PHONE,
    CONF_PREFIX,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_TRACKING_NUMBERS,
    DEFAULT_ARCHIVE_LIMIT,
    DEFAULT_BASE,
    DEFAULT_UA,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Common phone prefixes (InPost); dropdown defaulting to +48, custom allowed.
PREFIX_OPTIONS = ["+48", "+49", "+44", "+420", "+421", "+380", "+31", "+33"]


def _inpost_api() -> InPostApi:
    return InPostApi(DEFAULT_BASE, DEFAULT_UA)


class ShipmentConfigFlow(ConfigFlow, domain=DOMAIN):
    """Carrier select → per-carrier SMS onboarding."""

    VERSION = 1

    def __init__(self) -> None:
        self._carrier: str = CARRIER_INPOST
        self._alias: str = ""
        self._prefix: str = "+48"
        self._phone: str = ""
        self._reauth_entry: ConfigEntry | None = None
        self._dpd: DpdApi | None = None
        self._dhl: DhlApi | None = None
        self._email: str = ""

    # ------------------------- carrier select -------------------------
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._carrier = user_input[CONF_CARRIER]
            if self._carrier == CARRIER_DPD:
                return await self.async_step_dpd()
            if self._carrier == CARRIER_FEDEX:
                return await self.async_step_fedex()
            if self._carrier == CARRIER_POCZTEX:
                return await self.async_step_pocztex()
            if self._carrier == CARRIER_DHL:
                return await self.async_step_dhl()
            return await self.async_step_inpost()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CARRIER, default=CARRIER_INPOST): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": c, "label": CARRIER_LABELS[c]} for c in CARRIERS
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    # ----------------------------- InPost -----------------------------
    async def async_step_inpost(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._alias = user_input[CONF_ALIAS].strip()
            self._prefix = user_input[CONF_PREFIX].strip() or "+48"
            self._phone = user_input[CONF_PHONE].strip()
            if not (self._phone.isdigit() and len(self._phone) == 9):
                errors["base"] = "invalid_phone"
            else:
                await self.async_set_unique_id(f"inpost_{self._phone}")
                self._abort_if_unique_id_configured()
                try:
                    ok = await self.hass.async_add_executor_job(
                        _inpost_api().send_sms, self._prefix, self._phone
                    )
                except InPostError as err:
                    _LOGGER.error("InPost send_sms failed: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    if ok:
                        return await self.async_step_sms()
                    errors["base"] = "sms_rejected"

        return self.async_show_form(
            step_id="inpost",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ALIAS): str,
                    vol.Required(
                        CONF_PREFIX, default=self._prefix or "+48"
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=PREFIX_OPTIONS,
                            mode=SelectSelectorMode.DROPDOWN,
                            custom_value=True,
                        )
                    ),
                    vol.Required(CONF_PHONE): str,
                }
            ),
            errors=errors,
        )

    async def async_step_sms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            code = str(user_input["code"]).strip()
            try:
                _at, refresh_token = await self.hass.async_add_executor_job(
                    _inpost_api().verify_sms, code, self._prefix, self._phone
                )
            except InPostError as err:
                _LOGGER.warning("InPost verify_sms failed: %s", err)
                errors["base"] = "invalid_code"
            else:
                data = {
                    CONF_CARRIER: CARRIER_INPOST,
                    CONF_ALIAS: self._alias,
                    CONF_PREFIX: self._prefix,
                    CONF_PHONE: self._phone,
                    CONF_REFRESH_TOKEN: refresh_token,
                }
                if self._reauth_entry is not None:
                    return self.async_update_reload_and_abort(self._reauth_entry, data=data)
                return self.async_create_entry(title=f"InPost — {self._alias}", data=data)

        return self.async_show_form(
            step_id="sms",
            data_schema=vol.Schema({vol.Required("code"): str}),
            errors=errors,
            description_placeholders={"phone": f"+{self._prefix.lstrip('+')} {self._phone}"},
        )

    # ------------------------------ DPD -------------------------------
    async def async_step_dpd(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._alias = (user_input.get(CONF_ALIAS) or "").strip()
            self._phone = normalize_phone(user_input[CONF_PHONE])
            if not (self._phone.isdigit() and len(self._phone) == 9):
                errors["base"] = "invalid_phone"
            else:
                if self._reauth_entry is None:
                    await self.async_set_unique_id(f"dpd_{self._phone}")
                    self._abort_if_unique_id_configured()
                self._dpd = DpdApi()
                try:
                    ok = await self.hass.async_add_executor_job(
                        self._dpd.send_sms, self._phone
                    )
                except DpdError as err:
                    _LOGGER.error("DPD send_sms failed: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    if ok:
                        return await self.async_step_dpd_sms()
                    errors["base"] = "sms_rejected"

        return self.async_show_form(
            step_id="dpd",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_ALIAS, default=self._alias): str,
                    vol.Required(CONF_PHONE, default=self._phone): str,
                }
            ),
            errors=errors,
        )

    async def async_step_dpd_sms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            code = str(user_input["code"]).strip()
            assert self._dpd is not None
            try:
                _access, refresh_token = await self.hass.async_add_executor_job(
                    self._dpd.register, self._phone, code
                )
            except DpdError as err:
                _LOGGER.warning("DPD register failed: %s", err)
                errors["base"] = "invalid_code"
            else:
                alias = self._alias or self._phone
                data = {
                    CONF_CARRIER: CARRIER_DPD,
                    CONF_ALIAS: alias,
                    CONF_PHONE: self._phone,
                    CONF_REFRESH_TOKEN: refresh_token,
                }
                if self._reauth_entry is not None:
                    return self.async_update_reload_and_abort(self._reauth_entry, data=data)
                return self.async_create_entry(title=f"DPD — {alias}", data=data)

        return self.async_show_form(
            step_id="dpd_sms",
            data_schema=vol.Schema({vol.Required("code"): str}),
            errors=errors,
            description_placeholders={"phone": f"+48 {self._phone}"},
        )

    # ----------------------------- FedEx ------------------------------
    async def async_step_fedex(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Client ID/Secret only — official OAuth2 API, no SMS step.

        Validated by actually minting an access token, not just format
        checks: a typo'd secret should fail here, not silently at first poll.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            self._alias = user_input[CONF_ALIAS].strip()
            client_id = user_input[CONF_CLIENT_ID].strip()
            client_secret = user_input[CONF_CLIENT_SECRET].strip()
            account_number = user_input.get(CONF_ACCOUNT_NUMBER, "").strip()
            try:
                await self.hass.async_add_executor_job(
                    FedexApi(client_id, client_secret).get_access_token
                )
            except FedexError as err:
                _LOGGER.warning("FedEx OAuth validation failed: %s", err)
                errors["base"] = "invalid_auth"
            else:
                await self.async_set_unique_id(f"fedex_{client_id}")
                self._abort_if_unique_id_configured()
                data = {
                    CONF_CARRIER: CARRIER_FEDEX,
                    CONF_ALIAS: self._alias or "FedEx",
                    CONF_CLIENT_ID: client_id,
                    CONF_CLIENT_SECRET: client_secret,
                    CONF_ACCOUNT_NUMBER: account_number,
                }
                return self.async_create_entry(
                    title=f"FedEx — {self._alias or account_number or client_id[:8]}",
                    data=data,
                )

        return self.async_show_form(
            step_id="fedex",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_ALIAS): str,
                    vol.Required(CONF_CLIENT_ID): str,
                    vol.Required(CONF_CLIENT_SECRET): str,
                    vol.Optional(CONF_ACCOUNT_NUMBER, default=""): str,
                }
            ),
            errors=errors,
        )

    # ---------------------------- Pocztex ------------------------------
    async def async_step_pocztex(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Email+password, existing Pocztex Mobile account required —
        registration is app-only, this integration can't create one.
        Validated by actually logging in (full Keycloak PKCE flow).

        CHANGED 2026-08-26: the password is now stored in entry.data
        alongside the refresh_token (found live: this Keycloak client's
        session has a hard, non-extendable 30 min lifetime — decoded JWTs
        show refresh() mints a token with a genuinely new jti each call,
        but iat/exp stay pinned to the ORIGINAL login regardless, so no
        amount of refreshing avoids reauth). The coordinator re-logs-in
        with the stored password well inside that window instead of
        relying on refresh() to extend a session it structurally can't
        extend. Same storage trust level entry.data already has for every
        other carrier's refresh_token — not a new exposure, config entries
        aren't otherwise encrypted at rest."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._alias = user_input.get(CONF_ALIAS, "").strip()
            self._email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]
            try:
                _access, refresh_token = await self.hass.async_add_executor_job(
                    PocztexApi().login, self._email, password
                )
            except PocztexAuthError as err:
                _LOGGER.warning("Pocztex login rejected: %s", err)
                errors["base"] = "invalid_auth"
            except PocztexError as err:
                _LOGGER.error("Pocztex login failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                if self._reauth_entry is None:
                    await self.async_set_unique_id(f"pocztex_{self._email.lower()}")
                    self._abort_if_unique_id_configured()
                data = {
                    CONF_CARRIER: CARRIER_POCZTEX,
                    CONF_ALIAS: self._alias or self._email,
                    CONF_EMAIL: self._email,
                    CONF_PASSWORD: password,
                    CONF_REFRESH_TOKEN: refresh_token,
                }
                if self._reauth_entry is not None:
                    return self.async_update_reload_and_abort(self._reauth_entry, data=data)
                return self.async_create_entry(
                    title=f"Pocztex — {self._alias or self._email}", data=data
                )

        return self.async_show_form(
            step_id="pocztex",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_ALIAS, default=self._alias): str,
                    vol.Required(CONF_EMAIL, default=self._email): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    # ------------------------------ DHL --------------------------------
    async def async_step_dhl(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._alias = (user_input.get(CONF_ALIAS) or "").strip()
            self._phone = normalize_phone(user_input[CONF_PHONE])
            if not (self._phone.isdigit() and len(self._phone) == 9):
                errors["base"] = "invalid_phone"
            else:
                if self._reauth_entry is None:
                    await self.async_set_unique_id(f"dhl_{self._phone}")
                    self._abort_if_unique_id_configured()
                self._dhl = DhlApi()
                try:
                    ok = await self.hass.async_add_executor_job(
                        self._dhl.send_sms, self._phone
                    )
                except DhlError as err:
                    _LOGGER.error("DHL send_sms failed: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    if ok:
                        return await self.async_step_dhl_sms()
                    errors["base"] = "sms_rejected"

        return self.async_show_form(
            step_id="dhl",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_ALIAS, default=self._alias): str,
                    vol.Required(CONF_PHONE, default=self._phone): str,
                }
            ),
            errors=errors,
        )

    async def async_step_dhl_sms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            code = str(user_input["code"]).strip()
            assert self._dhl is not None
            device_id = str(uuid.uuid4())
            try:
                await self.hass.async_add_executor_job(
                    self._dhl.verify_sms, self._phone, code, device_id, "Home Assistant"
                )
            except DhlAuthError as err:
                _LOGGER.warning("DHL verify_sms failed: %s", err)
                errors["base"] = "invalid_code"
            else:
                alias = self._alias or self._phone
                data = {
                    CONF_CARRIER: CARRIER_DHL,
                    CONF_ALIAS: alias,
                    CONF_PHONE: self._phone,
                    CONF_DEVICE_ID: device_id,
                    CONF_COOKIES: self._dhl.export_cookies(),
                }
                if self._reauth_entry is not None:
                    return self.async_update_reload_and_abort(self._reauth_entry, data=data)
                return self.async_create_entry(title=f"DHL — {alias}", data=data)

        return self.async_show_form(
            step_id="dhl_sms",
            data_schema=vol.Schema({vol.Required("code"): str}),
            errors=errors,
            description_placeholders={"phone": f"+48 {self._phone}"},
        )

    # ------------------------------ reauth ----------------------------
    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        self._carrier = entry_data.get(CONF_CARRIER, CARRIER_INPOST)
        self._alias = entry_data.get(CONF_ALIAS, "")
        self._prefix = entry_data.get(CONF_PREFIX, "+48")
        self._phone = entry_data.get(CONF_PHONE, "")
        if self._carrier == CARRIER_POCZTEX:
            # No SMS-resend equivalent — just re-show the login form with
            # the email prefilled, same step as initial setup.
            self._email = entry_data.get(CONF_EMAIL, "")
            return await self.async_step_pocztex()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                if self._carrier == CARRIER_DPD:
                    self._dpd = DpdApi()
                    ok = await self.hass.async_add_executor_job(
                        self._dpd.send_sms, self._phone
                    )
                    if ok:
                        return await self.async_step_dpd_sms()
                elif self._carrier == CARRIER_DHL:
                    self._dhl = DhlApi()
                    ok = await self.hass.async_add_executor_job(
                        self._dhl.send_sms, self._phone
                    )
                    if ok:
                        return await self.async_step_dhl_sms()
                else:
                    ok = await self.hass.async_add_executor_job(
                        _inpost_api().send_sms, self._prefix, self._phone
                    )
                    if ok:
                        return await self.async_step_sms()
            except (InPostError, DpdError, DhlError) as err:
                _LOGGER.error("reauth send_sms failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                errors["base"] = "sms_rejected"

        return self.async_show_form(
            step_id="reauth_confirm",
            errors=errors,
            description_placeholders={"phone": self._phone},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ShipmentOptionsFlow()


class ShipmentOptionsFlow(OptionsFlow):
    """Scan interval, archive/delivered cap, notify toggle.

    FedEx entries additionally carry the tracked-numbers list here (comma
    separated in the form, split/joined on the way in/out) — it's the
    closest FedEx has to "adding a parcel", since there's no account to
    auto-discover from, and options don't need a reauth like credentials
    would. Pocztex doesn't need this — it auto-discovers, like DPD.

    InPost entries additionally carry an ignored-shipments list, same comma
    separated shape — the only way to make a zombie InPost record (still
    returned by /v4/parcels/tracked, no longer shown in InPost Mobile — see
    CONF_IGNORED_SHIPMENTS in const.py) stop appearing here, since InPost's
    API has no known delete/hide endpoint to actually remove it upstream.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        carrier = self.config_entry.data.get(CONF_CARRIER)
        needs_numbers = carrier == CARRIER_FEDEX
        needs_ignore_list = carrier == CARRIER_INPOST
        if user_input is not None:
            data = dict(user_input)
            if needs_numbers:
                raw = data.pop("tracking_numbers_csv", "")
                data[CONF_TRACKING_NUMBERS] = [
                    n.strip() for n in raw.split(",") if n.strip()
                ]
            if needs_ignore_list:
                raw = data.pop("ignored_shipments_csv", "")
                data[CONF_IGNORED_SHIPMENTS] = [
                    n.strip() for n in raw.split(",") if n.strip()
                ]
            return self.async_create_entry(title="", data=data)

        opts = self.config_entry.options
        schema: dict[Any, Any] = {
            vol.Optional(
                CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, 15)
            ): vol.All(vol.Coerce(int), vol.Range(min=5, max=180)),
            vol.Optional(
                CONF_ARCHIVE_LIMIT,
                default=opts.get(CONF_ARCHIVE_LIMIT, DEFAULT_ARCHIVE_LIMIT),
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
            vol.Optional(
                CONF_NOTIFY, default=opts.get(CONF_NOTIFY, True)
            ): bool,
        }
        if needs_numbers:
            schema[vol.Optional(
                "tracking_numbers_csv",
                default=", ".join(opts.get(CONF_TRACKING_NUMBERS, [])),
            )] = str
        if needs_ignore_list:
            schema[vol.Optional(
                "ignored_shipments_csv",
                default=", ".join(opts.get(CONF_IGNORED_SHIPMENTS, [])),
            )] = str
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
