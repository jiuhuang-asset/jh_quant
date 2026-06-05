"""启动模拟盘服务。

查看参数说明：
    uv run python run_paper.py --help

示例：
    uv run python run_paper.py --strategy turtle,momentum --backend tushare
"""

from __future__ import annotations

from jh_quant.trading.bootstrap import run_paper_from_cli


def main() -> None:
    run_paper_from_cli()


if __name__ == "__main__":
    main()
