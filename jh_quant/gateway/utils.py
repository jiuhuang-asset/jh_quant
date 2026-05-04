import re
from datetime import datetime

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

_ERROR_RE = re.compile(r"error|错误", re.IGNORECASE)
_WARNING_RE = re.compile(r"warning|警告", re.IGNORECASE)


def rprint(label: str, content: str, add_datetime: bool = True):
    if _ERROR_RE.search(label) or _ERROR_RE.search(content):
        label_color, content_color = "bold red", "bold red"
    elif _WARNING_RE.search(label) or _WARNING_RE.search(content):
        label_color, content_color = "bold yellow", "bold yellow"
    else:
        label_color, content_color = "bold blue", "bold green"

    if add_datetime:
        template = "[dim]{}[/dim] [{}]{}[/{}]: [{}]{}[/{}]"
        args = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            label_color,
            label,
            label_color,
            content_color,
            content,
            content_color,
        ]
    else:
        template = "[{}]{}[/{}]: [{}]{}[/{}]"
        args = [label_color, label, label_color, content_color, content, content_color]

    console.print(template.format(*args))


def print_service_startup_summary(
    *,
    session_id: str,
    mode: str,
    host: str,
    port: int,
    timezone: str,
    auto_start: bool,
    interval_seconds: int,
    cron_expression: str | None = None,
) -> None:
    """Print a compact startup summary for the SignalGateway service."""
    base_url = f"http://{host}:{port}"
    scheduler_mode = (
        f"Cron: {cron_expression}"
        if cron_expression
        else f"Interval: {interval_seconds}s"
    )

    summary_table = Table.grid(padding=(0, 2))
    summary_table.add_column(style="cyan", justify="right")
    summary_table.add_column(style="white")
    summary_table.add_row("Mode", mode)
    summary_table.add_row("Session", session_id)
    summary_table.add_row("Scheduler", scheduler_mode)
    summary_table.add_row("Auto Start", "ON" if auto_start else "OFF")
    summary_table.add_row("Timezone", timezone)

    endpoint_table = Table.grid(padding=(0, 2))
    endpoint_table.add_column(style="green", justify="right")
    endpoint_table.add_column(style="white")
    endpoint_table.add_row("API", base_url)
    endpoint_table.add_row("Health", f"{base_url}/health")
    endpoint_table.add_row("Status", f"{base_url}/service/status")

    console.print(
        Panel.fit(
            summary_table,
            title="SignalGateway Service",
            border_style="blue",
        )
    )
    console.print(
        Panel.fit(
            endpoint_table,
            title="Endpoints",
            border_style="green",
        )
    )
    if auto_start:
        console.print("[bold green]Scheduler auto-start is enabled.[/bold green]")
    else:
        console.print(
            "[bold yellow]Scheduler auto-start is disabled.[/bold yellow] "
            "Use POST /service/scheduler/start when ready."
        )


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
