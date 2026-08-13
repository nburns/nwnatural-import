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

from playwright.async_api import BrowserContext, Page, async_playwright

GAS_USAGE_URL = "https://www.nwnatural.com/account/gas-usage"
LOGIN_HOST = "identity.nwnatural.com"

log = logging.getLogger(__name__)


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
            await page.goto(GAS_USAGE_URL, wait_until="networkidle")
            if self._opts.account_no:
                await self._select_account(page, self._opts.account_no)
            await self._expand_date_range(page)
            await page.wait_for_selector("table tbody tr", timeout=30_000)
            rows = await page.eval_on_selector_all(
                "table tbody tr",
                "els => els.map(tr => [...tr.querySelectorAll('td')].map(td => td.innerText.trim()))",
            )
            log.info("scraped %d gas-usage rows", len(rows))
            return [r for r in (_parse_row(cells) for cells in rows) if r is not None]
        finally:
            await page.close()

    async def _expand_date_range(self, page: Page) -> None:
        """Set From = today - max_years, To = today, and click Submit.
        The default view only shows ~13 months; the portal exposes up to 3."""
        today = date.today()
        from_d = today.replace(year=today.year - self._opts.max_years)
        # The From/To inputs aren't native <input type=date>; look for text
        # inputs near the "From:" / "To:" labels. Try a range of selectors,
        # skip silently if none match (we still get the default view).
        try:
            from_input = page.get_by_label("From", exact=False).first
            to_input = page.get_by_label("To", exact=False).first
            await from_input.wait_for(state="visible", timeout=5_000)
            await from_input.fill(from_d.strftime("%m/%d/%Y"))
            await to_input.fill(today.strftime("%m/%d/%Y"))
            await page.get_by_role("button", name="Submit").click()
            await page.wait_for_load_state("networkidle")
            log.info("expanded date range: %s → %s", from_d, today)
        except Exception as e:
            log.warning("could not expand date range (%s); using portal default", e)

    async def _ensure_logged_in(self, page: Page) -> None:
        await page.goto(GAS_USAGE_URL, wait_until="networkidle")
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
        """If the account picker is present and the requested account isn't
        the current selection, switch to it."""
        body_text = await page.locator("body").inner_text()
        if account_no not in body_text:
            log.warning("requested account %s not visible on page", account_no)
            return
        candidates = page.get_by_text(f"Account No: {account_no}", exact=False)
        if await candidates.count() == 0:
            return
        try:
            await candidates.first.click()
            await page.wait_for_load_state("networkidle")
            log.info("selected account %s", account_no)
        except Exception as e:
            log.warning("account picker click failed (%s); continuing with default", e)


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
