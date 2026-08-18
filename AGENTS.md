# AGENTS.md — nwnatural-import

Home Assistant add-on that scrapes NW Natural's monthly gas-usage table
into HA long-term statistics (consumption in ft³ + billed cost in USD).

## Layout

```
<repo-root>/                       ← github.com/nburns/nwnatural-import
├── README.md                       (GitHub landing page)
├── LICENSE
├── AGENTS.md                       (this file)
├── repository.yaml                 (HA add-on repository metadata)
└── nwnatural_import/               ← the actual add-on
    ├── config.yaml                 HA add-on manifest (options, security)
    ├── Dockerfile                  Container build
    ├── build.yaml                  Add-on base image mapping
    ├── run.sh                      Entrypoint (options → backfill → cron)
    ├── entrypoint.sh               Root shim: chown /data + drop to pwuser
    ├── apparmor.txt                AppArmor profile
    ├── DOCS.md                     User-facing docs (HA add-on info tab)
    ├── CHANGELOG.md
    ├── README.md                   Short add-on README (HA info tab)
    ├── pyproject.toml              uv-managed Python project
    ├── uv.lock
    ├── src/nwnatural_import/
    │   ├── scraper.py              Playwright login + HTML table scrape
    │   ├── ha_client.py            HA WebSocket import_statistics client
    │   ├── state.py                /data/state.json bookkeeping
    │   └── __main__.py             CLI: --mode backfill|incremental
    └── tests/                      pytest
```

**All dev commands run from `nwnatural_import/nwnatural_import/`
(the add-on subdir with pyproject.toml).**

## Setup

```
cd nwnatural_import
uv sync
uv run playwright install chromium   # local dev only; addon uses image chromium
```

## Common commands

Local dev reads credentials from `.env` (copy from `.env.example`).

```
uv run pytest                                    # tests
uv run python -m nwnatural_import --help         # CLI

# Standalone scraper smoke test (visible browser):
uv run --env-file .env python -m nwnatural_import.scraper \
  --account-no 1234567-8 --headed

# Full local run against a real HA instance:
uv run --env-file .env python -m nwnatural_import --mode backfill
```

## Architecture notes

**Why Playwright?** NW Natural's login is a standard email/password form
posting to `identity.nwnatural.com` (OpenID Connect / .NET Identity
Server). Scriptable in pure httpx, but the gas-usage table renders
client-side. Simpler to drive a browser end-to-end.

**Why HTML scrape, not "Download table"?** The `Download table` `<a>`
has no href — it triggers a JS-built CSV blob download. Playwright's
`expect_download` couldn't catch it reliably. The visible `<table>` is
the same data, easier to scrape.

**Granularity.** NW Natural residential meters are AMR (drive-by, read
monthly). The portal exposes *only* monthly-billing-cycle rows. No
hourly / daily. Ceiling not fixable in software.

**Backfill horizon.** Portal claims up to 3 years. Default view shows
~13 months; we set the From/To date range to `today − 3y → today` to
get everything.

**Multi-account.** Some logins have multiple accounts (rental
properties etc.). If `account_no` option is set, the scraper clicks the
matching account tile before scraping.

**Units.** NW Natural bills in *therms*. HA Energy dashboard accepts
ft³, m³, CCF, or kWh — not therms directly. We convert via
`1 therm ≈ 100 ft³` (nominal 1000 BTU/ft³). Real heating value varies
±1% and NW Natural doesn't publish per-bill factors.

**HA long-term statistics.** External statistics require a
`statistic_id` with a colon (e.g. `nwnatural:gas_consumption`).
`has_sum=true`, `state` = ft³ per interval, `sum` = cumulative ft³
from an arbitrary epoch. Re-imports for the same `(statistic_id, start)`
overwrite in place.

**Cumulative sum.** Backfill calls `recorder/clear_statistics` on both
statistic_ids first so a partial prior import doesn't leave stale sums.
`state.backfill_version` gates re-backfill on upgrade.

**Auth persistence.** Chromium persistent context lives at
`<data_dir>/browser/`. Sessions carry across runs — full re-login only
when cookies expire.

## Add-on packaging

- Base image: `mcr.microsoft.com/playwright/python:v1.62.0-noble`.
- `run.sh` reads options from `/data/options.json` with `jq`, runs a
  one-shot backfill on first boot, then `exec`s `supercronic`.
- Inside the container HA is reached via `ws://supervisor/core/websocket`
  authenticated with `$SUPERVISOR_TOKEN` — no long-lived token needed.
- Add-on files: `config.yaml`, `Dockerfile`, `build.yaml`, `README.md`,
  `DOCS.md`, `CHANGELOG.md`, `apparmor.txt`. Icons aren't checked in.
- **Bump `config.yaml` `version:` whenever you ship a change.** HA
  supervisor detects updates by comparing this string, not commit
  hashes or CHANGELOG entries. If you skip the bump the add-on store
  will never surface the update, even after a repo reload.
- Installable as a HA custom repository via the `repository.yaml` at
  the repo root.

## Security posture

- `config.yaml`: only `homeassistant_api: true`. Everything else off.
  `privileged: []`, `devices: []`.
- `ingress: false`, no webui, no ports.
- `apparmor: true` loads `apparmor.txt` (base + nameservice abstractions
  only — heavier abstractions like `<abstractions/openssl>` don't exist
  on the HA OS host and cause silent load failure).
- Runs as non-root `pwuser` (uid 1001). `entrypoint.sh` runs as root
  only long enough to `chown /data`, then `exec gosu pwuser /run.sh`.
- Chromium sandbox is off (`chromium_sandbox=False`); container +
  AppArmor + non-root provide the isolation.
- Credentials only in `/data/options.json` (supervisor-encrypted) and
  in-memory. Never logged.

## Known gaps

- Not yet deployed to a real HA instance for supervisor-side testing.
- Multi-account picker code is best-guess based on the observed
  "Account No: X" text — the picker widget may need a different click
  target on some accounts.
- Date-range expansion is a best-effort — the From/To inputs aren't
  standard HTML5 date inputs. If the label-based locators change, we
  silently fall back to the default view (~13 months).

## Non-goals

- Sub-monthly granularity — impossible without a hardware pulse counter
  on the meter itself.
- NW Natural business accounts — schema likely differs; untested.
