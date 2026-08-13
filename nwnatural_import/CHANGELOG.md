# Changelog

## 0.1.3

- Fix multi-account picker: the `AccountSelector` widget is a proper
  closed→open dropdown. Previously we tried to click the account-number
  div directly, but a wrapper intercepted pointer events. Now we click
  the trigger first to open the dropdown, then click the option.
- Single-account logins short-circuit (no picker on the page).

## 0.1.2

- Emit a heartbeat to `input_datetime.nwnatural_last_import` after
  every successful run. Pair with a template binary_sensor + HA alert
  to detect stale imports. No-op if the helper doesn't exist.

## 0.1.1

- Scraper now always returns the default view (~13 months) first, and
  only replaces it if the date-range-expansion Submit produces MORE
  rows. Previously a failed Submit could leave the table empty and
  return 0 rows. In practice the Submit-then-wait race prevents us
  from getting the full 3 years from the portal; falling back to 13
  months is the honest MVP.
- Better Submit-button selector (there are 3 "Submit" buttons on the
  page; two are search-bar submits, we now target only the date-range
  one via `button.Button--auto:not(.GlobalHeader__search-sub)`).
- Correct date-range input selectors: `#startDate` / `#endDate`
  (`get_by_label("From")` and `("To")` matched unrelated elements
  because of substring matching in aria-labels).

## 0.1.0

Initial release.

- Log in to NW Natural (`identity.nwnatural.com`, OpenID Connect).
- Scrape the monthly gas usage table on `/account/gas-usage` — up to
  3 years of history.
- Import two long-term statistics per month:
  - `nwnatural:gas_consumption` in ft³ (therms × 100)
  - `nwnatural:gas_cost` in USD (billed total)
- Optional `account_no` for multi-account logins.
- Locked-down container (non-root pwuser, AppArmor, no host access).
