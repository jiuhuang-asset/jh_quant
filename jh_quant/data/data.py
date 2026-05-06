import re
import httpx
import json
import sys
import pandas as pd
import os
from os import getenv
from dotenv import load_dotenv
from datetime import datetime
from typing import Tuple, TypeVar, Generator
import duckdb
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
)
from rich import print as rprint
from .data_types import (
    DataTypes,
    get_table_fields,
    get_table_unique_keys,
    get_table_dt_field,
)


load_dotenv()

__all__ = ["JHData", "DataTypes", "get_code_col", "get_code_date_col"]


# Provider prefix to filter field mappings
PROVIDER_FILTER_FIELDS = {
    "ak_": "symbol",
    "ts_": "ts_code",
    "jh_": "symbol",  # TODO: verify for jh provider
}

# Date format patterns by provider prefix
PROVIDER_DATE_PATTERNS = {
    "ak_": [
        (r"^\d{4}-\d{2}-\d{2}$", "YYYY-MM-DD"),
        (r"^\d{4}-(0[1-9]|1[0-2])$", "YYYY-MM"),
        (r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", "YYYY-MM-DD HH:MM:SS"),
    ],
    "ts_": [
        (r"^\d{4}-\d{2}-\d{2}$", "YYYY-MM-DD"),
    ],
    "jh_": [
        (r"^\d{4}-\d{2}-\d{2}$", "YYYY-MM-DD"),
    ],
}


def _get_provider_prefix(data_type: DataTypes) -> str:
    """Extract provider prefix from data_type value."""
    value = data_type.value
    for prefix in PROVIDER_FILTER_FIELDS.keys():
        if value.startswith(prefix):
            return prefix
    # Default to ak_ for types without prefix
    return "ak_"


def _get_filter_field(data_type: DataTypes) -> str:
    """Get the filter field name (symbol or ts_code) for the data type."""
    prefix = _get_provider_prefix(data_type)
    return PROVIDER_FILTER_FIELDS.get(prefix, "symbol")


def _validate_date_by_provider(
    date_str: str, param_name: str, data_type: DataTypes
) -> None:
    """Validate date parameter format based on provider prefix."""
    if not date_str:
        return

    prefix = _get_provider_prefix(data_type)
    patterns = PROVIDER_DATE_PATTERNS.get(prefix, PROVIDER_DATE_PATTERNS["ak_"])

    for pattern, date_msg in patterns:
        import re

        if re.match(pattern, date_str):
            return

    # Default error message
    date_msg = (
        "YYYY-MM-DD"
        if prefix == "ts_"
        else "YYYY-MM-DD, YYYY-MM, or YYYY-MM-DD HH:MM:SS"
    )
    raise ValueError(
        f"Invalid date format for '{param_name}': '{date_str}'. Expected format: {date_msg}"
    )


def raise_err_with_details(response, read_body: bool = True) -> None:
    """
    检查响应状态，如果出错则抛出包含具体错误信息的异常。

    替代 response.raise_for_status()，能解析响应体中的错误信息。

    Args:
        response: httpx.Response 对象
        read_body: 是否读取响应体获取错误详情。流式响应应设为 False
    """
    if response.status_code >= 400:
        error_msg = f"HTTP {response.status_code}"
        # 流式响应需要特殊处理：先消费流或使用 text 属性
        if read_body:
            try:
                # 对于流式响应，需要读取完整内容
                if hasattr(response, "stream"):
                    # 流式响应：先读取完整内容
                    error_body = response.read().decode("utf-8")
                else:
                    error_body = response.text
                error_data = json.loads(error_body)
                error_msg = error_data.get("detail", error_body)
            except (json.JSONDecodeError, ValueError):
                error_msg = (
                    error_body if "error_body" in dir() else response.text or error_msg
                )
        raise Exception(f"API error {response.status_code}: {error_msg}")


def _assign_dt(func):
    def wrapper(*args, **kwargs):
        data = func(*args, **kwargs)
        datatype = args[1] if len(args) > 1 else kwargs.get("data_type")
        if isinstance(data, pd.DataFrame):
            result = _JHDataWrapper(data, datatype)
        else:
            result = _JHDataWrapper(pd.DataFrame(), datatype)
        return result

    return wrapper


class _JHDataWrapper:
    """包装 DataFrame 并提供 jh_dt、code_col 等属性"""

    def __init__(self, df, datatype):
        self._df = df
        self._jh_dt = datatype

    def __repr__(self):
        # 委托给内部 DataFrame 的 repr
        return repr(self._df)

    def __str__(self):
        return str(self._df)

    def __len__(self):
        return len(self._df)

    def __getattr__(self, name):
        # 将其他属性访问委托给内部 DataFrame
        return getattr(self._df, name)

    @property
    def jh_dt(self):
        return self._jh_dt

    @property
    def code_col(self) -> str:
        return get_code_col(self._df)

    @property
    def date_col(self) -> str:
        return get_date_col(self._df)

    @property
    def code_date_col(self) -> Tuple[str, str]:
        return get_code_date_col(self._df)

    @property
    def values(self):
        return self._df.values

    @property
    def columns(self):
        return self._df.columns

    def __getitem__(self, key):
        return self._df[key]

    def __iter__(self):
        return iter(self._df)

    def to_df(self) -> pd.DataFrame:
        """返回内部的 pandas DataFrame"""
        return self._df

    @property
    def code_col(self) -> str:
        """获取DataFrame的code列名"""
        return get_code_col(self._df)

    @property
    def code_date_col(self) -> Tuple[str, str]:
        """获取DataFrame的code列名和date列名"""
        return get_code_date_col(self._df)


JhDataType = _JHDataWrapper


def get_code_col(df: pd.DataFrame) -> str:
    """获取DataFrame的code列名"""
    code_col, _ = get_code_date_col(df)
    return code_col


def get_date_col(df: pd.DataFrame) -> str:
    """获取DataFrame的date列名"""
    _, date_col = get_code_date_col(df)
    return date_col


def get_code_date_col(df: pd.DataFrame) -> Tuple[str, str]:
    datatype = getattr(df, "_jh_dt", None)

    if datatype is None:
        # Fallback: infer from columns
        if "ts_code" in df.columns and "trade_date" in df.columns:
            return "ts_code", "trade_date"
        elif "symbol" in df.columns and "date" in df.columns:
            return "symbol", "date"
        elif "symbol" in df.columns and "dt" in df.columns:
            return "symbol", "dt"
        elif "symbol" in df.columns:
            # Check for any date-like column
            for col in ["date", "dt", "trade_date", "datetime"]:
                if col in df.columns:
                    return "symbol", col
        return "symbol", "date"  # Default

    if datatype in {DataTypes.TS_STK_MINS}:
        return "ts_code", "trade_time"

    if datatype in {DataTypes.TS_DAILY, DataTypes.TS_DAILY_HFQ, DataTypes.TS_DAILY_HFQ}:
        return "ts_code", "trade_date"

    if datatype in {
        DataTypes.AK_STOCK_ZH_A_HIST,
        DataTypes.AK_STOCK_ZH_A_HIST_HFQ,
        DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    }:
        return "symbol", "date"

    if datatype in {DataTypes.AK_STOCK_ZH_A_SPOT}:
        return "symbol", "dt"

    if datatype.value.startswith("ak"):
        return "symbol", "date"
    if datatype.value.startswith("ts"):
        return "ts_code", "trade_date"

    return "symbol", "date"  # Default


class JHData:
    SMALL_DOWNLOAD_THRESHOLD = 500_000
    INCREMENTAL_BATCH_SIZE = 50_000

    def __init__(
        self,
        api_key: str = getenv("JIUHUANG_API_KEY"),
        api_url: str = getenv("JIUHUANG_API_URL", "https://data.jiuhuang.xyz"),
        as_service: bool | None = None,
    ):
        self.api_key = api_key
        self.api_url = api_url
        self._prepare_client(api_key)

        if as_service is None:
            # Auto mode: try direct, fall back to service if DB is locked
            try:
                self._cache = _DataCache(jd=self)
            except RuntimeError:
                from .service_manager import ServiceManager
                from .cache_proxy import _DataCacheProxy

                service_url = ServiceManager.ensure_running()
                rprint("[yellow]缓存数据库被占用，自动切换到 DuckDB 服务模式[/yellow]")
                self._cache = _DataCacheProxy(
                    service_url,
                    jd=self,
                    on_connection_error=ServiceManager.get_recovery_callback(),
                )
        elif as_service:
            from .service_manager import ServiceManager
            from .cache_proxy import _DataCacheProxy

            service_url = ServiceManager.ensure_running()
            self._cache = _DataCacheProxy(
                service_url,
                jd=self,
                on_connection_error=ServiceManager.get_recovery_callback(),
            )
        else:
            self._cache = _DataCache(jd=self)

    def _prepare_client(self, api_key: str):
        client = httpx.Client(timeout=180)
        client.headers.update({"Authorization": f"Bearer {api_key}"})
        self._client = client

    def get_data_total(
        self,
        data_type: DataTypes,
        **kwargs,
    ):
        payload = {
            "data_type": data_type.value,
        }
        payload.update(kwargs)
        response = self._client.post(f"{self.api_url}/data-offline/total", json=payload)

        raise_err_with_details(response)
        total = response.json()["data"]
        try:
            total = int(total)
        except Exception as e:
            raise e

        return total

    # ---- 可分片参数定义 ----
    # 时间类参数：按日期范围二分
    _DATE_PARAMS = ("start", "end")
    # 列表类参数：按列表中元素分组二分
    _LIST_PARAMS = ("symbol", "ts_code")

    def _find_splittable_param(self, payload: dict) -> str | None:
        """从 payload 中找到第一个可二分的参数"""
        # 优先检查时间范围
        for p in self._DATE_PARAMS:
            if p in payload and payload[p]:
                return p
        # 再检查列表类参数（逗号分隔的字符串）
        for p in self._LIST_PARAMS:
            val = payload.get(p)
            if val and isinstance(val, str) and "," in val:
                return p
        return None

    def _bisect_date_range(
        self, start: str, end: str
    ) -> Generator[Tuple[str, str], None, None]:
        """将日期范围递归地按自然边界二分（年/季度/月），产出子范围"""
        s = datetime.strptime(start, "%Y-%m-%d")
        e = datetime.strptime(end, "%Y-%m-%d")
        if s >= e:
            return

        mid_year = (s.year + e.year) // 2
        if mid_year == s.year:
            # 同一年内，按月切
            mid = datetime(s.year, min(s.month + 1, 12), 1)
        else:
            mid = datetime(mid_year, 1, 1)

        yield (start, mid.strftime("%Y-%m-%d"))
        yield (mid.strftime("%Y-%m-%d"), end)

    def _bisect_list_param(
        self, value: str, param_name: str
    ) -> Generator[dict, None, None]:
        """将逗号分隔的列表参数二分"""
        items = [s.strip() for s in value.split(",") if s.strip()]
        n = len(items)
        if n <= 1:
            return
        mid = n // 2
        left = ",".join(items[:mid])
        right = ",".join(items[mid:])
        yield {param_name: left}
        yield {param_name: right}

    def _bisect_payload(self, payload: dict) -> list[dict] | None:
        """尝试对 payload 进行二分，返回子 payload 列表（None=不可二分）"""
        splittable = self._find_splittable_param(payload)
        if splittable is None:
            return None

        if splittable in self._DATE_PARAMS:
            start = payload.get("start")
            end = payload.get("end")
            if not start or not end:
                return None
            sub_ranges = list(self._bisect_date_range(start, end))
            if len(sub_ranges) < 2:
                return None
            base = {k: v for k, v in payload.items() if k not in ("start", "end")}
            return [{**base, "start": r[0], "end": r[1]} for r in sub_ranges]
        elif splittable in self._LIST_PARAMS:
            val = payload[splittable]
            sub_params = list(self._bisect_list_param(val, splittable))
            if len(sub_params) < 2:
                return None
            base = {k: v for k, v in payload.items() if k != splittable}
            return [{**base, **p} for p in sub_params]

        return None

    def _download_single(
        self,
        data_type: DataTypes,
        total: int,
        payload: dict,
        write_cache: bool = False,
    ) -> pd.DataFrame:
        """单次请求下载全部数据（<= SMALL_DOWNLOAD_THRESHOLD 时使用）"""
        url = f"{self.api_url}/data-offline/"
        all_data = []
        with self._client.stream("POST", url, json=payload) as response:
            raise_err_with_details(response, read_body=True)
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(),
            ) as progress:
                task_id = progress.add_task(
                    f"[cyan]Downloading {data_type}...", total=total
                )
                for chunk in response.iter_lines():
                    if chunk:
                        try:
                            resp = json.loads(chunk)
                            data = resp["data"]
                            all_data.extend(data)
                            progress.update(task_id, completed=len(all_data))
                        except json.JSONDecodeError:
                            raise Exception("获取数据失败[Json解码错误]")
        df = pd.DataFrame(all_data)
        if write_cache and not df.empty:
            self._cache.bulk_import(data_type, df)
        return df

    def _download_incremental(
        self,
        data_type: DataTypes,
        total: int,
        payload: dict,
        write_cache: bool = True,
    ) -> pd.DataFrame:
        """流式下载，按需增量写入缓存，并返回下载结果。"""
        url = f"{self.api_url}/data-offline/"
        batch = []
        downloaded = 0
        parts = []

        def flush_batch():
            nonlocal batch, downloaded, parts
            if batch:
                df_batch = pd.DataFrame(batch)
                if write_cache:
                    self._cache.bulk_import(data_type, df_batch)
                parts.append(df_batch)
                downloaded += len(batch)
                batch = []

        with self._client.stream("POST", url, json=payload) as response:
            raise_err_with_details(response, read_body=True)
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(),
            ) as progress:
                task_id = progress.add_task(
                    f"[cyan]Downloading {data_type}...", total=total
                )
                for chunk in response.iter_lines():
                    if chunk:
                        try:
                            resp = json.loads(chunk)
                            data = resp["data"]
                            batch.extend(data)
                            progress.update(task_id, completed=downloaded + len(batch))
                            if len(batch) >= self.INCREMENTAL_BATCH_SIZE:
                                flush_batch()
                        except json.JSONDecodeError:
                            raise Exception("获取数据失败[Json解码错误]")
        flush_batch()
        if not parts:
            return pd.DataFrame()
        return pd.concat(parts, ignore_index=True)

    def _fetch_recursive(
        self,
        data_type: DataTypes,
        payload: dict,
        total: int,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """
        递归二分下载：
        1. total <= SMALL_DOWNLOAD_THRESHOLD → 直接下载写入缓存，返回结果
        2. 尝试二分 payload：
           - 能二分 → 递归下载每个子范围，合并结果
           - 不能二分 → 超过阈值则报错；未超阈值则直接下载
        """
        if total <= self.SMALL_DOWNLOAD_THRESHOLD:
            return self._download_single(
                data_type,
                total,
                payload,
                write_cache=use_cache,
            )

        sub_payloads = self._bisect_payload(payload)
        if sub_payloads is None:
            # 没有任何可分片参数，数据量又超大 → 无法处理
            raise MemoryError(
                f"数据量({total})超过阈值({self.SMALL_DOWNLOAD_THRESHOLD})，"
                f"且请求参数无法拆分。请提供 start/end 日期范围参数以启用分片下载。"
            )
        parts = []
        for sub in sub_payloads:
            filter_kwargs = {k: v for k, v in sub.items() if k != "data_type"}
            sub_total = self.get_data_total(data_type, **filter_kwargs)
            if sub_total == 0:
                continue

            # 检查本地缓存数量，避免重复下载
            if use_cache:
                cache_count = self._cache.get_data_total(data_type, **filter_kwargs)
                if cache_count >= sub_total:
                    rprint(f"[green]    cache hit, skip: {sub}[/green]")
                    parts.append(self._cache.get_data(data_type, **filter_kwargs))
                    continue

            rprint(f"[dim]    sub range: {sub}[/dim]")
            parts.append(
                self._fetch_recursive(
                    data_type,
                    sub,
                    sub_total,
                    use_cache=use_cache,
                )
            )

        if not parts:
            return pd.DataFrame()
        return pd.concat(parts, ignore_index=True)

    @_assign_dt
    def get_data(
        self,
        data_type: DataTypes,
        bypass_cache: bool = False,
        **kwargs,
    ):
        """
        从 JiuHuang API 获取离线数据。

        Args:
            data_type: 数据类型
            bypass_cache: 是否绕过缓存直接从远程获取

        支持自动分片：当远程数据量超过阈值且存在 start/end 日期参数
        或逗号分隔的列表参数时，会递归二分参数范围；仅在 bypass_cache=False 时增量写入缓存。
        """
        remote_data_count = self.get_data_total(data_type=data_type, **kwargs)
        if remote_data_count == 0:
            rprint(
                f"[bold yellow]Remote没有数据({data_type}), 请检查参数[/bold yellow]"
            )
            return

        # 缓存命中检查
        if not bypass_cache:
            cached = self._cache.get_data(data_type, **kwargs)
            if len(cached) == remote_data_count:
                return cached
            if len(cached) > remote_data_count:
                self.clear_cache(data_type)  # remote should always be the root source

        rprint(f"[cyan]Pulling data from JiuHuang API...[/cyan]")

        payload = {"data_type": data_type.value, **kwargs}

        if remote_data_count > self.SMALL_DOWNLOAD_THRESHOLD:
            sub_payloads = self._bisect_payload(payload)
            if sub_payloads is None:
                raise MemoryError(
                    f"Remote数据量({remote_data_count})超过阈值({self.SMALL_DOWNLOAD_THRESHOLD})，"
                    f"且请求参数无法拆分。请提供 start/end 日期范围参数以启用分片下载。"
                )

        fetched = self._fetch_recursive(
            data_type,
            payload,
            remote_data_count,
            use_cache=not bypass_cache,
        )

        if bypass_cache:
            return fetched
        return self._cache.get_data(data_type, **kwargs)

    def clear_cache(self, data_type: DataTypes):
        """清除指定数据类型的本地缓存（truncate表）"""
        self._cache._clear_table(data_type)


def _build_filter_sql(data_type: DataTypes, kwargs: dict) -> str:
    """构建 WHERE 条件SQL片段 (module-level, shared with DuckDB service)"""
    prefix = _get_provider_prefix(data_type)
    filter_field = _get_filter_field(data_type)
    dt_field = get_table_dt_field(data_type)

    _validate_date_by_provider(kwargs.get("start"), "start", data_type)
    _validate_date_by_provider(kwargs.get("end"), "end", data_type)

    sql = "WHERE 1=1"

    if "start" in kwargs and kwargs["start"] and dt_field:
        sql += f" AND {dt_field} >= '{kwargs['start']}'"

    if "end" in kwargs and kwargs["end"] and dt_field:
        sql += f" AND {dt_field} <= '{kwargs['end']}'"

    if (
        filter_field in kwargs
        and kwargs[filter_field]
        and filter_field in get_table_fields(data_type)
    ):
        filter_value = kwargs[filter_field]
        if prefix == "ak_" or prefix == "jh_":
            _validate_symbol(filter_value)
        if isinstance(filter_value, str) and "," in filter_value:
            values = [s.strip() for s in filter_value.split(",")]
            value_list = ", ".join([f"'{v}'" for v in values])
            sql += f" AND {filter_field} IN ({value_list})"
        else:
            sql += f" AND {filter_field} = '{filter_value}'"
    return sql


class _DataCache:
    def __init__(self, jd: JHData):
        self.cache_dir = os.path.expanduser("~/.jiuhuang")
        self.cache_db_path = os.path.join(self.cache_dir, "cache_data.db")
        self._jd = jd
        self._initialize_cache()

    def _initialize_cache(self):
        os.makedirs(self.cache_dir, exist_ok=True)

        try:
            conn = duckdb.connect(self.cache_db_path)
        except Exception as e:
            raise RuntimeError(
                f"无法连接缓存数据库({self.cache_db_path})，可能被其他进程占用"
            ) from e

        conn.close()

    def _init_table(self, data_type: DataTypes):
        """按需初始化表：如果表不存在则从API获取DDL并创建"""
        table_name = data_type.value
        conn = duckdb.connect(self.cache_db_path)
        try:
            # 检查表是否已存在
            result = conn.execute(
                f"SELECT count(*) FROM information_schema.tables WHERE table_name = '{table_name}'"
            ).fetchone()[0]
            if result > 0:
                conn.close()
                return

            # 表不存在，从API获取DDL
            resp = self._jd._client.get(
                self._jd.api_url + "/data-offline/ddl",
                params={"data_types": [data_type.value]},
            )
            if resp.status_code == 200:
                ddl_dict = resp.json()["data"]
                ddl = ddl_dict.get(data_type.value)
                if ddl:
                    # 创建 sequence（如果DDL中有）
                    seq_match = re.search(r"nextval\('(\w+)'\)\)?", ddl)
                    if seq_match:
                        seq_name = seq_match.group(1)
                        try:
                            conn.execute(f"CREATE SEQUENCE IF NOT EXISTS {seq_name}")
                        except Exception:
                            pass
                    # 执行DDL创建表
                    conn.execute(ddl)
        finally:
            conn.close()

    def get_data(self, data_type: DataTypes, **kwargs):
        self._init_table(data_type)

        table_name = data_type.value
        where_sql = _build_filter_sql(data_type, kwargs)

        dt_field = get_table_dt_field(data_type)
        order_clause = f"ORDER BY {dt_field}" if dt_field else "ORDER BY id"

        sql = f"SELECT * FROM {table_name} {where_sql} {order_clause}"
        conn = duckdb.connect(self.cache_db_path)
        data = conn.sql(sql).to_df()
        conn.close()
        data.drop(columns=["id", "created_at"], errors="ignore", inplace=True)
        return data

    def get_data_total(self, data_type: DataTypes, **kwargs):
        self._init_table(data_type)

        table_name = data_type.value
        where_sql = _build_filter_sql(data_type, kwargs)
        sql = f"SELECT count(*) FROM {table_name} {where_sql}"

        conn = duckdb.connect(self.cache_db_path)
        count = conn.execute(sql).fetchone()[0]
        conn.close()
        return count

    def bulk_import(self, data_type: DataTypes, data: pd.DataFrame):
        """批量导入数据到缓存（支持 upsert）

        Args:
            data_type: 表名
            data: pandas DataFrame
        """
        if data.empty:
            return
        table_name = data_type.value
        data = data.replace("NaN", None)

        # 获取 unique_keys
        unique_keys = get_table_unique_keys(data_type)
        if unique_keys:
            data = data.drop_duplicates(subset=unique_keys, keep="first")

        conn = duckdb.connect(self.cache_db_path)
        try:
            # 注册临时 DataFrame
            conn.register("temp_df", data)

            # 获取表字段
            table_fields = get_table_fields(data_type)

            if unique_keys:
                # Upsert 模式：使用 MERGE 语句
                self._bulk_upsert_df(conn, table_name, unique_keys, table_fields, data)
                rprint(
                    f"[green]Successfully upserted {len(data)} records into {table_name}"
                )
            else:
                self._bulk_insert_df(conn, table_name, table_fields, data)
                rprint(
                    f"[green]Successfully inserted {len(data)} records into {table_name}"
                )

        except Exception as e:
            rprint(f"[bold red]Error importing data: {e}")
            raise
        finally:
            conn.unregister("temp_df")
            conn.close()

    def _bulk_insert_df(
        self,
        conn,
        table_name: str,
        table_fields: list,
        data: pd.DataFrame,
    ):
        """简单批量插入（无冲突处理）"""
        # 只包含存在于 data 中的列
        data_columns = list(data.columns)
        insert_columns = [col for col in table_fields if col in data_columns]

        if not insert_columns:
            return

        column_list = ", ".join([f'"{col}"' for col in insert_columns])
        copy_sql = f"""
            INSERT INTO {table_name} ({column_list})
            SELECT {column_list} FROM temp_df
        """
        conn.execute(copy_sql)

    def _bulk_upsert_df(
        self,
        conn,
        table_name: str,
        unique_keys: list,
        table_fields: list,
        data: pd.DataFrame,
    ):
        """Upsert 数据到 DuckDB（基于唯一键的冲突解决）"""
        # 只包含存在于 data 中的列
        data_columns = list(data.columns)
        insert_columns = [col for col in table_fields if col in data_columns]

        if not insert_columns:
            return

        column_list = ", ".join([f'"{col}"' for col in insert_columns])

        # 构建更新列（非唯一键列）
        update_columns = [col for col in insert_columns if col not in unique_keys]

        if update_columns:
            # 使用 EXCLUDED 关键字引用新数据
            update_set_clause = ", ".join(
                [f'EXCLUDED."{col}"' for col in update_columns]
            )
            update_column_names = ", ".join([f'"{col}"' for col in update_columns])

            merge_sql = f"""
                INSERT INTO {table_name} ({column_list})
                SELECT {column_list} FROM temp_df
                ON CONFLICT ({', '.join([f'"{key}"' for key in unique_keys])})
                DO UPDATE SET ({update_column_names}) = ({update_set_clause})
            """
        else:
            # 如果没有非键列需要更新，直接忽略冲突
            merge_sql = f"""
                INSERT INTO {table_name} ({column_list})
                SELECT {column_list} FROM temp_df
                ON CONFLICT ({', '.join([f'"{key}"' for key in unique_keys])})
                DO NOTHING
            """

        try:
            conn.execute(merge_sql)
        except Exception as e:
            rprint(f"[bold red]Error executing merge statement: {e}")
            # 回退到 INSERT ... WHERE NOT EXISTS 方式
            self._fallback_upsert(conn, table_name, unique_keys, insert_columns)

    def _fallback_upsert(
        self,
        conn,
        table_name: str,
        unique_keys: list,
        insert_columns: list,
    ):
        """回退的 upsert 实现（使用 WHERE NOT EXISTS）"""
        column_list = ", ".join([f'"{col}"' for col in insert_columns])

        # 构建 WHERE NOT EXISTS 条件
        where_conditions = []
        for key in unique_keys:
            where_conditions.append(f't1."{key}" = t2."{key}"')
        where_clause = " AND ".join(where_conditions)

        insert_sql = f"""
            INSERT INTO {table_name} ({column_list})
            SELECT {column_list} FROM temp_df t1
            WHERE NOT EXISTS (
                SELECT 1 FROM {table_name} t2
                WHERE {where_clause}
            )
        """
        conn.execute(insert_sql)

    def _clear_table(self, data_type: DataTypes):
        """清除指定数据类型的本地缓存（truncate表）"""
        table_name = data_type.value
        conn = duckdb.connect(self.cache_db_path)
        try:
            conn.execute(f"TRUNCATE TABLE {table_name}")
            rprint(f"[green]Successfully truncated cache table: {table_name}[/green]")
        finally:
            conn.close()


def _validate_symbol(symbol_value: str) -> None:
    """验证 symbol 参数格式，无效则抛出 ValueError"""
    if not symbol_value:
        return

    # 如果是逗号分隔的字符串，验证每个 symbol
    if isinstance(symbol_value, str) and "," in symbol_value:
        symbols = [s.strip() for s in symbol_value.split(",")]
        for sym in symbols:
            if len(sym) > 12:
                raise ValueError(
                    f"Invalid symbol length: '{sym}' (length={len(sym)}). Symbol length must be <= 12"
                )
    else:
        # 单个 symbol
        if len(symbol_value) > 12:
            raise ValueError(
                f"Invalid symbol length: '{symbol_value}' (length={len(symbol_value)}). Symbol length must be <= 12"
            )
