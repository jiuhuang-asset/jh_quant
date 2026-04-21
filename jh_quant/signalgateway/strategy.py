from jh_quant.backtest.strategy import (
    Strategy,
    StrategyTurtle,
    StrategyMovingAverageCrossover,
    StrategyBuyAndHold,
    StrategyVolumeTrend,
    StrategyVolumeDivergence,
    StrategyMeanReversion,
)
from itertools import product


def buildStrategyGrid(strat_class: list[Strategy]) -> dict:
    """Build a grid of strategy instances with all parameter combinations."""
    strategies = {}

    for strategy in strat_class:
        param_grid = strategy.get_possible_params()
        param_values = list(product(*param_grid.values()))

        for param_combination in param_values:
            param_dict = dict(zip(param_grid.keys(), param_combination))
            strat_instance = strategy(**param_dict)
            strat_name = f"{strategy.__name__}_" + "_".join(
                f"{k}{v}" for k, v in param_dict.items()
            )
            strategies[strat_name] = strat_instance
    return strategies