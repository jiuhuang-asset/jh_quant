from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
import io
from typing import Any, Dict, Optional

import pandas as pd

from ..config import PortfolioSpec


@dataclass
class PortfolioOptimizationResult:
    optimizer: str
    symbols: list[str]
    weights: pd.DataFrame
    diagnostics: Dict[str, Any]

    def to_payload(self) -> Dict[str, Any]:
        return {
            "optimizer": self.optimizer,
            "symbols": self.symbols,
            "weights": self.weights.to_dict(orient="records"),
            "diagnostics": self.diagnostics,
        }


class RiskfolioPortfolioOptimizer:
    def _build_signal_score_map(
        self,
        signals: Optional[pd.DataFrame],
        symbols: list[str],
    ) -> pd.Series:
        if signals is None or signals.empty or "symbol" not in signals.columns:
            return pd.Series(1.0, index=symbols, dtype=float)

        score_map = (
            signals.drop_duplicates("symbol")
            .set_index("symbol")
            .get("score", pd.Series(dtype=float))
            .reindex(symbols)
            .fillna(0.0)
            .astype(float)
        )
        if float(score_map.clip(lower=0.0).sum()) <= 0:
            return pd.Series(1.0, index=symbols, dtype=float)
        return score_map

    def _redistribute_capped_weights(
        self,
        weights: pd.DataFrame,
        portfolio_spec: PortfolioSpec,
        *,
        signal_scores: pd.Series,
    ) -> pd.DataFrame:
        universe = pd.DataFrame({"symbol": list(signal_scores.index)})
        normalized = universe.merge(weights.copy(), on="symbol", how="left")
        normalized["target_weight"] = (
            normalized["target_weight"].astype(float).clip(lower=0.0)
        )
        epsilon = float(portfolio_spec.weight_epsilon)
        normalized.loc[normalized["target_weight"] < epsilon, "target_weight"] = 0.0

        total_weight = float(normalized["target_weight"].sum())
        if total_weight > 0:
            normalized["target_weight"] = normalized["target_weight"] / total_weight

        max_weight = float(portfolio_spec.max_weight)
        normalized["target_weight"] = normalized["target_weight"].clip(upper=max_weight)
        residual = max(0.0, 1.0 - float(normalized["target_weight"].sum()))

        # Fill remaining weight budget using signal ranking rather than preserving
        # infinitesimal optimizer tail weights.
        while residual > 1e-9:
            capacity = (max_weight - normalized["target_weight"]).clip(lower=0.0)
            eligible = normalized.loc[capacity > 1e-9, "symbol"]
            if eligible.empty:
                break

            eligible_scores = (
                signal_scores.reindex(eligible).fillna(0.0).clip(lower=0.0)
            )
            if float(eligible_scores.sum()) <= 0:
                eligible_scores = pd.Series(1.0, index=eligible, dtype=float)

            allocation = eligible_scores / float(eligible_scores.sum())
            allocated_any = False
            for symbol, fraction in allocation.items():
                idx = normalized.index[normalized["symbol"] == symbol][0]
                room = max_weight - float(normalized.at[idx, "target_weight"])
                if room <= 1e-9:
                    continue
                delta = min(room, residual * float(fraction))
                if delta <= 1e-9:
                    continue
                normalized.at[idx, "target_weight"] = (
                    float(normalized.at[idx, "target_weight"]) + delta
                )
                residual -= delta
                allocated_any = True

            if not allocated_any:
                break

        normalized.loc[normalized["target_weight"] < epsilon, "target_weight"] = 0.0
        normalized = normalized[normalized["target_weight"] > 0].copy()
        total_weight = float(normalized["target_weight"].sum())
        if total_weight > 0:
            normalized["target_weight"] = normalized["target_weight"] / total_weight
            normalized["target_weight"] = normalized["target_weight"].clip(
                upper=max_weight
            )
        return normalized.sort_values("target_weight", ascending=False).reset_index(
            drop=True
        )

    def optimize(
        self,
        returns: pd.DataFrame,
        portfolio_spec: PortfolioSpec,
        *,
        signals: Optional[pd.DataFrame] = None,
    ) -> PortfolioOptimizationResult:
        try:
            import riskfolio as rp
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError(
                "Riskfolio-Lib is required for portfolio optimization. Install it before using portfolio optimization."
            ) from exc

        if returns is None or returns.empty:
            raise ValueError("No return matrix available for portfolio optimization")

        clean_returns = returns.dropna(axis=1, how="any")
        if clean_returns.empty:
            raise ValueError(
                "Return matrix is empty after dropping columns with missing values"
            )

        variance = clean_returns.var()
        non_constant_symbols = variance[variance > 1e-12].index.tolist()
        clean_returns = clean_returns[non_constant_symbols]
        if clean_returns.empty:
            raise ValueError(
                "Return matrix is empty after dropping constant-return assets"
            )

        if (
            portfolio_spec.max_assets is not None
            and clean_returns.shape[1] > portfolio_spec.max_assets
        ):
            if (
                signals is not None
                and not signals.empty
                and "symbol" in signals.columns
            ):
                score_map = (
                    signals.drop_duplicates("symbol")
                    .set_index("symbol")
                    .get("score", pd.Series(dtype=float))
                )
                ordered_symbols = sorted(
                    clean_returns.columns,
                    key=lambda symbol: float(score_map.get(symbol, 0.0)),
                    reverse=True,
                )
                clean_returns = clean_returns[
                    ordered_symbols[: portfolio_spec.max_assets]
                ]
            else:
                clean_returns = clean_returns.iloc[:, : portfolio_spec.max_assets]

        signal_scores = self._build_signal_score_map(
            signals, list(clean_returns.columns)
        )
        portfolio = rp.Portfolio(returns=clean_returns)
        capture = io.StringIO()
        with redirect_stdout(capture), redirect_stderr(capture):
            portfolio.assets_stats(
                method_mu="hist", method_cov=portfolio_spec.covariance_method
            )
            weight_frame = portfolio.optimization(
                model=portfolio_spec.model,
                rm=portfolio_spec.risk_measure,
                obj=portfolio_spec.objective,
                rf=portfolio_spec.analysis.risk_free_rate,
                l=0,
                hist=True,
            )
        if weight_frame is None or weight_frame.empty:
            raise ValueError("Riskfolio-Lib returned no portfolio weights")

        weight_series = (
            weight_frame.iloc[:, 0]
            if isinstance(weight_frame, pd.DataFrame)
            else weight_frame
        )
        weights = (
            weight_series.rename("target_weight")
            .reset_index()
            .rename(columns={"index": "symbol"})
        )
        weights["target_weight"] = weights["target_weight"].astype(float)
        weights = self._redistribute_capped_weights(
            weights,
            portfolio_spec,
            signal_scores=signal_scores,
        )
        optimizer_messages = [
            line.strip() for line in capture.getvalue().splitlines() if line.strip()
        ]

        return PortfolioOptimizationResult(
            optimizer="riskfolio",
            symbols=list(clean_returns.columns),
            weights=weights,
            diagnostics={
                "rows": int(clean_returns.shape[0]),
                "asset_count": int(clean_returns.shape[1]),
                "objective": portfolio_spec.objective,
                "risk_measure": portfolio_spec.risk_measure,
                "model": portfolio_spec.model,
                "covariance_method": portfolio_spec.covariance_method,
                "weight_epsilon": float(portfolio_spec.weight_epsilon),
                "optimizer_messages": optimizer_messages,
                "effective_assets": int(len(weights)),
            },
        )


def optimize_portfolio_preview(
    returns: pd.DataFrame,
    portfolio_spec: PortfolioSpec,
    *,
    signals: Optional[pd.DataFrame] = None,
) -> PortfolioOptimizationResult:
    if portfolio_spec.optimizer != "riskfolio":
        raise ValueError(f"Unsupported portfolio optimizer: {portfolio_spec.optimizer}")
    return RiskfolioPortfolioOptimizer().optimize(
        returns, portfolio_spec, signals=signals
    )
