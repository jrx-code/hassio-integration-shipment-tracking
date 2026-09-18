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

