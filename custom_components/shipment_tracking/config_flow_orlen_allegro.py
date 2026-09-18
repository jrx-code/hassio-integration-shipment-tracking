"""Config-flow mixins for Orlen Paczka and Allegro One."""
from __future__ import annotations

import uuid
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult

from .carriers_orlen_allegro import CARRIER_ALLEGRO_ONE, CARRIER_ORLEN
from .const import CONF_ALIAS, CONF_CARRIER


class OrlenAllegroOneFlowMixin:
    """Mixin providing Orlen Paczka + Allegro One config steps.

    Mixed into ShipmentConfigFlow. Expects ``self._alias`` and HA ConfigFlow APIs.
    """

    async def async_step_orlen(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Alias only — public track-by-number, no credentials."""
        if user_input is not None:
            self._alias = (user_input.get(CONF_ALIAS) or "").strip() or "Orlen Paczka"
            uid = f"orlen_{uuid.uuid4().hex[:12]}"
            await self.async_set_unique_id(uid)
            return self.async_create_entry(
                title=f"Orlen Paczka — {self._alias}",
                data={
                    CONF_CARRIER: CARRIER_ORLEN,
                    CONF_ALIAS: self._alias,
                },
            )

        return self.async_show_form(
            step_id="orlen",
            data_schema=vol.Schema(
                {vol.Optional(CONF_ALIAS, default=self._alias or "Orlen Paczka"): str}
            ),
        )

    async def async_step_allegro_one(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Alias only — public edge track-by-number, no OAuth."""
        if user_input is not None:
            self._alias = (user_input.get(CONF_ALIAS) or "").strip() or "Allegro One"
            uid = f"allegro_one_{uuid.uuid4().hex[:12]}"
            await self.async_set_unique_id(uid)
            return self.async_create_entry(
                title=f"Allegro One — {self._alias}",
                data={
                    CONF_CARRIER: CARRIER_ALLEGRO_ONE,
                    CONF_ALIAS: self._alias,
                },
            )

        return self.async_show_form(
            step_id="allegro_one",
            data_schema=vol.Schema(
                {vol.Optional(CONF_ALIAS, default=self._alias or "Allegro One"): str}
            ),
        )
