"""Config & options flow for InPost (SMS-code authentication)."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

# Common phone prefixes; the field is a dropdown defaulting to +48 but accepts a
# custom value for anything not listed.
PREFIX_OPTIONS = ["+48", "+49", "+44", "+420", "+421", "+380", "+31", "+33"]

from .api import InPostApi, InPostError
from .const import (
    CONF_ALIAS,
    CONF_ARCHIVE_LIMIT,
    CONF_NOTIFY,
    CONF_PHONE,
    CONF_PREFIX,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DEFAULT_ARCHIVE_LIMIT,
    DEFAULT_BASE,
    DEFAULT_UA,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _api() -> InPostApi:
    return InPostApi(DEFAULT_BASE, DEFAULT_UA)


class InPostConfigFlow(ConfigFlow, domain=DOMAIN):
    """Two-step SMS flow: request a code, then verify it and store the token."""

    VERSION = 1

    def __init__(self) -> None:
        self._alias: str = ""
        self._prefix: str = "+48"
        self._phone: str = ""
        self._reauth_entry: ConfigEntry | None = None

    async def async_step_user(
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
                await self.async_set_unique_id(self._phone)
                self._abort_if_unique_id_configured()
                try:
                    ok = await self.hass.async_add_executor_job(
                        _api().send_sms, self._prefix, self._phone
                    )
                except InPostError as err:
                    _LOGGER.error("send_sms failed: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    if ok:
                        return await self.async_step_sms()
                    errors["base"] = "sms_rejected"

        return self.async_show_form(
            step_id="user",
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
                    _api().verify_sms, code, self._prefix, self._phone
                )
            except InPostError as err:
                _LOGGER.warning("verify_sms failed: %s", err)
                errors["base"] = "invalid_code"
            else:
                data = {
                    CONF_ALIAS: self._alias,
                    CONF_PREFIX: self._prefix,
                    CONF_PHONE: self._phone,
                    CONF_REFRESH_TOKEN: refresh_token,
                }
                if self._reauth_entry is not None:
                    return self.async_update_reload_and_abort(
                        self._reauth_entry, data=data
                    )
                return self.async_create_entry(title=self._alias, data=data)

        return self.async_show_form(
            step_id="sms",
            data_schema=vol.Schema({vol.Required("code"): str}),
            errors=errors,
            description_placeholders={"phone": f"+{self._prefix.lstrip('+')} {self._phone}"},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        self._alias = entry_data.get(CONF_ALIAS, "")
        self._prefix = entry_data.get(CONF_PREFIX, "+48")
        self._phone = entry_data.get(CONF_PHONE, "")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                ok = await self.hass.async_add_executor_job(
                    _api().send_sms, self._prefix, self._phone
                )
            except InPostError as err:
                _LOGGER.error("reauth send_sms failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                if ok:
                    return await self.async_step_sms()
                errors["base"] = "sms_rejected"

        return self.async_show_form(
            step_id="reauth_confirm",
            errors=errors,
            description_placeholders={"phone": f"+{self._prefix.lstrip('+')} {self._phone}"},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return InPostOptionsFlow()


class InPostOptionsFlow(OptionsFlow):
    """Scan interval, archive cap, notify toggle."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=opts.get(CONF_SCAN_INTERVAL, 15),
                    ): vol.All(vol.Coerce(int), vol.Range(min=5, max=180)),
                    vol.Optional(
                        CONF_ARCHIVE_LIMIT,
                        default=opts.get(CONF_ARCHIVE_LIMIT, DEFAULT_ARCHIVE_LIMIT),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                    vol.Optional(
                        CONF_NOTIFY, default=opts.get(CONF_NOTIFY, True)
                    ): bool,
                }
            ),
        )
