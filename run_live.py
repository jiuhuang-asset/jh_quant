"""启动实盘服务。

实盘需要先配置 MiniQMT / xtquant 环境变量：
    MINIQMT_USERDATA_DIR
    MINIQMT_STOCK_ACCOUNT

查看参数说明：
    uv run python run_live.py --help

示例：
    uv run python run_live.py --backend xquant --strategy turtle
"""

from __future__ import annotations

from jh_quant.trading.bootstrap import run_live_from_cli


def main() -> None:
    run_live_from_cli()


if __name__ == "__main__":
    main()
