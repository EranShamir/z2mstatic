"""Shared test fixtures for Z2M Static Entities."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integration loading in every test."""


@pytest.fixture
def load_fixture() -> Callable[[str], dict[str, Any]]:
    """Return a callable that loads a device definition fixture by name."""

    def _load(name: str) -> dict[str, Any]:
        with (FIXTURES_DIR / f"{name}.json").open() as f:
            return json.load(f)

    return _load
