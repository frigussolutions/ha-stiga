"""Config flow for STIGA."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TimeSelector
from homeassistant.util import slugify

from .api import PINNED_BROKERS, CannotConnect, InvalidAuth, StigaAuth, robot_broker
from .const import CONF_BLOCKS, DOMAIN, MAX_BLOCKS, STIGA_API_URL
from .coordinator import blocks_from_options

USER_SCHEMA = vol.Schema({vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str})

# Attribution to the upstream project, shown while setting up and once set up (licence condition).
ATTRIBUTION = {"stiga_api_url": STIGA_API_URL}


class StigaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a STIGA config flow."""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Schedule block options."""
        return StigaOptionsFlow()

    async def _async_validate(self, email: str, password: str) -> str | None:
        """Return an error key, or None when the account has robots we can connect to."""
        auth = StigaAuth(async_get_clientsession(self.hass), email, password)
        try:
            robots = await auth.async_get_robots()
        except InvalidAuth:
            return "invalid_auth"
        except CannotConnect:
            return "cannot_connect"
        if not robots:
            return "no_robots"
        if any(robot_broker(robot) not in PINNED_BROKERS for robot in robots):
            return "unknown_broker"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the STIGA.GO credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()
            if not (error := await self._async_validate(email, user_input[CONF_PASSWORD])):
                return self.async_create_entry(
                    title=f"STIGA ({email})",
                    data={CONF_EMAIL: email, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                    description_placeholders=ATTRIBUTION,
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=USER_SCHEMA,
            description_placeholders=ATTRIBUTION,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication after the password was rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            email = entry.data[CONF_EMAIL]
            if not (error := await self._async_validate(email, user_input[CONF_PASSWORD])):
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )


def _parse_time(value: str | None, *, end: bool) -> str | None:
    """Selector 'HH:MM:SS' to 'HH:MM' on a half hour; a block ending at 00:00 ends at midnight."""
    if not value:
        return None
    hours, minutes, *seconds = (int(part) for part in value.split(":"))
    if minutes not in (0, 30) or any(seconds):
        raise ValueError("half_hour")
    if end and hours == 0 and minutes == 0:
        hours = 24
    return f"{hours:02d}:{minutes:02d}"


def _blocks_from_input(user_input: dict[str, Any]) -> list[dict[str, str]]:
    """Validate the form; raises ValueError(error key)."""
    blocks: list[dict[str, str]] = []
    for index in range(1, MAX_BLOCKS + 1):
        name = (user_input.get(f"block_{index}_name") or "").strip()
        if not name:
            continue
        start = _parse_time(user_input.get(f"block_{index}_start"), end=False)
        end = _parse_time(user_input.get(f"block_{index}_end"), end=True)
        if start is None or end is None:
            raise ValueError("missing_time")
        if start >= end:
            raise ValueError("end_before_start")
        blocks.append({"key": slugify(name), "name": name, "start": start, "end": end})
    if len({block["key"] for block in blocks}) != len(blocks):
        raise ValueError("duplicate_name")
    ordered = sorted(blocks, key=lambda block: block["start"])
    if any(a["end"] > b["start"] for a, b in zip(ordered, ordered[1:])):
        raise ValueError("overlap")
    return blocks


class StigaOptionsFlow(OptionsFlow):
    """Configure the schedule blocks offered as switches (up to three per day)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Edit the blocks; leave a name empty to drop that block."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                blocks = _blocks_from_input(user_input)
            except ValueError as err:
                errors["base"] = str(err)
            else:
                return self.async_create_entry(data={CONF_BLOCKS: blocks})

        current = [block.as_dict() for block in blocks_from_options(self.config_entry.options)]
        fields: dict[Any, Any] = {}
        for index in range(1, MAX_BLOCKS + 1):
            block = current[index - 1] if index <= len(current) else None
            start = end = None
            if block:
                start = f"{block['start']}:00"
                end = "00:00:00" if block["end"] == "24:00" else f"{block['end']}:00"
            fields[vol.Optional(f"block_{index}_name", default=block["name"] if block else "")] = str
            fields[vol.Optional(f"block_{index}_start", description={"suggested_value": start})] = TimeSelector()
            fields[vol.Optional(f"block_{index}_end", description={"suggested_value": end})] = TimeSelector()
        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields), errors=errors)
