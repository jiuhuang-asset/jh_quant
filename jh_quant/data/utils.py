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

def get_ak_exchange_from_code(stock_code:str):
    if stock_code.startswith(("600", "601", "603", "688")):
        return "sh"
    elif stock_code.startswith(("000", "002", "300", "003")):
        return "sz"
    elif stock_code.startswith(("430", "830", "870", "880")):
        return "bj"
    else:
        return "Unknown Exchange"
    
def ak_symbol_to_ts_code(stock_code:str):
    """
    将Akshare的股票代码转换为Tushare的股票代码(A股)
    """
    exchange = get_ak_exchange_from_code(stock_code)
    if exchange == "Unknown Exchange":
        return stock_code
    return f"{stock_code}.{exchange.upper()}"   


def ts_code_to_ak_symbol(ts_code:str):
    """
    将Tushare的股票代码转换为Akshare的股票代码(A股)
    """
    if "." in ts_code:
        return ts_code.split(".")[0]
    return ts_code