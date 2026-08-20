"""Tests for status.py — pure, no HA connections."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytest

from nwnatural_import.status import (
    GRACE_DAYS,
    LastRun,
    StatusSnapshot,
    compute,
    load_last_run,
    save_last_run,
)


@dataclass
class _FakeState:
    latest_interval_start: Optional[datetime] = None


_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)


def test_compute_up_to_date():
    state = _FakeState(latest_interval_start=_NOW)
    snap = compute(state, LastRun(), None, _NOW)
    assert snap.state == "up-to-date"
    assert snap.newest_data_date == "2026-08-20"


def test_compute_backfilling_when_stale():
    stale = _NOW - timedelta(days=60)
    state = _FakeState(latest_interval_start=stale)
    snap = compute(state, LastRun(), None, _NOW)
    assert snap.state == "backfilling"


def test_compute_backfilling_when_missing():
    state = _FakeState(latest_interval_start=None)
    snap = compute(state, LastRun(), None, _NOW)
    assert snap.state == "backfilling"
    assert snap.newest_data_date is None


def test_compute_error_from_last_run():
    state = _FakeState(latest_interval_start=_NOW)
    lr = LastRun(ok=False, error="login failed", finished_at="2026-08-20T11:00:00+00:00")
    snap = compute(state, lr, None, _NOW)
    assert snap.state == "error"
    assert snap.last_error == "login failed"
    assert snap.last_error_at == "2026-08-20T11:00:00+00:00"


def test_last_run_roundtrip(tmp_path):
    path = tmp_path / "last_run.json"
    lr = LastRun(
        started_at="2026-08-20T10:00:00+00:00",
        finished_at="2026-08-20T10:05:00+00:00",
        mode="incremental",
        ok=True,
        error=None,
    )
    save_last_run(lr, path)
    loaded = load_last_run(path)
    assert loaded.started_at == lr.started_at
    assert loaded.finished_at == lr.finished_at
    assert loaded.mode == lr.mode
    assert loaded.ok is True
    assert loaded.error is None


def test_last_run_missing_returns_default(tmp_path):
    path = tmp_path / "nonexistent.json"
    lr = load_last_run(path)
    assert lr == LastRun()


def test_last_run_corrupt_returns_default(tmp_path):
    path = tmp_path / "last_run.json"
    path.write_text("not valid json{{{{")
    lr = load_last_run(path)
    assert lr == LastRun()


def test_next_run_from_cron():
    # At 2026-08-20 12:00 UTC, the next 06:00 UTC is 2026-08-21 06:00 UTC.
    state = _FakeState(latest_interval_start=_NOW)
    snap = compute(state, LastRun(), "0 6 * * *", _NOW)
    assert snap.next_run_at is not None
    assert snap.next_run_at.startswith("2026-08-21T06:00:00")
    assert snap.schedule_cron == "0 6 * * *"


def test_save_last_run_is_atomic(tmp_path):
    path = tmp_path / "last_run.json"
    lr = LastRun(ok=True, mode="backfill")
    save_last_run(lr, path)
    assert path.exists()
    assert not (tmp_path / "last_run.json.tmp").exists()
    data = json.loads(path.read_text())
    assert data["ok"] is True
    assert data["mode"] == "backfill"
