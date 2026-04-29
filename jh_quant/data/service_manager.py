"""
Service lifecycle manager for the DuckDB-as-a-Service process.

Handles discovery, startup, health-checking, and shutdown of the
background DuckDB service subprocess.
"""

import os
import sys
import time
import threading
import subprocess
from typing import Optional

import httpx


class ServiceManager:
    """Manages the lifecycle of the DuckDB service subprocess."""

    DEFAULT_PORT = 19876
    PORT_FILE = os.path.expanduser("~/.jiuhuang/service.port")
    STARTUP_TIMEOUT = 15  # seconds to wait for service to be ready

    _start_lock = threading.Lock()
    _process: Optional[subprocess.Popen] = None

    # ---- Discovery ----

    @classmethod
    def discover(cls) -> Optional[str]:
        """
        Find a running DuckDB service. Returns the service URL or None.

        Priority:
        1. DUCKDB_SERVICE_URL env var
        2. Port file at ~/.jiuhuang/service.port (with health check)
        3. Fixed default port (with health check)
        """
        # 1. Environment variable
        env_url = os.environ.get("DUCKDB_SERVICE_URL")
        if env_url:
            return env_url.rstrip("/")

        # 2. Port file
        port = cls._read_port_file()
        if port:
            url = f"http://127.0.0.1:{port}"
            if cls._health_check(url):
                return url

        # 3. Fixed default port
        url = f"http://127.0.0.1:{cls.DEFAULT_PORT}"
        if cls._health_check(url):
            return url

        return None

    @classmethod
    def _read_port_file(cls) -> Optional[int]:
        """Read port from the port file, if it exists and looks valid."""
        if not os.path.exists(cls.PORT_FILE):
            return None
        try:
            with open(cls.PORT_FILE, "r") as f:
                content = f.read().strip()
            _pid_str, port_str = content.split(":")
            return int(port_str)
        except (ValueError, OSError):
            return None

    @classmethod
    def _health_check(cls, url: str, timeout: float = 0.3) -> bool:
        """Check if a DuckDB service is alive at the given URL."""
        try:
            resp = httpx.get(f"{url}/health", timeout=timeout)
            return resp.status_code == 200
        except Exception:
            return False

    # ---- Lifecycle ----

    @classmethod
    def start_service(cls, port: int = DEFAULT_PORT) -> str:
        """
        Start the DuckDB service subprocess and wait until it's healthy.
        Returns the service URL. Raises RuntimeError on failure.
        """
        # Find an available port if the default is in use
        actual_port = cls._find_available_port(port)

        cmd = [
            sys.executable,
            "-m",
            "jh_quant.data.service",
            "--port",
            str(actual_port),
            "--host",
            "127.0.0.1",
        ]
        try:
            cls._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to start DuckDB service: {e}")

        url = f"http://127.0.0.1:{actual_port}"
        deadline = time.time() + cls.STARTUP_TIMEOUT
        while time.time() < deadline:
            if cls._health_check(url, timeout=0.3):
                return url
            if cls._process.poll() is not None:
                raise RuntimeError(
                    f"DuckDB service process exited prematurely (code {cls._process.returncode})"
                )
            time.sleep(0.3)

        # Timeout: kill the process and raise
        cls._process.kill()
        cls._process.wait()
        raise RuntimeError(
            f"DuckDB service did not become healthy within {cls.STARTUP_TIMEOUT}s"
        )

    @classmethod
    def _find_available_port(cls, start_port: int, max_attempts: int = 10) -> int:
        """Find an available port starting from start_port."""
        import socket

        for offset in range(max_attempts):
            port = start_port + offset
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    continue
        return start_port  # fallback, will likely fail

    @classmethod
    def ensure_running(cls, port: int = DEFAULT_PORT) -> str:
        """
        Discover an already-running service or start a new one.
        Thread-safe: uses double-checked locking.
        Returns the service URL.
        """
        url = cls.discover()
        if url is not None:
            return url

        with cls._start_lock:
            url = cls.discover()
            if url is not None:
                return url
            return cls.start_service(port)

    @classmethod
    def stop_service(cls, url: str) -> bool:
        """Send shutdown request to the service. Returns True if successful."""
        try:
            resp = httpx.post(f"{url}/shutdown", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    @classmethod
    def get_recovery_callback(cls, port: int = DEFAULT_PORT):
        """Return a callable suitable for _DataCacheProxy.on_connection_error."""
        return lambda: cls.ensure_running(port)
