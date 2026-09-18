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

    FedEx / Orlen Paczka / Allegro One entries additionally carry the
    tracked-numbers list here (comma separated in the form, split/joined on
    the way in/out). Pocztex doesn't need this — it auto-discovers, like DPD.

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
        needs_numbers = carrier in (CARRIER_FEDEX, CARRIER_ORLEN, CARRIER_ALLEGRO_ONE)
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

