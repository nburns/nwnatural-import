"""NW Natural portal scraper — logs in and scrapes the monthly gas
usage/cost table.

Unlike the electric side, NW Natural residential meters are AMR (drive-by
radio read once/month), so the max granularity is monthly billing cycles.
The portal renders an HTML table on /account/gas-usage — we scrape that
directly rather than fighting the JS-triggered "Download table" flow.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from playwright.async_api import BrowserContext, Error as PlaywrightError, Page, async_playwright

GAS_USAGE_URL = "https://www.nwnatural.com/account/gas-usage"
LOGIN_HOST = "identity.nwnatural.com"

_RETRYABLE_NET_ERRORS = (
    "ERR_NETWORK_CHANGED",
    "ERR_INTERNET_DISCONNECTED",
    "ERR_TIMED_OUT",
    "ERR_CONNECTION_RESET",
    "ERR_ABORTED",
    "ERR_NAME_NOT_RESOLVED",
)

log = logging.getLogger(__name__)


async def _goto_with_retry(page: Page, url: str, *, tries: int = 3,
                           delay_s: float | None = None) -> None:
    backoffs = [5.0, 15.0] if delay_s is None else [delay_s] * (tries - 1)
    last_exc: PlaywrightError | None = None
    for attempt in range(1, tries + 1):
        try:
            await page.goto(url, wait_until="networkidle")
            return
        except PlaywrightError as exc:
            msg = str(exc)
            if not any(code in msg for code in _RETRYABLE_NET_ERRORS):
                raise
            last_exc = exc
            log.info("page.goto transient error (attempt %d/%d): %s", attempt, tries, msg)
            if attempt < tries:
                await asyncio.sleep(backoffs[attempt - 1])
    raise last_exc  # type: ignore[misc]


@dataclass(frozen=True)
class GasReading:
    """One row from the monthly gas-use table."""
    read_date: date       # meter-read date shown in the table
    month_label: str      # e.g. "July"
    total_bill_usd: float | None
    therms: float


@dataclass
class ScraperOptions:
    username: str
    password: str
    storage_dir: Path         # persistent Chromium user-data dir
    headless: bool = True
    account_no: str | None = None   # e.g. "1234567-8"; None = accept the default
    max_years: int = 3              # NW Natural exposes up to 3 years


class NWNaturalScraper:
    def __init__(self, opts: ScraperOptions):
        self._opts = opts
        self._pw = None
        self._ctx: BrowserContext | None = None

    async def __aenter__(self) -> "NWNaturalScraper":
        self._opts.storage_dir.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()
        # Chromium's own sandbox needs privileges the add-on doesn't grant.
        self._ctx = await self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self._opts.storage_dir),
            headless=self._opts.headless,
            accept_downloads=True,
            chromium_sandbox=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-dev-shm-usage", "--no-first-run",
                  "--disable-features=Translate,MediaRouter"],
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._ctx is not None:
            await self._ctx.close()
        if self._pw is not None:
            await self._pw.stop()

    async def fetch_gas_readings(self) -> list[GasReading]:
        assert self._ctx is not None
        page = await self._ctx.new_page()
        try:
            await self._ensure_logged_in(page)
            await _goto_with_retry(page, GAS_USAGE_URL)
            if self._opts.account_no:
                await self._select_account(page, self._opts.account_no)

            # Always scrape the default view first (guaranteed ~13 months).
            default_rows = await self._scrape_table(page)

            # Best-effort date-range expansion to grab up to 3 years. If it
            # fails or the resulting table is empty, we still have the
            # default rows and haven't broken anything.
            expanded_rows: list[list[str]] = []
            try:
                await self._expand_date_range(page)
                expanded_rows = await self._scrape_table(page)
            except Exception as e:
                log.warning("date-range expansion failed: %s", e)

            rows = expanded_rows if len(expanded_rows) > len(default_rows) else default_rows
            log.info("scraped %d gas-usage rows (default=%d, expanded=%d)",
                     len(rows), len(default_rows), len(expanded_rows))
            if len(rows) == 0:
                raise RuntimeError("NW Natural returned zero rows — likely a page-render or auth issue")
            return [r for r in (_parse_row(cells) for cells in rows) if r is not None]
        finally:
            await page.close()

    async def _scrape_table(self, page: Page) -> list[list[str]]:
        try:
            await page.wait_for_selector("table tbody tr", timeout=15_000)
        except Exception:
            return []
        return await page.eval_on_selector_all(
            "table tbody tr",
            "els => els.map(tr => [...tr.querySelectorAll('td')].map(td => td.innerText.trim()))",
        )

    async def _expand_date_range(self, page: Page) -> None:
        """Set From = today - max_years, To = today, and click Submit.
        The default view only shows ~13 months; the portal exposes up to 3.
        The From/To inputs are Angular Material datepicker inputs with
        specific ids on this page."""
        today = date.today()
        from_d = today.replace(year=today.year - self._opts.max_years)
        try:
            from_input = page.locator("#startDate")
            to_input = page.locator("#endDate")
            await from_input.wait_for(state="visible", timeout=10_000)
            await from_input.fill(from_d.strftime("%m/%d/%Y"))
            await to_input.fill(today.strftime("%m/%d/%Y"))
            # There are 3 "Submit" buttons on the page: 2 are search-bar
            # submits (`.GlobalHeader__search-sub`), the third is the
            # date-range submit. Filter to just that one.
            submit = page.locator("button.Button--auto:not(.GlobalHeader__search-sub)")
            await submit.first.click()
            await page.wait_for_load_state("networkidle")
            log.info("expanded date range: %s → %s", from_d, today)
        except Exception as e:
            log.warning("could not expand date range (%s); using portal default", e)
            # If Submit left the table in a bad state, reload to reset.
            try:
                await page.goto(GAS_USAGE_URL, wait_until="networkidle")
                if self._opts.account_no:
                    await self._select_account(page, self._opts.account_no)
            except Exception as reload_err:
                log.warning("reload after failed date-range also failed: %s", reload_err)

    async def _ensure_logged_in(self, page: Page) -> None:
        await _goto_with_retry(page, GAS_USAGE_URL)
        if LOGIN_HOST not in page.url:
            log.info("Session restored — already logged in")
            return

        log.info("Not authenticated — running login flow")
        # Simple form: email + password + Sign In. Not iframed.
        await page.locator(
            'input[type="email"], input[name="Email"], input[name="Username"]'
        ).first.fill(self._opts.username)
        await page.locator('input[type="password"]').first.fill(self._opts.password)
        await page.get_by_role("button", name="Sign In").click()
        await page.wait_for_url(
            lambda u: "nwnatural.com" in u and LOGIN_HOST not in u,
            timeout=45_000,
            wait_until="networkidle",
        )
        log.info("Logged in — landed on %s", page.url)

    async def _select_account(self, page: Page, account_no: str) -> None:
        """Multi-account logins render an `AccountSelector` dropdown. It's a
        proper closed→open widget: clicking the trigger reveals the options
        list, then you click the desired account.
        Single-account logins have no picker at all — no-op in that case."""
        trigger = page.locator(".AccountSelector__trigger").first
        if await trigger.count() == 0:
            log.info("no account selector on page (single-account login?)")
            return

        # If the trigger already shows our account, we're on the right one.
        current = (await trigger.inner_text()).strip()
        if account_no in current:
            log.info("account %s already selected", account_no)
            return

        # Open the dropdown, then click the account option.
        try:
            await trigger.click()
            option = page.get_by_text(f"Account No: {account_no}", exact=False).first
            await option.wait_for(state="visible", timeout=5_000)
            await option.click()
            await page.wait_for_load_state("networkidle")
            log.info("selected account %s", account_no)
        except Exception as e:
            log.warning("account picker click failed (%s); continuing with current selection", e)


def _parse_row(cells: list[str]) -> GasReading | None:
    """Parse one table row. Columns observed: Date | Month | Total bill | Therms."""
    if len(cells) < 4:
        return None
    date_str, month_str, bill_str, therms_str = cells[0], cells[1], cells[2], cells[3]

    try:
        read_date = datetime.strptime(date_str, "%m/%d/%Y").date()
    except ValueError:
        return None

    bill = None
    if bill_str:
        m = re.search(r"[-+]?\d+(?:\.\d+)?", bill_str.replace(",", ""))
        if m:
            bill = float(m.group(0))

    try:
        therms = float(therms_str.replace(",", ""))
    except ValueError:
        therms = 0.0

    return GasReading(
        read_date=read_date,
        month_label=month_str,
        total_bill_usd=bill,
        therms=therms,
    )


if __name__ == "__main__":
    import argparse, os

    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default=os.environ.get("NW_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("NW_PASSWORD"))
    parser.add_argument("--account-no", default=os.environ.get("NW_ACCOUNT_NO"))
    parser.add_argument("--storage-dir", default="/tmp/nw_browser")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if not args.username or not args.password:
        raise SystemExit("Set NW_USERNAME and NW_PASSWORD (env or --flags)")

    async def _run():
        opts = ScraperOptions(
            username=args.username, password=args.password,
            storage_dir=Path(args.storage_dir),
            account_no=args.account_no,
            headless=not args.headed,
        )
        async with NWNaturalScraper(opts) as s:
            readings = await s.fetch_gas_readings()
        for r in readings[:5]:
            print(r)
        print(f"... {len(readings)} rows total")

    asyncio.run(_run())
