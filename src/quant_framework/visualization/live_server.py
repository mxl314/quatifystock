from __future__ import annotations

import json
import logging
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Protocol

from .chart import render_chart_html
from .models import ChartData
from .repository import SQLiteChartRepository


class ChartProvider(Protocol):
    def snapshot(self) -> ChartData: ...


class _ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(
                socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1,
            )
        super().server_bind()


class DatabaseChartProvider:
    def __init__(
        self,
        database: str,
        contract: str,
        interval_seconds: int,
        trading_day: str | None = None,
    ) -> None:
        self.repository = SQLiteChartRepository(database)
        self.contract = contract
        self.interval_seconds = interval_seconds
        self.trading_day = trading_day

    def snapshot(self) -> ChartData:
        return self.repository.load(
            self.contract, self.interval_seconds, self.trading_day,
        )


class LiveChartServer:
    def __init__(
        self,
        provider: ChartProvider,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        self.provider = provider
        self.host = host
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._log = logging.getLogger(__name__)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def start(self) -> None:
        if self._server is not None:
            return
        provider = self.provider
        logger = self._log

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
                try:
                    if self.path.split("?", 1)[0] == "/api/chart":
                        payload = json.dumps(
                            provider.snapshot().as_dict(), ensure_ascii=False,
                        ).encode("utf-8")
                        self._send(200, "application/json; charset=utf-8", payload)
                    elif self.path.split("?", 1)[0] in {"/", "/index.html"}:
                        payload = render_chart_html(
                            provider.snapshot(), api_url="/api/chart",
                        ).encode("utf-8")
                        self._send(200, "text/html; charset=utf-8", payload)
                    else:
                        self._send(404, "text/plain; charset=utf-8", "未找到".encode())
                except Exception as exc:
                    logger.exception("生成实时K线响应失败")
                    self._send(
                        500, "application/json; charset=utf-8",
                        json.dumps({"error": str(exc)}, ensure_ascii=False).encode(),
                    )

            def _send(self, status: int, content_type: str, payload: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *_args) -> None:
                return

        self._server = _ExclusiveThreadingHTTPServer((self.host, self.port), Handler)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="chart-server", daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None
        self._server = None
