# Changelog

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
