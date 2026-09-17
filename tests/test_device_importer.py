"""Tests for the definition-import workflow."""

import json
from pathlib import Path

import pytest

from scripts.import_device import (
    InvalidDefinitionError,
    UnsupportedExposeError,
    import_definition,
)


def _write_definition(path: Path, exposes: list[dict[str, object]]) -> Path:
    path.write_text(
        json.dumps(
            {
                "model": "TEST-1",
                "vendor": "Test vendor",
                "description": "Test device",
                "exposes": exposes,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_importer_writes_fixture_and_expected_entities(tmp_path: Path) -> None:
    """A generic definition becomes a deterministic reviewed fixture pair."""
    source = _write_definition(
        tmp_path / "definition.json",
        [
            {
                "type": "binary",
                "access": 1,
                "property": "occupancy",
                "label": "Occupancy",
                "value_on": True,
                "value_off": False,
            },
            {
                "type": "numeric",
                "access": 3,
                "property": "sensitivity",
                "label": "Sensitivity",
            },
        ],
    )
    fixture_dir = tmp_path / "fixtures"

    report = import_definition(
        source,
        "presence_sensor",
        fixture_dir=fixture_dir,
    )

    assert report.entity_count == 2
    assert report.active_domains == ("binary_sensor",)
    assert report.future_domains == ("number",)
    assert report.unsupported_types == ()
    assert report.fixture_path == fixture_dir / "presence_sensor.json"
    assert report.expected_path == fixture_dir / "presence_sensor.expected.json"
    expected = json.loads(report.expected_path.read_text(encoding="utf-8"))
    assert [entity["domain"] for entity in expected] == [
        "binary_sensor",
        "number",
    ]


def test_importer_refuses_unknown_composite_without_override(
    tmp_path: Path,
) -> None:
    """Unknown composite behavior cannot silently generate approved fixtures."""
    source = _write_definition(
        tmp_path / "definition.json",
        [{"type": "climate", "features": []}],
    )

    with pytest.raises(UnsupportedExposeError, match="climate"):
        import_definition(
            source,
            "thermostat",
            fixture_dir=tmp_path / "fixtures",
        )


def test_importer_can_capture_reviewed_unsupported_definition(
    tmp_path: Path,
) -> None:
    """Explicit override stores unknown data while reporting no mapped entity."""
    source = _write_definition(
        tmp_path / "definition.json",
        [{"type": "light", "features": []}],
    )

    report = import_definition(
        source,
        "reviewed_light",
        fixture_dir=tmp_path / "fixtures",
        allow_unsupported=True,
    )

    assert report.unsupported_types == ("light",)
    assert report.entity_count == 0


@pytest.mark.parametrize("name", ["Presence", "1_presence", "presence-sensor"])
def test_importer_rejects_noncanonical_fixture_names(
    tmp_path: Path,
    name: str,
) -> None:
    """Fixture names remain importable Python-style identifiers."""
    source = _write_definition(tmp_path / "definition.json", [])

    with pytest.raises(InvalidDefinitionError, match="Name must start"):
        import_definition(
            source,
            name,
            fixture_dir=tmp_path / "fixtures",
        )
