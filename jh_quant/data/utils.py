from rich.console import Console
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


def get_ak_exchange_from_code(stock_code: str):
    if stock_code.startswith(("600", "601", "603", "688")):
        return "sh"
    elif stock_code.startswith(("000", "002", "300", "003")):
        return "sz"
    elif stock_code.startswith(("430", "830", "870", "880")):
        return "bj"
    else:
        return "Unknown Exchange"


def ak_symbol_to_ts_code(stock_code: str):
    """
    将Akshare的股票代码转换为Tushare的股票代码(A股)
    """
    exchange = get_ak_exchange_from_code(stock_code)
    if exchange == "Unknown Exchange":
        return stock_code
    return f"{stock_code}.{exchange.upper()}"


def ts_code_to_ak_symbol(ts_code: str):
    """
    将Tushare的股票代码转换为Akshare的股票代码(A股)
    """
    if "." in ts_code:
        return ts_code.split(".")[0]
    return ts_code


def _delete_cache_data(
    data_type,
    ts_code: str = "",
    start: str = "",
    end: str = "",
    symbol: str = "",
    dry_run: bool = False,
    **kwargs,
) -> int:
    """删除本地 DuckDB 缓存中指定数据类型的数据。

    Args:
        data_type: 数据类型，``DataTypes`` 枚举或其字符串值
            （如 ``DataTypes.TS_DAILY`` / ``"ts_daily"``），与 ``get_data`` 语义一致。
        ts_code: 代码筛选（ts_ 源格式，如 ``000001.SZ``；ak_/jh_ 源会自动映射到 symbol 列）。
        symbol: 代码筛选（ak_/jh_ 源格式，如 ``000001``）。
        start: 起始日期筛选（按该表的时间字段）。
        end: 结束日期筛选。
        dry_run: 只统计将删除的行数，不实际删除。
        **kwargs: 其他字段筛选（键为表字段名，值做等值匹配）。

    Returns:
        删除（或将删除）的行数。
    """
    # 延迟导入，避免 utils 顶层引入重模块 / 循环依赖
    from .data import JHData, _get_filter_field
    from .data_types import DataTypes

    # 统一成 DataTypes 枚举（与 get_data 一致，避免暴露具体表名）
    if isinstance(data_type, DataTypes):
        dt = data_type
    else:
        try:
            dt = DataTypes(data_type)
        except ValueError:
            raise ValueError(
                f"无效的数据类型: {data_type!r}。请用 `DataTypes` 枚举或它的值，如 'ts_daily'。"
            )

    filter_kwargs = dict(kwargs)
    # 代码列规范化：ts_code / symbol → 该表真实的代码列名
    code_val = ts_code or symbol
    if not code_val:
        code_val = filter_kwargs.pop("ts_code", "") or filter_kwargs.pop("symbol", "")
    if code_val:
        filter_kwargs[_get_filter_field(dt)] = code_val
    if start:
        filter_kwargs["start"] = start
    if end:
        filter_kwargs["end"] = end

    jd = JHData()
    if dry_run:
        return jd.count_cache(dt, **filter_kwargs)
    return jd.delete_cache(dt, **filter_kwargs)
