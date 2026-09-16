from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from .models import ChartData


def render_chart_html(data: ChartData, *, api_url: str = "") -> str:
    template = (
        files("quant_framework.visualization")
        .joinpath("templates/kline.html")
        .read_text(encoding="utf-8")
    )
    payload = json.dumps(data.as_dict(), ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    return template.replace("__CHART_DATA__", payload).replace(
        "__CHART_API_URL__", json.dumps(api_url),
    )


def write_chart_report(data: ChartData, output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_chart_html(data), encoding="utf-8")
    return path.resolve()
