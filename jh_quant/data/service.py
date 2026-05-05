"""
DuckDB-as-a-Service server process.

Started as a subprocess by ServiceManager. Runs a FastAPI app with uvicorn.
Maintains a single long-lived DuckDB connection for all operations.
"""

import os
import sys
import time
import json
import threading
import signal
import argparse
import re

import duckdb
import pandas as pd
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv

from .data_types import (
    DataTypes,
    get_table_fields,
    get_table_unique_keys,
    get_table_dt_field,
)
from .data import (
    _build_filter_sql,
    _get_provider_prefix,
    _get_filter_field,
)

load_dotenv()

# ---- Global state ----
_db_conn: duckdb.DuckDBPyConnection = None
_db_lock: threading.Lock = None
_db_path: str = None
_api_key: str = None
_api_url: str = None
_start_time: float = None
_idle_timeout: int = 300
_last_activity: float = None
_port_file: str = None


def get_db() -> duckdb.DuckDBPyConnection:
    return _db_conn


def _init_table(data_type_str: str) -> None:
    """Initialize table from DDL (fetched from remote API)."""
    table_name = data_type_str
    conn = get_db()
    result = conn.execute(
        f"SELECT count(*) FROM information_schema.tables WHERE table_name = '{table_name}'"
    ).fetchone()[0]
    if result > 0:
        return

    client = httpx.Client(timeout=30)
    client.headers.update({"Authorization": f"Bearer {_api_key}"})
    try:
        resp = client.get(
            f"{_api_url}/data-offline/ddl",
            params={"data_types": [data_type_str]},
        )
        if resp.status_code == 200:
            ddl_dict = resp.json()["data"]
            ddl = ddl_dict.get(data_type_str)
            if ddl:
                seq_match = re.search(r"nextval\('(\w+)'\)\)?", ddl)
                if seq_match:
                    try:
                        conn.execute(
                            f"CREATE SEQUENCE IF NOT EXISTS {seq_match.group(1)}"
                        )
                    except Exception:
                        pass
                conn.execute(ddl)
    finally:
        client.close()


def _bulk_import(data_type_str: str, data: pd.DataFrame) -> int:
    """Upsert data into the table. Returns number of rows imported."""
    if data.empty:
        return 0

    table_name = data_type_str
    dt = DataTypes(data_type_str)
    unique_keys = get_table_unique_keys(dt)
    table_fields = get_table_fields(dt)
    conn = get_db()

    data = data.replace("NaN", None)
    if unique_keys:
        data = data.drop_duplicates(subset=unique_keys, keep="first")

    conn.register("temp_df", data)
    try:
        data_columns = list(data.columns)
        insert_columns = [col for col in table_fields if col in data_columns]
        if not insert_columns:
            return 0
        column_list = ", ".join([f'"{col}"' for col in insert_columns])

        if unique_keys:
            update_columns = [col for col in insert_columns if col not in unique_keys]
            if update_columns:
                update_set = ", ".join([f'EXCLUDED."{col}"' for col in update_columns])
                update_names = ", ".join([f'"{col}"' for col in update_columns])
                merge_sql = f"""
                    INSERT INTO {table_name} ({column_list})
                    SELECT {column_list} FROM temp_df
                    ON CONFLICT ({', '.join([f'"{key}"' for key in unique_keys])})
                    DO UPDATE SET ({update_names}) = ({update_set})
                """
            else:
                merge_sql = f"""
                    INSERT INTO {table_name} ({column_list})
                    SELECT {column_list} FROM temp_df
                    ON CONFLICT ({', '.join([f'"{key}"' for key in unique_keys])})
                    DO NOTHING
                """
            conn.execute(merge_sql)
        else:
            conn.execute(
                f"INSERT INTO {table_name} ({column_list}) SELECT {column_list} FROM temp_df"
            )
    finally:
        conn.unregister("temp_df")

    return len(data)


# ---- FastAPI app ----


def create_app() -> FastAPI:
    app = FastAPI(title="JHData DuckDB Service")

    @app.get("/health")
    def health():
        return {"status": "ok", "uptime_seconds": time.time() - _start_time}

    @app.middleware("http")
    async def track_activity(request: Request, call_next):
        global _last_activity
        _last_activity = time.time()
        response = await call_next(request)
        return response

    @app.post("/query")
    def query(req: dict):
        data_type_str = req["data_type"]
        kwargs = req.get("kwargs", {})
        dt = DataTypes(data_type_str)
        with _db_lock:
            _init_table(data_type_str)

            where_sql = _build_filter_sql(dt, kwargs)
            dt_field = get_table_dt_field(dt)
            order_clause = f"ORDER BY {dt_field}" if dt_field else "ORDER BY id"

            sql = f"SELECT * FROM {data_type_str} {where_sql} {order_clause}"
            conn = get_db()
            df = conn.sql(sql).to_df()
            df.drop(columns=["id", "created_at"], errors="ignore", inplace=True)
        return {"data": df.to_dict(orient="records"), "row_count": len(df)}

    @app.post("/count")
    def count(req: dict):
        data_type_str = req["data_type"]
        kwargs = req.get("kwargs", {})
        dt = DataTypes(data_type_str)
        with _db_lock:
            _init_table(data_type_str)

            where_sql = _build_filter_sql(dt, kwargs)
            sql = f"SELECT count(*) FROM {data_type_str} {where_sql}"
            conn = get_db()
            count_val = conn.execute(sql).fetchone()[0]
        return {"count": int(count_val)}

    @app.post("/import")
    def import_data(req: dict):
        data_type_str = req["data_type"]
        data = pd.DataFrame(req["data"])
        with _db_lock:
            n = _bulk_import(data_type_str, data)
        return {"status": "ok", "row_count": n}

    @app.post("/clear")
    def clear(req: dict):
        data_type_str = req["data_type"]
        with _db_lock:
            conn = get_db()
            conn.execute(f"TRUNCATE TABLE {data_type_str}")
        return {"status": "ok"}

    @app.post("/init")
    def init_table(req: dict):
        data_type_str = req["data_type"]
        with _db_lock:
            _init_table(data_type_str)
        return {"status": "ok"}

    @app.post("/shutdown")
    def shutdown():
        threading.Thread(target=_delayed_shutdown, daemon=True).start()
        return {"status": "shutting_down"}

    return app


def _delayed_shutdown():
    time.sleep(0.5)
    if _port_file and os.path.exists(_port_file):
        try:
            os.remove(_port_file)
        except OSError:
            pass
    os._exit(0)


def _idle_monitor_loop():
    """Background daemon thread: exit process if idle too long."""
    while True:
        time.sleep(30)
        if time.time() - _last_activity > _idle_timeout:
            if _port_file and os.path.exists(_port_file):
                try:
                    os.remove(_port_file)
                except OSError:
                    pass
            os._exit(0)


def _cleanup(signum=None, frame=None):
    if _port_file and os.path.exists(_port_file):
        try:
            os.remove(_port_file)
        except OSError:
            pass
    os._exit(0)


def main():
    global _db_conn, _db_lock, _db_path, _api_key, _api_url, _start_time
    global _last_activity, _idle_timeout, _port_file

    _db_lock = threading.Lock()

    parser = argparse.ArgumentParser(description="JHData DuckDB Service")
    parser.add_argument("--port", type=int, default=19876)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--api-url", default="https://data.jiuhuang.xyz")
    parser.add_argument("--idle-timeout", type=int, default=300)
    args = parser.parse_args()

    _db_path = args.db_path or os.path.expanduser("~/.jiuhuang/cache_data.db")
    _api_key = args.api_key or os.getenv("JIUHUANG_API_KEY")
    _api_url = args.api_url
    _idle_timeout = int(
        os.environ.get("DUCKDB_SERVICE_IDLE_TIMEOUT", str(args.idle_timeout))
    )
    _start_time = time.time()
    _last_activity = time.time()

    # Ensure cache directory exists
    os.makedirs(os.path.dirname(_db_path), exist_ok=True)

    # Open the single persistent DuckDB connection
    _db_conn = duckdb.connect(_db_path)

    # Write port file for service discovery
    _port_file = os.path.expanduser("~/.jiuhuang/service.port")
    os.makedirs(os.path.dirname(_port_file), exist_ok=True)
    with open(_port_file, "w") as f:
        f.write(f"{os.getpid()}:{args.port}")

    # Start idle monitor thread
    monitor = threading.Thread(target=_idle_monitor_loop, daemon=True)
    monitor.start()

    # Handle termination signals
    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    try:
        app = create_app()
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    finally:
        if _db_conn:
            _db_conn.close()
        if _port_file and os.path.exists(_port_file):
            try:
                os.remove(_port_file)
            except OSError:
                pass


if __name__ == "__main__":
    main()
