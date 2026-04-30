"""Config file import/export utilities.

Read and write :class:`SignalGatewayServiceConfig` as JSON files for
offline editing, backup, and sharing across environments.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Union

from .service import SignalGatewayServiceConfig


def export_config_to_file(
    config: SignalGatewayServiceConfig,
    filepath: Union[str, Path],
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> Path:
    """Serialize the current config bundle to a JSON file.

    Args:
        config: The service config to export.
        filepath: Destination path (``.json`` extension is appended if missing).
        indent: JSON indentation level.
        ensure_ascii: Whether to escape non-ASCII characters.

    Returns:
        The resolved file path that was written.
    """
    filepath = Path(filepath)
    if not filepath.suffix:
        filepath = filepath.with_suffix(".json")

    payload = config.model_dump(mode="json")
    filepath.write_text(
        json.dumps(payload, indent=indent, ensure_ascii=ensure_ascii),
        encoding="utf-8",
    )
    return filepath.resolve()


def export_config_to_json_string(
    config: SignalGatewayServiceConfig,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> str:
    """Serialize the current config bundle to a JSON string."""
    payload = config.model_dump(mode="json")
    return json.dumps(payload, indent=indent, ensure_ascii=ensure_ascii)


def import_config_from_file(filepath: Union[str, Path]) -> SignalGatewayServiceConfig:
    """Load and validate a config bundle from a JSON file.

    Args:
        filepath: Path to a JSON config file.

    Returns:
        Validated :class:`SignalGatewayServiceConfig` instance.

    Raises:
        FileNotFoundError: If *filepath* does not exist.
        ValueError: If the file content fails validation.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Config file not found: {filepath}")

    try:
        payload = json.loads(filepath.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in config file {filepath}: {exc}") from exc

    return import_config_from_dict(payload)


def import_config_from_dict(payload: dict) -> SignalGatewayServiceConfig:
    """Validate and build a config bundle from a raw dictionary.

    Args:
        payload: Dictionary representation of a config bundle.

    Returns:
        Validated :class:`SignalGatewayServiceConfig` instance.

    Raises:
        ValueError: If validation fails.
    """
    return SignalGatewayServiceConfig.model_validate(payload)
