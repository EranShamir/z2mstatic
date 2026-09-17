"""Configuration flows for Z2M Static Entities."""

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_BASE_TOPICS,
    CONF_LIGHT_ENTITIES,
    CONF_RELIABLE_ENTITIES,
    CONF_RESTORE_DEVICES,
    CONF_STALE_DAYS,
    DEFAULT_STALE_DAYS,
    DOMAIN,
)


def normalize_base_topics(value: str) -> list[str]:
    """Normalize a comma-separated list of MQTT base topics."""
    topics: list[str] = []
    for raw_topic in value.split(","):
        topic = raw_topic.strip().strip("/")
        if topic and topic not in topics:
            topics.append(topic)
    return topics


def _schema(
    base_topics: list[str],
    stale_days: int,
    tombstones: dict[str, str] | None = None,
    control_choices: dict[str, str] | None = None,
    light_entities: set[str] | None = None,
    reliable_entities: set[str] | None = None,
) -> vol.Schema:
    fields: dict[vol.Marker, Any] = {
        vol.Required(
            CONF_BASE_TOPICS,
            default=", ".join(base_topics),
        ): str,
        vol.Required(CONF_STALE_DAYS, default=stale_days): vol.All(
            vol.Coerce(int),
            vol.Range(min=1, max=3650),
        ),
    }
    if tombstones:
        fields[vol.Optional(CONF_RESTORE_DEVICES, default=[])] = cv.multi_select(
            tombstones
        )
    if control_choices:
        fields[
            vol.Optional(
                CONF_LIGHT_ENTITIES,
                default=sorted(light_entities or set()),
            )
        ] = cv.multi_select(control_choices)
        fields[
            vol.Optional(
                CONF_RELIABLE_ENTITIES,
                default=sorted(reliable_entities or set()),
            )
        ] = cv.multi_select(control_choices)
    return vol.Schema(fields)


class Z2MStaticEntitiesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle initial configuration."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow."""
        return Z2MStaticEntitiesOptionsFlow(config_entry)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Configure all Zigbee2MQTT base topics."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            topics = normalize_base_topics(user_input[CONF_BASE_TOPICS])
            if topics:
                return self.async_create_entry(
                    title="Z2M Static Entities",
                    data={
                        CONF_BASE_TOPICS: topics,
                        CONF_STALE_DAYS: user_input[CONF_STALE_DAYS],
                    },
                )
            errors[CONF_BASE_TOPICS] = "base_topics_required"

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(["zigbee2mqtt"], DEFAULT_STALE_DAYS),
            errors=errors,
        )


class Z2MStaticEntitiesOptionsFlow(config_entries.OptionsFlow):
    """Handle integration options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""
        self._entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Update base topics and stale-device threshold."""
        errors: dict[str, str] = {}
        if user_input is not None:
            topics = normalize_base_topics(user_input[CONF_BASE_TOPICS])
            if topics:
                choices = self._rendered_control_choices()
                current_lights = self._current_selection(CONF_LIGHT_ENTITIES)
                current_reliable = self._current_selection(CONF_RELIABLE_ENTITIES)
                light_entities = _merge_selection(
                    current_lights,
                    set(choices),
                    set(user_input.get(CONF_LIGHT_ENTITIES, [])),
                )
                reliable_entities = _merge_selection(
                    current_reliable,
                    set(choices),
                    set(user_input.get(CONF_RELIABLE_ENTITIES, [])),
                )
                if self._entry.state is ConfigEntryState.LOADED:
                    runtime = self._entry.runtime_data
                    for ieee in user_input.get(CONF_RESTORE_DEVICES, []):
                        runtime.registry.restore_tombstone(ieee)
                    runtime.schedule_save()
                return self.async_create_entry(
                    data={
                        **self._entry.options,
                        CONF_BASE_TOPICS: topics,
                        CONF_STALE_DAYS: user_input[CONF_STALE_DAYS],
                        CONF_LIGHT_ENTITIES: sorted(light_entities),
                        CONF_RELIABLE_ENTITIES: sorted(reliable_entities),
                    }
                )
            errors[CONF_BASE_TOPICS] = "base_topics_required"

        choices = self._rendered_control_choices()
        light_entities = self._current_selection(CONF_LIGHT_ENTITIES)
        reliable_entities = self._current_selection(CONF_RELIABLE_ENTITIES)
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(
                self._entry.options.get(
                    CONF_BASE_TOPICS,
                    self._entry.data[CONF_BASE_TOPICS],
                ),
                self._entry.options.get(
                    CONF_STALE_DAYS,
                    self._entry.data[CONF_STALE_DAYS],
                ),
                self._tombstone_choices(),
                choices,
                light_entities,
                reliable_entities,
            ),
            errors=errors,
        )

    def _tombstone_choices(self) -> dict[str, str]:
        if self._entry.state is not ConfigEntryState.LOADED:
            return {}
        return {
            ieee: f"{ieee} (removed {removed_at.date().isoformat()})"
            for ieee, removed_at in self._entry.runtime_data.registry.tombstones.items()
        }

    def _control_choices(self) -> dict[str, str]:
        if self._entry.state is not ConfigEntryState.LOADED:
            return {}
        return self._entry.runtime_data.control_choices()

    def _rendered_control_choices(self) -> dict[str, str]:
        choices = self._control_choices()
        selected = self._current_selection(
            CONF_LIGHT_ENTITIES
        ) | self._current_selection(CONF_RELIABLE_ENTITIES)
        for key in selected:
            choices.setdefault(key, f"{key} (unavailable selection)")
        return _sort_choices(choices)

    def _current_selection(self, key: str) -> set[str]:
        return set(self._entry.options.get(key, self._entry.data.get(key, [])))


def _merge_selection(
    existing: set[str],
    rendered: set[str],
    submitted: set[str],
) -> set[str]:
    """Replace rendered selections while preserving hidden/unavailable keys."""
    return (existing - rendered) | submitted


def _sort_choices(choices: dict[str, str]) -> dict[str, str]:
    """Sort options case-insensitively by their displayed friendly-name label."""
    return dict(
        sorted(
            choices.items(),
            key=lambda item: (item[1].casefold(), item[0]),
        )
    )
