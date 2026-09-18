"""Config & options flow for Śledzenie przesyłek (InPost, DPD, FedEx, Pocztex, DHL, Orlen, Allegro One)."""
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
from .carriers_orlen_allegro import (
    CARRIER_ALLEGRO_ONE,
    CARRIER_LABEL_ALLEGRO_ONE,
    CARRIER_LABEL_ORLEN,
    CARRIER_ORLEN,
)
from .config_flow_orlen_allegro import OrlenAllegroOneFlowMixin
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


class ShipmentConfigFlow(OrlenAllegroOneFlowMixin, ConfigFlow, domain=DOMAIN):
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
            if self._carrier == CARRIER_ORLEN:
                return await self.async_step_orlen()
            if self._carrier == CARRIER_ALLEGRO_ONE:
                return await self.async_step_allegro_one()
            return await self.async_step_inpost()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CARRIER, default=CARRIER_INPOST): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": c, "label": CARRIER_LABELS[c]} for c in CARRIERS
                            ]
                            + [
                                {"value": CARRIER_ORLEN, "label": CARRIER_LABEL_ORLEN},
                                {
                                    "value": CARRIER_ALLEGRO_ONE,
                                    "label": CARRIER_LABEL_ALLEGRO_ONE,
                                },
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
