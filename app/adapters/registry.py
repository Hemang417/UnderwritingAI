from app.adapters.base import BaseSourceAdapter

ADAPTER_REGISTRY: dict[str, type[BaseSourceAdapter]] = {}


def register_adapter(adapter_key: str):
    """Class decorator: adds a state/source to the registry with zero
    orchestrator changes -- the whole point of the adapter pattern (ADR-004).
    """

    def decorator(adapter_cls: type[BaseSourceAdapter]) -> type[BaseSourceAdapter]:
        ADAPTER_REGISTRY[adapter_key] = adapter_cls
        return adapter_cls

    return decorator


def get_adapter(adapter_key: str) -> BaseSourceAdapter:
    try:
        adapter_cls = ADAPTER_REGISTRY[adapter_key]
    except KeyError as exc:
        raise KeyError(f"No adapter registered for key '{adapter_key}'") from exc
    return adapter_cls()
