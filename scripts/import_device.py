"""Import a Zigbee2MQTT device definition as a reviewed regression fixture."""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from custom_components.z2m_static_entities.parser import parse_exposes

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE_DIR = REPOSITORY_ROOT / "tests" / "fixtures" / "imported"
V1_DOMAINS = frozenset({"binary_sensor", "sensor", "switch"})
KNOWN_FUTURE_DOMAINS = frozenset({"button", "number", "select"})
SUPPORTED_ROOT_TYPES = frozenset({"binary", "numeric", "enum"})
VALID_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class ImportReport:
    """Result of validating and importing one definition."""

    name: str
    model: str
    vendor: str
    entity_count: int
    active_domains: tuple[str, ...]
    future_domains: tuple[str, ...]
    unsupported_types: tuple[str, ...]
    fixture_path: Path | None
    expected_path: Path | None


class InvalidDefinitionError(ValueError):
    """Raised when input is not a usable Z2M definition."""


class UnsupportedExposeError(ValueError):
    """Raised before writing a fixture containing unknown expose shapes."""

    def __init__(self, unsupported_types: tuple[str, ...]) -> None:
        """Initialize the unsupported-expose error."""
        self.unsupported_types = unsupported_types
        super().__init__(", ".join(unsupported_types))


def load_definition(path: Path) -> dict[str, Any]:
    """Load either a raw definition or one bridge/devices entry."""
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise InvalidDefinitionError("The input must be a JSON object")
    if isinstance(payload.get("definition"), dict):
        payload = payload["definition"]
    exposes = payload.get("exposes")
    if not isinstance(exposes, list):
        raise InvalidDefinitionError("The definition must contain an exposes list")
    return payload


def unsupported_expose_types(definition: dict[str, Any]) -> tuple[str, ...]:
    """Return expose shapes that the generic parser cannot safely map."""
    unsupported: set[str] = set()
    for expose in definition["exposes"]:
        if not isinstance(expose, dict):
            unsupported.add("non_object")
            continue
        expose_type = expose.get("type")
        if expose_type in SUPPORTED_ROOT_TYPES:
            if "access" not in expose or "property" not in expose:
                unsupported.add(f"{expose_type}:missing_contract")
            continue
        if expose_type == "switch":
            features = expose.get("features")
            if (
                not isinstance(features, list)
                or len(features) != 1
                or not isinstance(features[0], dict)
                or features[0].get("type") != "binary"
                or "access" not in features[0]
                or "property" not in features[0]
            ):
                unsupported.add("switch:unsupported_features")
            continue
        unsupported.add(str(expose_type or "missing_type"))
    return tuple(sorted(unsupported))


def import_definition(
    input_path: Path,
    name: str,
    *,
    fixture_dir: Path = DEFAULT_FIXTURE_DIR,
    force: bool = False,
    allow_unsupported: bool = False,
) -> ImportReport:
    """Validate a definition and write fixture plus expected parser output."""
    if not VALID_NAME.fullmatch(name):
        raise InvalidDefinitionError(
            "Name must start with a letter and contain lowercase letters, "
            "numbers, or underscores"
        )

    definition = load_definition(input_path)
    unsupported = unsupported_expose_types(definition)
    if unsupported and not allow_unsupported:
        raise UnsupportedExposeError(unsupported)

    entities = parse_exposes(definition)
    active_domains = tuple(
        sorted({entity.domain for entity in entities if entity.domain in V1_DOMAINS})
    )
    future_domains = tuple(
        sorted(
            {
                entity.domain
                for entity in entities
                if entity.domain in KNOWN_FUTURE_DOMAINS
            }
        )
    )

    fixture_path = fixture_dir / f"{name}.json"
    expected_path = fixture_dir / f"{name}.expected.json"
    if not force and (fixture_path.exists() or expected_path.exists()):
        raise FileExistsError(
            f"{name} already exists; pass --force only after reviewing the change"
        )

    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(
        json.dumps(definition, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    expected_path.write_text(
        json.dumps(
            [asdict(entity) for entity in entities],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return ImportReport(
        name=name,
        model=str(definition.get("model", "")),
        vendor=str(definition.get("vendor", "")),
        entity_count=len(entities),
        active_domains=active_domains,
        future_domains=future_domains,
        unsupported_types=unsupported,
        fixture_path=fixture_path,
        expected_path=expected_path,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a Z2M definition as a parser regression fixture",
    )
    parser.add_argument("definition", type=Path, help="Path to definition JSON")
    parser.add_argument(
        "--name",
        required=True,
        help="Lowercase fixture name, for example mmwave_presence_1",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing reviewed fixture",
    )
    parser.add_argument(
        "--allow-unsupported",
        action="store_true",
        help="Capture a partial fixture after reviewing unsupported expose types",
    )
    return parser


def main() -> int:
    """Run the importer CLI."""
    args = _parser().parse_args()
    try:
        report = import_definition(
            args.definition,
            args.name,
            force=args.force,
            allow_unsupported=args.allow_unsupported,
        )
    except (InvalidDefinitionError, UnsupportedExposeError, FileExistsError) as err:
        print(f"Import refused: {err}", file=sys.stderr)
        return 2

    print(f"Imported {report.vendor} {report.model} as {report.name}")
    print(f"Entities: {report.entity_count}")
    print(f"V1 domains: {', '.join(report.active_domains) or 'none'}")
    print(f"Known future domains: {', '.join(report.future_domains) or 'none'}")
    print(f"Unsupported expose types: {', '.join(report.unsupported_types) or 'none'}")
    print(f"Review: {report.fixture_path}")
    print(f"Review: {report.expected_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
