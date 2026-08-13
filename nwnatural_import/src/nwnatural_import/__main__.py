"""CLI entrypoint: scrape NW Natural gas usage → HA long-term statistics.

Imports two statistics per run:
  - <prefix>:gas_consumption in ft³ (therms × 100)
  - <prefix>:gas_cost in USD (billed amount per month)
Both are month-bucketed, timestamped at the meter-read date.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from .ha_client import HAClient, StatisticEntry
from .scraper import NWNaturalScraper, ScraperOptions
from .state import State

log = logging.getLogger("nwnatural_import")


BACKFILL_VERSION = 1  # bump when data model changes incompatibly

# NW Natural bills in therms; HA Energy dashboard accepts ft³ / m³ / kWh
# for gas. We convert therms → ft³ using the standard 1 therm = 100 ft³
# (1000 BTU per ft³, 100 000 BTU per therm) approximation. Close enough
# for consumption tracking — actual heating value varies ±1%.
FT3_PER_THERM = 100.0


async def run(mode: str, *, data_dir: Path, opts: ScraperOptions, ha: HAClient,
              statistic_id: str, statistic_name: str,
              cost_statistic_id: str, cost_statistic_name: str) -> None:
    state = State.load(data_dir / "state.json")

    async with NWNaturalScraper(opts) as scraper:
        readings = await scraper.fetch_gas_readings()

    if not readings:
        log.warning("scraper returned no readings — nothing to import")
        return

    readings.sort(key=lambda r: r.read_date)
    log.info("Parsed %d monthly readings (%s → %s)",
             len(readings), readings[0].read_date, readings[-1].read_date)

    consumption_entries: list[StatisticEntry] = []
    cost_entries: list[StatisticEntry] = []
    cumulative_ft3 = 0.0
    cumulative_cost = 0.0
    for r in readings:
        ft3 = r.therms * FT3_PER_THERM
        cumulative_ft3 += ft3
        cumulative_cost += r.total_bill_usd or 0.0
        start = _midnight_utc(r.read_date)
        consumption_entries.append(StatisticEntry(
            start=start, state=ft3, sum=cumulative_ft3,
        ))
        if r.total_bill_usd is not None:
            cost_entries.append(StatisticEntry(
                start=start, state=r.total_bill_usd, sum=cumulative_cost,
            ))

    async with ha:
        if mode == "backfill":
            log.info("clearing existing gas + cost statistics before backfill")
            await ha.clear_statistics([statistic_id, cost_statistic_id])

        await ha.import_statistics(
            statistic_id=statistic_id,
            name=statistic_name,
            unit="ft³",
            source=statistic_id.split(":", 1)[0],
            stats=consumption_entries,
        )
        log.info("imported %d gas-consumption points (ft³)", len(consumption_entries))

        if cost_entries:
            await ha.import_statistics(
                statistic_id=cost_statistic_id,
                name=cost_statistic_name,
                unit="USD",
                source=cost_statistic_id.split(":", 1)[0],
                stats=cost_entries,
            )
            log.info("imported %d gas-cost points (USD)", len(cost_entries))


        # Heartbeat for stale-import alerting (no-op if helper missing).
        await ha.touch_heartbeat("input_datetime.nwnatural_last_import")

    # Persist state.
    now = datetime.now().astimezone()
    if mode == "backfill":
        state.last_backfill = now
        state.backfill_version = BACKFILL_VERSION
    state.last_incremental = now
    state.cumulative_wh = cumulative_ft3            # repurposed field: cumulative ft³
    state.latest_interval_start = _midnight_utc(readings[-1].read_date)
    state.save(data_dir / "state.json")


def _midnight_utc(d) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["backfill", "incremental"], required=True)
    parser.add_argument("--data-dir", default=os.environ.get("DATA_DIR", "/data"))
    parser.add_argument("--statistic-id",
                        default=os.environ.get("STATISTIC_ID", "nwnatural:gas_consumption"))
    parser.add_argument("--statistic-name",
                        default=os.environ.get("STATISTIC_NAME", "NW Natural gas consumption"))
    parser.add_argument("--cost-statistic-id",
                        default=os.environ.get("COST_STATISTIC_ID", "nwnatural:gas_cost"))
    parser.add_argument("--cost-statistic-name",
                        default=os.environ.get("COST_STATISTIC_NAME", "NW Natural gas cost"))
    # Scraper opts
    parser.add_argument("--username", default=os.environ.get("NW_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("NW_PASSWORD"))
    parser.add_argument("--account-no", default=os.environ.get("NW_ACCOUNT_NO"))
    parser.add_argument("--headed", action="store_true")
    # HA opts
    parser.add_argument("--ha-url", default=os.environ.get("HA_URL"))
    parser.add_argument("--ha-token", default=os.environ.get("HA_TOKEN"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if not args.username or not args.password:
        raise SystemExit("Set NW_USERNAME / NW_PASSWORD (env or --flags)")

    data_dir = Path(args.data_dir)
    opts = ScraperOptions(
        username=args.username, password=args.password,
        storage_dir=data_dir / "browser",
        account_no=args.account_no,
        headless=not args.headed,
    )

    if args.ha_url and args.ha_token:
        ha = HAClient(args.ha_url, args.ha_token)
    elif os.environ.get("SUPERVISOR_TOKEN"):
        ha = HAClient.for_supervisor()
    else:
        raise SystemExit("Provide --ha-url + --ha-token, or run inside an HA add-on with SUPERVISOR_TOKEN")

    asyncio.run(run(
        args.mode, data_dir=data_dir, opts=opts, ha=ha,
        statistic_id=args.statistic_id, statistic_name=args.statistic_name,
        cost_statistic_id=args.cost_statistic_id, cost_statistic_name=args.cost_statistic_name,
    ))


if __name__ == "__main__":
    main()
