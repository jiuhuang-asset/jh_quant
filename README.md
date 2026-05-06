# JH_QUANT

![banner](assets/banner_sm.png)
量化交易研究与执行平台。支持：**免费数据获取**、**回测**、**因子计算**、 **模拟交易**、**持仓优化**、**信号网关**、**可视化仪表盘**

- **官网**: https://jiuhuang.xyz
- **文档**: https://doc.jiuhuang.xyz

## 模块

| 模块                           | 说明                                                           | 文档                              |
| ------------------------------ | -------------------------------------------------------------- | --------------------------------- |
| [data](docs/data.md)           | 多种数据获取，兼容akshare和tushare数据类型及调用风格 | [README](docs/data/index.md)      |
| [gateway](docs/gateway.md)     | 交易网关，模拟(实时)交易                                       | [README](docs/gateway/index.md)   |
| [backtest](docs/backtest.md)   | 回测引擎，快速策略验证，多种内置策略                           | [README](docs/backtest/index.md)  |
| [factors](docs/factors.md)     | 因子计算，内置多种因子模型                                     | [README](docs/factors/index.md)   |
| [dashboard](docs/dashboard.md) | PyWebView可视化仪表盘                                          | [README](docs/dashboard/index.md) |

## 快速开始

### 安装

```bash
pip install jh_quant
```

### 数据获取

```python
import os
from jh_quant.data import JHData, DataTypes

load_dotenv()   # 读取.env文件, 必须设置JIUHUANG_API_KEY变量

jh = JHData(apt_key=os.getenv("JIUHUANG_API_KEY"))
stock_price = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,  #akshare日线前复盘数据
    symbol="000001",
    start="2025-01-01",
    end="2025-12-10",
)
```

**重要**

> `jh_quant` 的数据获取**并非**像 [akshare](https://github.com/akfamily/akshare) 那样需要实时抓取数据。  
> `jh_quant` 仅做了对 [akshare](https://github.com/akfamily/akshare) 数据类型的兼容，数据真实来源为：[JiuHuang API](https://jiuhuang.xyz)

> 兼容[akshare](https://github.com/akfamily/akshare)和[tushare](https://github.com/waditu/tushare)的数据类型和调用风格, 详细见文档: [数据兼容](docs/data/compatibility.md)  
> 注意：请优先使用akshare数据源, tushare数据源的完整支持仍在进展中...

### 实时模拟交易

**jh_quant**支持同时开启多个模拟交易会话，每个会话对应一个模拟账户, 下面是示例运行:

```bash
python run_paper.py
```

*run_paper.py*的完整代码参考本repo根目录的[run_paper.py](./run_paper.py)

**开启控制台仪表盘**

```python
from jh_quant.dashboard import display_gateway

display_gateway()
```

![dashboard](assets/screenshots/gateway_sessions_sm.png)

## License

This project is licensed under the AGPL-3.0 License - see the [LICENSE](LICENSE) file for details.
