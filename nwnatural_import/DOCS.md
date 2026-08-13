# NW Natural Import — Setup

## Configure

Open the add-on's **Configuration** tab and set:

| Option | Description |
| --- | --- |
| `username` | Your NW Natural online account email. |
| `password` | Your NW Natural online account password. |
| `account_no` | (optional) If your login has multiple accounts, the number to import (e.g. `1234567-8`). Leave blank to accept the default account. |
| `statistic_id` | Internal HA statistic id for consumption. Must contain a colon. Default `nwnatural:gas_consumption`. |
| `statistic_name` | Human-readable name shown in HA for the consumption stat. |
| `cost_statistic_id` | Internal HA statistic id for the billed cost. Default `nwnatural:gas_cost`. |
| `cost_statistic_name` | Human-readable name for the cost stat. |
| `schedule` | Cron expression for the incremental scrape. Default `17 6 * * *` (06:17 local, daily). Since bills are monthly, weekly is also fine. |
| `run_backfill_on_start` | If `true`, run the 3-year backfill on first start when no state file exists yet. |

Click **Save**, then **Start** the add-on.

## First-run behavior

On first start the add-on:

1. Reads options from the supervisor.
2. Launches a headless Chromium.
3. Signs in to `identity.nwnatural.com` (OpenID Connect provider).
4. Navigates to `/account/gas-usage`, selects the requested account,
   sets the date range to today − 3 years → today.
5. Scrapes the monthly usage table.
6. Imports each month as two long-term-statistic points:
   - `<statistic_id>` in ft³ (therms × 100)
   - `<cost_statistic_id>` in USD (billed total)

Watch the **Log** tab. Full backfill is usually <60 seconds.

## Add to the Energy dashboard

1. Go to **Settings → Dashboards → Energy**.
2. Under **Gas**, click **Add gas source**.
3. Select "NW Natural gas consumption" (or your custom `statistic_name`).
4. For cost, either:
   - Use HA's static price with your ¢/therm from a recent bill, OR
   - Select **Use an entity tracking the total costs** and pick the
     `nwnatural:gas_cost` statistic — this gives you the actual billed
     amount, not an estimate.
5. Save. Historical monthly bars appear immediately.

## Granularity note

NW Natural residential meters are **AMR** — a truck drives by once a
month and reads the meter. This add-on cannot produce more than
monthly-granularity data because that's all the utility ever collects.
For real-time gas monitoring, you'd need a pulse-counting sensor on the
mechanical meter itself (an ESPHome reed switch on the low dial).

## Troubleshooting

- **"Not authenticated — running login flow" every run**: session cookies
  aren't sticking. Check `/data/browser/` exists and is writable; a HA
  backup restore may have wiped it.
- **`Timeout` waiting for the email/password fields**: NW Natural's
  identity provider changed. File an issue with the log.
- **"scraper returned no readings"**: the account picker probably
  didn't match. Double-check `account_no` (with the dash, e.g.
  `1234567-8`) — or leave it blank to accept the default.
- **Weird cost math in the dashboard**: HA computes cost via
  `state × price` if you set a static price. Since we import cost
  directly, prefer "Use an entity tracking the total costs" and point
  at `nwnatural:gas_cost` to see actual billed amounts.

## Storage

Everything the add-on persists lives under `/data/`:

- `state.json` — cumulative ft³ + last-run timestamps + backfill_version.
- `browser/` — persistent Chromium context (cookies, cache).

Deleting `/data/` triggers a full re-login and a fresh backfill on the
next start.
