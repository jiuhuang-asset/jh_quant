from __future__ import annotations

from typing import Any, Callable, Dict

from ..config import BrokerSpec


BROKER_REGISTRY: dict[str, Callable[..., object]] = {}


def register_broker(name: str, factory: Callable[..., object]) -> None:
    BROKER_REGISTRY[name.lower()] = factory


def create_broker(
    broker_spec: BrokerSpec,
    *,
    session_id: str,
) -> object:
    key = broker_spec.name.lower()
    try:
        factory = BROKER_REGISTRY[key]
    except KeyError as exc:
        available = ", ".join(sorted(BROKER_REGISTRY)) or "<empty>"
        raise ValueError(
            f"Unknown broker '{broker_spec.name}'. Available brokers: {available}"
        ) from exc

    params = dict(broker_spec.params or {})
    params.setdefault("session_id", session_id)
    return factory(**params)


__all__ = ["BROKER_REGISTRY", "create_broker", "register_broker"]
