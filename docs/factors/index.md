# jh_quant.factors 用户文档

`jh_quant.factors` 是多因子模型计算框架，支持 **11种** 主流学术因子模型的因子收益率计算、个股暴露度估计和统计验证。

## 核心特性

- **11 种因子模型**：CAPM、FF3、FF5、Carhart、Novy-Marx、Hou-Xue-Zhang (q-factor)、DHS、CH3、SY4、Reversal、Low Vol
- **两种计算方法**：SIMPLE（简化版，等权 + 中位数分组）和 CLASSIC（经典版，市值加权 + 分位数分组）
- **日频/月频**：支持月度（`M`）和日度（`D`）因子计算
- **高性能**：支持 Polars 加速 + joblib 多进程并行
- **暴露度估计**：OLS 回归计算个股在因子上的 Beta 暴露，支持滚动窗口
- **因子验证**：截距项 t 检验 + Fama-MacBeth 两步回归

## 文档导航

| 文档 | 内容 |
|------|------|
| [快速开始](./quickstart.md) | 安装配置、基本用法、环境变量 |
| [因子模型介绍](./factor-models.md) | 11 种因子模型详解、因子含义、学术来源 |
| [计算方法详解](./calculation.md) | SIMPLE vs CLASSIC、参数调优、性能优化 |
| [暴露计算与验证](./exposure.md) | 个股 Beta 计算、Fama-MacBeth 验证 |
