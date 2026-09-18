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
