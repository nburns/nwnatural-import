"""Ingress status web server."""

from __future__ import annotations

import html
import logging
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web

from . import status
from .state import State

log = logging.getLogger(__name__)

INGRESS_PORT = 8099
_DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))

_BADGE_CSS = {
    "up-to-date": "background:#2a6;color:#fff",
    "backfilling": "background:#a80;color:#fff",
    "error": "background:#c33;color:#fff",
}

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NW Natural Import</title>
<style>
body {{
  font-family: sans-serif;
  background: #1a1a1a;
  color: #d0d0d0;
  margin: 0;
  padding: 1.5em;
  max-width: 640px;
}}
h1 {{ color: #f0a040; margin-bottom: 0.5em; }}
.badge {{
  display: inline-block;
  padding: 0.2em 0.7em;
  border-radius: 4px;
  font-weight: bold;
  font-size: 0.95em;
  margin-bottom: 1em;
}}
table {{ border-collapse: collapse; width: 100%; margin-top: 1em; }}
th, td {{ text-align: left; padding: 0.4em 0.8em; border-bottom: 1px solid #333; }}
th {{ color: #888; font-weight: normal; width: 14em; }}
.error-val {{ color: #f66; }}
.hint {{ color: #666; font-size: 0.85em; margin-top: 1.5em; }}
</style>
</head>
<body>
<h1>NW Natural Import</h1>
<span class="badge badge-{state}" style="{badge_css}">{state}</span>
<table>
{rows}
</table>
{error_section}
<p class="hint">Reload the page to update.</p>
</body>
</html>
"""

_ROW = "<tr><th>{label}</th><td>{value}</td></tr>"
_ERROR_SECTION = """\
<h2 style="color:#f66;margin-top:1.2em">Last error</h2>
<p class="error-val">{error}</p>
<p style="color:#888;font-size:0.85em">At: {error_at}</p>
"""


def _ingress_prefix(request: web.Request) -> str:
    return request.headers.get("X-Ingress-Path", "").rstrip("/")


def _render_html(snap: status.StatusSnapshot, prefix: str) -> str:
    badge_css = _BADGE_CSS.get(snap.state, "background:#555;color:#fff")
    rows = []
    rows.append(_ROW.format(label="Newest data date", value=snap.newest_data_date or "—"))
    rows.append(_ROW.format(label="Last run finished", value=snap.last_run_finished_at or "—"))
    rows.append(_ROW.format(label="Last run mode", value=snap.last_run_started_at and "see log" or "—"))
    rows.append(_ROW.format(label="Next scheduled run", value=snap.next_run_at or "—"))
    rows.append(_ROW.format(label="Schedule (cron)", value=snap.schedule_cron or "—"))

    error_section = ""
    if snap.last_error:
        error_section = _ERROR_SECTION.format(
            error=html.escape(snap.last_error),
            error_at=snap.last_error_at or "—",
        )

    return _HTML_TEMPLATE.format(
        state=snap.state,
        badge_css=badge_css,
        rows="\n".join(rows),
        error_section=error_section,
    )


async def handle_status(request: web.Request) -> web.Response:
    state = State.load(_DATA_DIR / "state.json")
    lr = status.load_last_run()
    cron = os.environ.get("IMPORTER_CRON")
    snap = status.compute(state, lr, cron, datetime.now(timezone.utc))
    body = _render_html(snap, _ingress_prefix(request))
    return web.Response(text=body, content_type="text/html")


async def handle_status_json(request: web.Request) -> web.Response:
    state = State.load(_DATA_DIR / "state.json")
    lr = status.load_last_run()
    cron = os.environ.get("IMPORTER_CRON")
    snap = status.compute(state, lr, cron, datetime.now(timezone.utc))
    return web.json_response(asdict(snap))


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_status)
    app.router.add_get("/status.json", handle_status_json)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log.info("ingress web server starting on 0.0.0.0:%d", INGRESS_PORT)
    web.run_app(make_app(), host="0.0.0.0", port=INGRESS_PORT, print=None)


if __name__ == "__main__":
    main()
