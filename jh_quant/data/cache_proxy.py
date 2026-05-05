"""
Client-side HTTP proxy for DuckDB cache operations.

Provides the same interface as _DataCache but forwards all operations
to a DuckDB service process over HTTP.
"""

from typing import Callable, Optional
import pandas as pd
import httpx

from .data_types import DataTypes


class _DataCacheProxy:
    """HTTP proxy for _DataCache — same interface, forwards to DuckDB service."""

    def __init__(
        self,
        service_url: str,
        jd: "JHData" = None,
        on_connection_error: Optional[Callable[[], str]] = None,
    ):
        self._service_url = service_url.rstrip("/")
        self._client = httpx.Client(timeout=120)
        self._on_connection_error = on_connection_error

    def _request(self, method: str, path: str, **kwargs):
        """Make an HTTP request to the service, with one retry on connection error or 502/503."""
        url = f"{self._service_url}{path}"
        try:
            resp = self._client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except (httpx.ConnectError, httpx.RemoteProtocolError):
            if self._on_connection_error:
                new_url = self._on_connection_error()
                self._service_url = new_url.rstrip("/")
                url = f"{self._service_url}{path}"
                resp = self._client.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp.json()
            raise
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (502, 503) and self._on_connection_error:
                new_url = self._on_connection_error()
                self._service_url = new_url.rstrip("/")
                url = f"{self._service_url}{path}"
                resp = self._client.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp.json()
            raise

    def get_data(self, data_type: DataTypes, **kwargs) -> pd.DataFrame:
        body = self._request(
            "POST",
            "/query",
            json={"data_type": data_type.value, "kwargs": kwargs},
        )
        data = body.get("data", [])
        if not data:
            return pd.DataFrame()
        return pd.DataFrame(data)

    def get_data_total(self, data_type: DataTypes, **kwargs) -> int:
        body = self._request(
            "POST",
            "/count",
            json={"data_type": data_type.value, "kwargs": kwargs},
        )
        return body["count"]

    def bulk_import(self, data_type: DataTypes, data: pd.DataFrame) -> None:
        if data.empty:
            return
        data = data.replace("NaN", None)
        self._request(
            "POST",
            "/import",
            json={
                "data_type": data_type.value,
                "data": data.to_dict(orient="records"),
            },
        )

    def _clear_table(self, data_type: DataTypes) -> None:
        self._request(
            "POST",
            "/clear",
            json={"data_type": data_type.value},
        )

    def close(self):
        self._client.close()
