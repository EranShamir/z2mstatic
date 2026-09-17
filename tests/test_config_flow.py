"""Tests for Z2M Static Entities configuration flows."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
    MockConfigEntry,
)

from custom_components.z2m_static_entities.config_flow import (
    _merge_selection,
    _sort_choices,
)
from custom_components.z2m_static_entities.const import (
    CONF_BASE_TOPICS,
    CONF_LIGHT_ENTITIES,
    CONF_RELIABLE_ENTITIES,
    CONF_STALE_DAYS,
    DEFAULT_STALE_DAYS,
    DOMAIN,
)


async def test_cfg_001_user_flow_normalizes_base_topics(
    hass: HomeAssistant,
) -> None:
    """CFG-001: Setup normalizes and deduplicates one or more base topics."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_BASE_TOPICS: " zigbee2mqtt/, zigbee2mqtt2, zigbee2mqtt ",
            CONF_STALE_DAYS: 45,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Z2M Static Entities"
    assert result["data"] == {
        CONF_BASE_TOPICS: ["zigbee2mqtt", "zigbee2mqtt2"],
        CONF_STALE_DAYS: 45,
    }


async def test_cfg_001_rejects_empty_base_topics(hass: HomeAssistant) -> None:
    """CFG-001: Setup rejects input containing no usable base topic."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_BASE_TOPICS: " , /, ",
            CONF_STALE_DAYS: DEFAULT_STALE_DAYS,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_BASE_TOPICS: "base_topics_required"}


async def test_cfg_001_allows_only_one_config_entry(hass: HomeAssistant) -> None:
    """CFG-001: A single entry owns all configured Z2M instances."""
    MockConfigEntry(domain=DOMAIN).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_cfg_002_options_update_topics_and_threshold(
    hass: HomeAssistant,
) -> None:
    """CFG-002: Options update normalized topics and stale threshold."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_BASE_TOPICS: ["zigbee2mqtt"],
            CONF_STALE_DAYS: DEFAULT_STALE_DAYS,
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_BASE_TOPICS: "zigbee2mqtt2/, zigbee2mqtt",
            CONF_STALE_DAYS: 60,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_BASE_TOPICS: ["zigbee2mqtt2", "zigbee2mqtt"],
        CONF_STALE_DAYS: 60,
        CONF_LIGHT_ENTITIES: [],
        CONF_RELIABLE_ENTITIES: [],
    }


def test_cfg_003_hidden_override_selections_are_preserved() -> None:
    """CFG-003: Saving a partial form cannot erase unavailable selections."""
    existing = {"visible", "temporarily_missing"}

    result = _merge_selection(
        existing,
        rendered={"visible"},
        submitted=set(),
    )

    assert result == {"temporarily_missing"}


def test_cfg_003_rendered_unavailable_selection_can_be_removed() -> None:
    """CFG-003: Unchecking a displayed unavailable override removes it."""
    result = _merge_selection(
        {"unavailable"},
        rendered={"unavailable"},
        submitted=set(),
    )

    assert result == set()


def test_cfg_003_control_choices_are_sorted_by_friendly_name() -> None:
    """CFG-003: Light and reliable selectors sort by their displayed labels."""
    choices = {
        "0x2|state": "zeta switch — State [state]",
        "0x1|state_s2": "Alpha switch — Right [state_s2]",
        "0x1|state_s1": "Alpha switch — Left [state_s1]",
    }

    result = _sort_choices(choices)

    assert list(result.values()) == [
        "Alpha switch — Left [state_s1]",
        "Alpha switch — Right [state_s2]",
        "zeta switch — State [state]",
    ]
