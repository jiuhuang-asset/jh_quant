import pandas as pd
from rich.console import Console
from rich.table import Table
from datetime import datetime

console = Console()


def rprint(label: str, content: str, add_datetime: bool = True):
    if add_datetime:
        template = (
            "[dim]{}[/dim] [bold blue]{}[/bold blue]: [bold green]{}[/bold green]"
        )
        args = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), label, content]
    else:
        template = "[bold blue][{}][/bold blue]: [bold green]{}[/bold green]"
        args = [label, content]

    console.print(template.format(*args))


def highlight_table(data: pd.DataFrame, title: str):
    console.print(f"[bold blue]{title}[/bold blue]")
    table = Table(show_header=True, header_style="bold magenta")

    table.add_column("Index", style="dim")
    for col in data.columns:
        table.add_column(str(col), style="dim")

    # Process each row to highlight max and min values
    for idx, row in data.iterrows():
        row_cells = [str(idx)]

        # Find max and min values in the current row (excluding index column)
        numeric_values = pd.to_numeric(row, errors="coerce")
        max_val = numeric_values.max()
        min_val = numeric_values.min()

        for col in data.columns:
            val = row[col]
            str_val = str(round(val, 2))

            # Check if the value is max or min and apply appropriate style
            if pd.api.types.is_numeric_dtype(data[col]) and pd.notna(val):
                if val == max_val:
                    row_cells.append(f"[bold green]{str_val}[/bold green]")
                elif val == min_val:
                    row_cells.append(f"[bold red]{str_val}[/bold red]")
                else:
                    row_cells.append(str_val)
            else:
                # For non-numeric values, just add as is
                row_cells.append(str_val)

        table.add_row(*row_cells)

    console.print(table)


# 辅助函数
def filter_buy_signal_by_fundamental_condition(
    fundamental_data: pd.DataFrame, conditions: str
):
    def filter_func(candidates: pd.DataFrame) -> pd.DataFrame:
        if fundamental_data.empty or conditions == "":
            return candidates

        assert "symbol" in fundamental_data.columns
        data = pd.merge(candidates, fundamental_data, on="symbol", how="left")
        try:
            data = data.query(conditions)
            return data

        except Exception as e:
            rprint(
                "Error",
                "Data Filtering error applying condition'{}': {}".format(
                    conditions, str(e)
                ),
            )
            return candidates

    return filter_func


def filter_st(
    fundamental_data: pd.DataFrame
):
    def filter_func(candidates: pd.DataFrame) -> pd.DataFrame:
        if fundamental_data.empty:
            return candidates

        assert "symbol" in fundamental_data.columns
        data = pd.merge(candidates, fundamental_data[["symbol", "symbol_name"]], on="symbol", how="left")
        try:
            data =  data[~data["symbol_name"].str.contains("ST", case=True)]
            return data

        except Exception as e:
            rprint(
                "Error",
                f"Data Filtering error applying ST filtering: {e.args}")
            return candidates

    return filter_func

def filter_buy_signal_by_industry(
    fundamental_data: pd.DataFrame,
    max_candidate_per_industry: int = 2,
):
    def filter_func(candidates: pd.DataFrame) -> pd.DataFrame:
        if candidates.empty:
            return candidates
            
        result = candidates.copy()
        
        # Add industry info if missing
        if "industry" not in result.columns:
            if not fundamental_data.empty and "industry" in fundamental_data.columns:
                result = result.merge(
                    fundamental_data[["symbol", "industry"]],
                    on="symbol",
                    how="left",
                )
            else:
                rprint("Warning:", "No industry information available")
                return result
        
        # Simple and efficient: group by industry and take top N by score
        result_filtered = (
            result.sort_values("score", ascending=False)
            .groupby("industry")
            .head(max_candidate_per_industry)
            .reset_index(drop=True)
        )
        
        rprint(
            "Info:",
            f"Industry risk filter: {len(result)} → {len(result_filtered)} candidates"
        )
        
        # Clean up temporary industry column
        if "industry" in result_filtered.columns and "industry" not in candidates.columns:
            result_filtered = result_filtered.drop("industry", axis=1)
            
        return result_filtered
    
    return filter_func



# 实现一个标准化
def normalize_score(score_series: pd.Series) -> pd.Series:
    """
    Normalize a score series to have a mean of 1.

    Parameters:
    score_series (pd.Series): Series containing the scores to be normalized.

    Returns:
    pd.Series: Normalized score series with mean = 1.
    """
    # Calculate the mean of the current scores
    mean_score = score_series.mean()

    # Normalize the scores so that the mean becomes 1
    normalized_scores = score_series / mean_score

    return normalized_scores


def adjust_buy_score_by_fundamentals(
    fundamental_data: pd.DataFrame,
    adjust_factors: list[str],
    default_rank_factor: float = 0.1,
):
    def adjust_score_func(candidates: pd.DataFrame):
        result = candidates.copy()

        for factor_name in adjust_factors:
            factor_col = f"{factor_name}_rank_in_industry"
            if factor_col not in fundamental_data.columns:
                rprint(
                    label="Warning:",
                    content=f"Factor {factor_col} not found in fundamental data",
                )
                continue

            # 合并基本面数据
            result = result.merge(
                fundamental_data[["symbol", factor_col]].rename(
                    columns={factor_col: f"{factor_name}_rank"}
                ),
                on="symbol",
                how="left",
            )

            # 计算调整因子（排名越高，因子越接近1）
            result[f"{factor_name}_factor"] = (
                1 - result[f"{factor_name}_rank"]
            ).fillna(default_rank_factor)

            # 应用调整
            result["score"] = (
                result["score"] * result[f"{factor_name}_factor"]
            )  # factor 是0到1
            result["score"] = normalize_score(result["score"])
            # 清理临时列
            result = result.drop(
                [f"{factor_name}_rank", f"{factor_name}_factor"], axis=1
            )

        return result

    return adjust_score_func



