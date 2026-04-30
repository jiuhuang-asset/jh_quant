# JH_QUANT
量化交易研究与执行平台。支持：**数据获取**、**回测**、**因子计算**、**信号网关**、**可视化仪表盘**

- **官网**: https://data.jiuhuang.xyz
- **文档**: https://doc.jiuhuang.xyz


## 模块
| 模块 | 说明 | 文档 |
|------|------|------|
| [data](docs/data.md) | 数据获取，同时兼容akshare和tushare数据接口 | [README](docs/data.md) |
| [backtest](docs/backtest.md) | 回测引擎，11种内置策略 | [README](docs/backtest.md) |
| [factors](docs/factors.md) | 因子计算，FF3/FF5/Carhart等学术模型 | [README](docs/factors.md) |
| [gateway](docs/gateway.md) | 交易网关，订单管理，FastAPI服务 | [README](docs/gateway.md) |
| [dashboard](docs/dashboard.md) | PyWebView可视化仪表盘 | [README](docs/dashboard.md) |

## 快速开始
### 安装
```bash
pip install jh_quant
```

### 数据获取

```python
from dotenv import load_dotenv
from jh_quant.data import JHData, DataTypes

load_dotenv()   # 读取.env文件, 必须设置JIUHUANG_API_KEY变量

jh = JHData()
stock_price = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    symbol="000001",
    start="2025-01-01",
    end="2025-12-10",
)
```
兼容akshare和tushare数据获取接口, 详细见文档: [jh_quant.data](docs/data.md)  
更多功能请查看各自模块文档或者访问逛网。


## License
This project is licensed under the BSD 3-Clause License - see the [LICENSE](LICENSE) file for details.

