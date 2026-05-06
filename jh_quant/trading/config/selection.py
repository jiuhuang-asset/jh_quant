from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import inspect
from typing import TYPE_CHECKING, Any, Dict, Optional, Protocol, runtime_checkable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    create_model,
    field_validator,
)

from jh_quant.data import JHData

from ..models import SelectionSnapshot

if TYPE_CHECKING:
    from jh_quant.backtest.selectors import FactorSelector

    from ..market_data import MarketDataProvider


def _params_to_plain_dict(params: Any) -> Dict[str, Any]:
    if params is None:
        return {}
    if isinstance(params, dict):
        return dict(params)
    if isinstance(params, BaseModel):
        return params.model_dump(exclude_none=False)
    if is_dataclass(params) and not isinstance(params, type):
        return asdict(params)
    raise TypeError(
        "selection params must be a dict, pydantic BaseModel, dataclass instance, or None"
    )


def _validated_model_to_dict(model_cls: type, params: Dict[str, Any]) -> Dict[str, Any]:
    adapter = TypeAdapter(model_cls)
    value = adapter.validate_python(params)
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_none=False)
    if is_dataclass(value):
        return asdict(value)
    return dict(value)


def _schema_from_model(model_cls: type) -> Dict[str, Any]:
    return TypeAdapter(model_cls).json_schema()


@runtime_checkable
class SelectionProvider(Protocol):
    def select(self, as_of_date: str) -> SelectionSnapshot:
        raise NotImplementedError

    @property
    def config(self) -> Dict[str, Any]:
        return {}


class SelectionSpec(BaseModel):
    """选股器配置描述。

    - `name`：注册到系统中的选股器名称
    - `params`：该选股器对应的参数字典
    - `alias`：可选别名，方便日志和接口展示
    """

    name: str = Field(description="选股器注册名，例如 `factor_selector`。")
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="选股器初始化或运行所需的参数字典，也支持传入 dataclass 或 Pydantic 配置对象。",
    )
    alias: Optional[str] = Field(
        default=None, description="可选别名，便于在日志、接口或界面中展示。"
    )

    @field_validator("params", mode="before")
    @classmethod
    def _normalize_params(cls, value: Any) -> Dict[str, Any]:
        return _params_to_plain_dict(value)


@dataclass
class FactorSelectionConfig:
    """因子选股器参数。"""

    factor: str
    start: str
    top_n: int = 100
    bottom_n: int = 100
    factor_alpha: float = 0.10
    default_weight: float = 0.1
    period: str = "M"
    insignificant_weight_ratio: float = 0.5
    missing_data_threshold: float = 0.10
    test_window: int = 36
    verbose: bool = True


class FactorSelectionProviderAdptor(SelectionProvider):
    def __init__(self, jh_data: JHData, config: FactorSelectionConfig):
        from jh_quant.backtest.selectors import FactorSelector

        self.factor_selector: FactorSelector = FactorSelector(jh_data=jh_data)
        self._config = config

    def select(self, as_of_date: str) -> SelectionSnapshot:
        return self.factor_selector.select(
            **asdict(self._config),
            end=as_of_date,
        )

    @property
    def config(self) -> Dict[str, Any]:
        return asdict(self._config)


SELECTION_PROVIDER_REGISTRY: Dict[str, type] = {
    "factor_selector": FactorSelectionProviderAdptor,
}

SELECTION_PROVIDER_CONFIG_MODELS: Dict[str, type] = {
    "factor_selector": FactorSelectionConfig,
}

SELECTION_PROVIDER_RUNTIME_DEPENDENCIES: Dict[str, tuple[str, ...]] = {
    "factor_selector": ("jh_data",),
}


def get_selection_config_model(name: str) -> Optional[type]:
    """获取某个选股器注册名对应的参数模型类。"""

    return SELECTION_PROVIDER_CONFIG_MODELS.get(name)


def _callable_param_model(
    target: Any, model_name: str, *, exclude: Optional[set[str]] = None
):
    exclude = exclude or set()
    signature = inspect.signature(target)
    fields: Dict[str, tuple[Any, Any]] = {}
    for name, param in signature.parameters.items():
        if name in exclude or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        annotation = (
            Any if param.annotation is inspect.Signature.empty else param.annotation
        )
        default = ... if param.default is inspect.Signature.empty else param.default
        fields[name] = (annotation, default)
    return create_model(model_name, __config__=ConfigDict(extra="forbid"), **fields)


def _validate_callable_params(
    target: Any,
    params: Dict[str, Any],
    model_name: str,
    *,
    exclude: Optional[set[str]] = None,
) -> Dict[str, Any]:
    model = _callable_param_model(target, model_name, exclude=exclude)
    return model.model_validate(params).model_dump(exclude_none=False)


def _schema_from_callable(
    target: Any,
    model_name: str,
    *,
    exclude: Optional[set[str]] = None,
) -> Dict[str, Any]:
    model = _callable_param_model(target, model_name, exclude=exclude)
    return model.model_json_schema()


def _resolve_selection_runtime_kwargs(
    name: str,
    market_data_provider: Optional["MarketDataProvider"],
) -> Dict[str, Any]:
    if name == "factor_selector":
        jh_data = getattr(market_data_provider, "jhd", None)
        if jh_data is None:
            raise ValueError(
                "selection provider 'factor_selector' requires a market data provider with a 'jhd' attribute"
            )
        return {"jh_data": jh_data}
    return {}


def validate_selection_params(name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if name not in SELECTION_PROVIDER_REGISTRY:
        raise ValueError(f"Unsupported selection provider name: {name}")
    if name in SELECTION_PROVIDER_CONFIG_MODELS:
        return _validated_model_to_dict(SELECTION_PROVIDER_CONFIG_MODELS[name], params)
    provider_cls = SELECTION_PROVIDER_REGISTRY[name]
    return _validate_callable_params(
        provider_cls.__init__,
        params,
        f"{provider_cls.__name__}Params",
        exclude={"self"},
    )


def normalize_selection_spec(spec: SelectionSpec) -> SelectionSpec:
    return spec.model_copy(
        update={"params": validate_selection_params(spec.name, spec.params)}
    )


def get_selection_params_schema(name: str) -> Dict[str, Any]:
    if name not in SELECTION_PROVIDER_REGISTRY:
        raise ValueError(f"Unsupported selection provider name: {name}")
    if name in SELECTION_PROVIDER_CONFIG_MODELS:
        return _schema_from_model(SELECTION_PROVIDER_CONFIG_MODELS[name])
    provider_cls = SELECTION_PROVIDER_REGISTRY[name]
    return _schema_from_callable(
        provider_cls.__init__,
        f"{provider_cls.__name__}Params",
        exclude={"self"},
    )


def list_selection_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "params_schema": get_selection_params_schema(name),
            "config_model": getattr(get_selection_config_model(name), "__name__", None),
            "runtime_dependencies": list(
                SELECTION_PROVIDER_RUNTIME_DEPENDENCIES.get(name, ())
            ),
        }
        for name in SELECTION_PROVIDER_REGISTRY
    ]


def build_selection_provider(
    spec: SelectionSpec,
    market_data_provider: Optional["MarketDataProvider"],
) -> tuple[SelectionSpec, SelectionProvider]:
    normalized_spec = normalize_selection_spec(spec)
    provider_cls = SELECTION_PROVIDER_REGISTRY[normalized_spec.name]
    runtime_kwargs = _resolve_selection_runtime_kwargs(
        normalized_spec.name, market_data_provider
    )

    if normalized_spec.name in SELECTION_PROVIDER_CONFIG_MODELS:
        config_cls = SELECTION_PROVIDER_CONFIG_MODELS[normalized_spec.name]
        provider = provider_cls(
            config=config_cls(**normalized_spec.params),
            **runtime_kwargs,
        )
    else:
        provider = provider_cls(
            **normalized_spec.params,
            **runtime_kwargs,
        )

    return normalized_spec, provider


def register_selection_provider(
    name: str,
    provider_cls: type,
    config_model: Optional[type] = None,
    runtime_dependencies: Optional[tuple[str, ...]] = None,
) -> None:
    """注册选股器实现及其可选参数模型。"""

    if not inspect.isclass(provider_cls):
        raise TypeError(f"{provider_cls} must be a class")
    if not callable(getattr(provider_cls, "select", None)):
        raise TypeError(f"{provider_cls} must define a callable select method")
    SELECTION_PROVIDER_REGISTRY[name] = provider_cls
    if config_model is not None:
        SELECTION_PROVIDER_CONFIG_MODELS[name] = config_model
    if runtime_dependencies is not None:
        SELECTION_PROVIDER_RUNTIME_DEPENDENCIES[name] = runtime_dependencies


def create_selection_provider(spec: SelectionSpec, **init_kwargs) -> SelectionProvider:
    normalized_spec = normalize_selection_spec(spec)
    provider_cls = SELECTION_PROVIDER_REGISTRY[normalized_spec.name]
    if normalized_spec.name in SELECTION_PROVIDER_CONFIG_MODELS:
        config_cls = SELECTION_PROVIDER_CONFIG_MODELS[normalized_spec.name]
        return provider_cls(config=config_cls(**normalized_spec.params), **init_kwargs)
    return provider_cls(**normalized_spec.params, **init_kwargs)
