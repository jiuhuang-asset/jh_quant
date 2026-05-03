# jh_quant.data 用户文档

`jh_quant.data` 是 jh_quant 的数据获取模块，基于 **JiuHuang Data API** 提供统一的金融数据访问接口，同时兼容 **akshare** 和 **tushare** 的调用风格。

## 核心特性

- **统一数据接口**：通过 `JHData` 类和 `DataTypes` 枚举统一访问 360+ 种金融数据类型
- **本地缓存**：内置 DuckDB 缓存，相同查询不会重复请求 API，支持增量同步
- **自动分片**：大数据量请求自动按时间/标的分片下载，避免内存溢出
- **多源兼容**：无缝兼容 akshare 和 tushare 调用风格，方便迁移

## 文档导航

| 文档 | 内容 |
|------|------|
| [快速开始](./quickstart.md) | 安装配置、基本用法、环境变量设置 |
| [DataTypes 介绍](./datatypes.md) | 数据类型前缀规则、分类概览、常用数据示例 |
| [get_data 详解](./get-data.md) | 时间参数、symbol 批量查询、缓存机制、分片下载 |
| [akshare/tushare 兼容](./compatibility.md) | 兼容接口使用、参数映射、数据格式转换 |
