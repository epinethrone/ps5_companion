"""Config flow for PS5 Companion."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
)

from .const import (
    CONF_POWER_SWITCH,
    CONF_PSN_ENTRY_ID,
    CONF_VOLUME_DELEGATE,
    CONFLICTING_ENTITY_IDS,
    DEFAULT_NAME,
    DOMAIN,
    PS5_MQTT_POWER_SUFFIX,
    PSN_DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _detect_psn_entry(hass: HomeAssistant) -> str | None:
    """Return the playstation_network config entry id, or None if not present."""
    entries = hass.config_entries.async_entries(PSN_DOMAIN)
    if not entries:
        return None
    # Return the first non-disabled entry. If a user has multiple PSN accounts,
    # they can choose at setup time in a future iteration; v1 picks the first.
    for e in entries:
        if not e.disabled_by:
            return e.entry_id
    return None


def _detect_ps5_mqtt_power_switches(hass: HomeAssistant) -> list[str]:
    """Find candidate switch entities published by the ps5-mqtt addon.

    The addon's switch unique_ids end with '_power_ps5mqtt' (e.g.
    '2C9E000AEA77_power_ps5mqtt'). Returns matching entity_ids.
    """
    registry = er.async_get(hass)
    return [
        ent.entity_id
        for ent in registry.entities.values()
        if ent.domain == "switch"
        and ent.platform == "mqtt"
        and ent.unique_id
        and ent.unique_id.endswith(PS5_MQTT_POWER_SUFFIX)
    ]


def _find_legacy_conflicts(hass: HomeAssistant) -> list[str]:
    """Return any legacy YAML-setup entity_ids still present in the registry."""
    registry = er.async_get(hass)
    return sorted(
        eid for eid in CONFLICTING_ENTITY_IDS
        if registry.async_get(eid) is not None
    )


class PS5CompanionConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the PS5 Companion config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """First (and only) step: pick power switch + optional volume delegate."""
        errors: dict[str, str] = {}

        # Single-instance enforcement — only one PS5 Companion entry at a time.
        # Easy to remove later if users want multi-PS5 support.
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        # Prerequisite: playstation_network must be configured.
        psn_entry_id = _detect_psn_entry(self.hass)
        if psn_entry_id is None:
            return self.async_abort(reason="playstation_network_missing")

        # Prerequisite: ps5-mqtt addon must have published at least one switch.
        candidate_switches = _detect_ps5_mqtt_power_switches(self.hass)
        if not candidate_switches:
            return self.async_abort(reason="ps5_mqtt_missing")

        # Migration safety: refuse setup if legacy YAML entities exist.
        conflicts = _find_legacy_conflicts(self.hass)
        if conflicts:
            return self.async_abort(
                reason="legacy_setup_present",
                description_placeholders={
                    "entities": ", ".join(conflicts),
                },
            )

        if user_input is not None:
            data = {
                CONF_PSN_ENTRY_ID: psn_entry_id,
                CONF_POWER_SWITCH: user_input[CONF_POWER_SWITCH],
                CONF_VOLUME_DELEGATE: user_input.get(CONF_VOLUME_DELEGATE) or None,
                CONF_NAME: user_input.get(CONF_NAME, DEFAULT_NAME),
            }
            return self.async_create_entry(title=data[CONF_NAME], data=data)

        # Build the form
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(
                    CONF_POWER_SWITCH,
                    default=candidate_switches[0],
                ): EntitySelector(
                    EntitySelectorConfig(
                        domain="switch",
                        include_entities=candidate_switches,
                    )
                ),
                vol.Optional(CONF_VOLUME_DELEGATE): EntitySelector(
                    EntitySelectorConfig(domain="media_player")
                ),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "psn_entry": psn_entry_id,
                "candidate_count": str(len(candidate_switches)),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> PS5CompanionOptionsFlow:
        """Return the options flow handler."""
        return PS5CompanionOptionsFlow(config_entry)


class PS5CompanionOptionsFlow(OptionsFlow):
    """Options flow — lets the user change volume delegate / power switch later."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Init."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        candidate_switches = _detect_ps5_mqtt_power_switches(self.hass) or [
            current.get(CONF_POWER_SWITCH, "")
        ]

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_POWER_SWITCH,
                    default=current.get(CONF_POWER_SWITCH),
                ): EntitySelector(
                    EntitySelectorConfig(
                        domain="switch",
                        include_entities=candidate_switches,
                    )
                ),
                vol.Optional(
                    CONF_VOLUME_DELEGATE,
                    default=current.get(CONF_VOLUME_DELEGATE) or vol.UNDEFINED,
                ): EntitySelector(
                    EntitySelectorConfig(domain="media_player")
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
