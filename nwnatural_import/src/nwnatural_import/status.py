"""Persistent last-run bookkeeping and status snapshot computation."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

BadgeState = Literal["backfilling", "up-to-date", "error"]

GRACE_DAYS = 35
LAST_RUN_FILE = Path(os.environ.get("DATA_DIR", "/data")) / "last_run.json"


@dataclass
class LastRun:
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    mode: Optional[str] = None
    ok: Optional[bool] = None
    error: Optional[str] = None


@dataclass
class StatusSnapshot:
    state: BadgeState
    newest_data_date: Optional[str]
    last_run_started_at: Optional[str]
    last_run_finished_at: Optional[str]
    last_run_ok: Optional[bool]
    last_error: Optional[str]
    last_error_at: Optional[str]
    next_run_at: Optional[str]
    schedule_cron: Optional[str]


def load_last_run(path: Path = LAST_RUN_FILE) -> LastRun:
    try:
        raw = json.loads(path.read_text())
        return LastRun(
            started_at=raw.get("started_at"),
            finished_at=raw.get("finished_at"),
            mode=raw.get("mode"),
            ok=raw.get("ok"),
            error=raw.get("error"),
        )
    except Exception:
        return LastRun()


def save_last_run(lr: LastRun, path: Path = LAST_RUN_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(lr), indent=2))
    os.replace(tmp, path)


def compute(state, last_run: LastRun, cron_expr: Optional[str], now: datetime) -> StatusSnapshot:
    newest = None
    lis = getattr(state, "latest_interval_start", None)
    if lis is not None:
        newest = lis.date() if hasattr(lis, "date") else None

    if last_run.ok is False:
        badge: BadgeState = "error"
    elif newest is None or newest < (now.date() - timedelta(days=GRACE_DAYS)):
        badge = "backfilling"
    else:
        badge = "up-to-date"

    next_run = None
    if cron_expr:
        from croniter import croniter
        next_run = croniter(cron_expr, now).get_next(datetime).isoformat()

    return StatusSnapshot(
        state=badge,
        newest_data_date=newest.isoformat() if newest is not None else None,
        last_run_started_at=last_run.started_at,
        last_run_finished_at=last_run.finished_at,
        last_run_ok=last_run.ok,
        last_error=last_run.error,
        last_error_at=last_run.finished_at if last_run.ok is False else None,
        next_run_at=next_run,
        schedule_cron=cron_expr,
    )
