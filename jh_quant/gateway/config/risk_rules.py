"""风险规则配置与注册。

提供与 strategy.py / selection.py 一致的注册-验证-构建流程：
- ``RISK_RULE_REGISTRY``：预置常用风控规则
- ``RiskRuleSpec``：配置描述
- ``register_risk_rule``：用户自定义规则注册
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import inspect
from typing import Any, Dict, List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    create_model,
    field_validator,
)

from jh_quant.backtest.rules import (
    ATRTrailingStopRule,
    MaxConsecutiveFallingBarsRule,
    MaxConsecutiveRisingBarsRule,
    MaxHoldingBarsRule,
    RiskRule,
    StopLossRule,
    TakeProfitRule,
    TrailingStopRule,
)


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
        "risk rule params must be a dict, pydantic BaseModel, dataclass instance, or None"
    )


RISK_RULE_REGISTRY: Dict[str, type[RiskRule]] = {
    "stop_loss": StopLossRule,
    "take_profit": TakeProfitRule,
    "trailing_stop": TrailingStopRule,
    "atr_trailing_stop": ATRTrailingStopRule,
    "max_holding_bars": MaxHoldingBarsRule,
    "max_consecutive_rising": MaxConsecutiveRisingBarsRule,
    "max_consecutive_falling": MaxConsecutiveFallingBarsRule,
}


def register_risk_rule(name: str, rule_cls: type) -> None:
    if not issubclass(rule_cls, RiskRule):
        raise TypeError(f"{rule_cls} must inherit from RiskRule")
    RISK_RULE_REGISTRY[name] = rule_cls


class RiskRuleSpec(BaseModel):
    name: str = Field(
        description="风险规则注册名，例如 `stop_loss` 或 `trailing_stop`。"
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="规则初始化参数字典，也支持传入 dataclass 或 Pydantic 配置对象。",
    )
    alias: Optional[str] = Field(
        default=None, description="可选别名，便于日志、接口展示或区分多个同类规则实例。"
    )

    @field_validator("params", mode="before")
    @classmethod
    def _normalize_params(cls, value: Any) -> Dict[str, Any]:
        return _params_to_plain_dict(value)


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


def validate_risk_rule_params(name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if name not in RISK_RULE_REGISTRY:
        raise ValueError(f"Unsupported risk rule name: {name}")
    rule_cls = RISK_RULE_REGISTRY[name]
    return _validate_callable_params(
        rule_cls.__init__,
        params,
        f"{rule_cls.__name__}Params",
        exclude={"self"},
    )


def normalize_risk_rule_spec(spec: RiskRuleSpec) -> RiskRuleSpec:
    return spec.model_copy(
        update={"params": validate_risk_rule_params(spec.name, spec.params)}
    )


def get_risk_rule_params_schema(name: str) -> Dict[str, Any]:
    if name not in RISK_RULE_REGISTRY:
        raise ValueError(f"Unsupported risk rule name: {name}")
    rule_cls = RISK_RULE_REGISTRY[name]
    return _schema_from_callable(
        rule_cls.__init__,
        f"{rule_cls.__name__}Params",
        exclude={"self"},
    )


def list_risk_rule_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "params_schema": get_risk_rule_params_schema(name),
        }
        for name in RISK_RULE_REGISTRY
    ]


def build_risk_rules(specs: List[RiskRuleSpec]) -> List[RiskRule]:
    rules: List[RiskRule] = []
    for spec in specs:
        normalized = normalize_risk_rule_spec(spec)
        rule_cls = RISK_RULE_REGISTRY[normalized.name]
        rules.append(rule_cls(**normalized.params))
    return rules
