# NW Natural → Home Assistant

A Home Assistant add-on that pulls your NW Natural (northwest US natural
gas utility) **monthly gas usage and billed cost** into HA's Energy
dashboard.

NW Natural residential meters are AMR (drive-by radio read once a month),
so the max granularity available is monthly billing cycles. The add-on
logs into `nwnatural.com/account/gas-usage` in a headless browser,
scrapes the usage table, and inserts the values as HA long-term
statistics — both consumption (ft³) and cost (USD).

## Features

- Automatic monthly import into HA long-term statistics.
- Up to 3 years of historical backfill on first run.
- Weekly cron top-up (bills only arrive once a month, so no need for daily).
- Imports **both consumption AND cost** — HA Energy dashboard can show
  either directly, or use its own cost calculation if you prefer.
- Locked-down container: non-root, AppArmor profile, no host network / PID
  / IPC, minimal HA API access.

## Install

One-click (uses [my.home-assistant.io](https://my.home-assistant.io) —
opens the "Add repository" dialog in your HA):

[![Add repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fnburns%2Fnwnatural-import)

Or manually:

1. In Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Add: `https://github.com/nburns/nwnatural-import` → **Add**

Then:

3. Refresh the add-on store; "NW Natural Import" appears in the list.
4. Click **Install**.
5. Open the **Configuration** tab; enter your NW Natural `username`
   (email) and `password`. Optional: `account_no` if you have multiple
   accounts (e.g. `1234567-8`).
6. **Save**, then **Start**.
7. Watch the **Log** tab — the initial backfill takes ~30 seconds.

## Add to the Energy dashboard

1. **Settings → Dashboards → Energy → Gas → Add gas source**
2. Select "NW Natural gas consumption".
3. For cost, either:
   - Use HA's static price setting with your ¢/therm rate, OR
   - Point cost at the imported statistic `nwnatural:gas_cost` for real
     billed dollars.
4. Save.

See [DOCS.md](DOCS.md) for the full options reference.

## Requirements

- Home Assistant OS or Supervised (add-ons don't work on Container/Core).
- A NW Natural online account (register at nwnatural.com if you haven't).
- MFA disabled on the account (the login flow is scripted).

## Security

- Add-on security rating: **6/8** (AppArmor + no host access + no
  dangerous caps + non-root pwuser).
- Credentials live only in supervisor-encrypted options + process memory.
- Everything after startup runs as unprivileged `pwuser`.

## How it works

- **Auth**: Simple email/password against `identity.nwnatural.com` (an
  OpenID-Connect identity provider). Session cookies persist between runs.
- **Data**: The `/account/gas-usage` page renders an HTML table with
  columns `Date | Month | Total bill | Therms`. We scrape the table
  directly rather than fight the JS-triggered "Download table" flow.
- **Conversion**: NW Natural bills in therms; HA's Energy dashboard
  wants ft³ or m³. Converted via `1 therm ≈ 100 ft³` (standard 1000
  BTU/ft³ approximation). Real heating value varies ±1%.
- **Import**: HA WebSocket API's `recorder/import_statistics` accepts
  external statistics idempotent by `(statistic_id, start)`.

## License

MIT — see [LICENSE](LICENSE).
