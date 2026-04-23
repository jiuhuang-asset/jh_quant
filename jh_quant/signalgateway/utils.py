import pandas as pd
from rich.console import Console
from datetime import datetime

console = Console()


def rprint(label: str, content: str, add_datetime: bool = True):
    label_lower = label.lower()
    if "error" in label_lower:
        label_color, content_color = "bold red", "bold red"
    elif "warning" in label_lower:
        label_color, content_color = "bold yellow", "bold yellow"
    else:
        label_color, content_color = "bold blue", "bold green"

    if add_datetime:
        template = (
            "[dim]{}[/dim] [{}]{}[/{}]: [{}]{}[/{}]"
        )
        args = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), label_color, label, label_color, content_color, content, content_color]
    else:
        template = "[{}]{}[/{}]: [{}]{}[/{}]"
        args = [label_color, label, label_color, content_color, content, content_color]

    console.print(template.format(*args))


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





