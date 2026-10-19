Alternative-provider and local CSV import contracts
==================================================

Public NDX source: FRED NASDAQ100, originally supplied by Nasdaq, Inc. This is
the Nasdaq-100 closing PRICE index, not QQQ or a total-return proxy. Reference:
https://fred.stlouisfed.org/series/NASDAQ100. Only actual closing observations
are imported; FRED missing markers on non-session holidays are not prices.
Trading-session missing markers, extra valued dates and duplicates are errors.
No OHLC range, volume or index corporate actions are invented from a close.

ETF adapter: Alpha Vantage TIME_SERIES_DAILY_ADJUSTED. The provider documents
raw as-traded OHLCV, adjusted close and split/dividend events. Reference:
https://www.alphavantage.co/documentation/#dailyadj. Entitlement and an existing
ALPHAVANTAGE_API_KEY are required; the implementation creates no credentials.
Keys never enter saved request URLs or report metadata. Missing keys, HTTP
errors, entitlement errors and identity mismatches are recorded explicitly.
Stooq was probed but is not a certified adapter: the request returned HTTP 404
and its adjustment basis has not been established. No fallback is automatic.

Commands (exclusive end dates)::

    .\.venv\Scripts\python.exe -B -m quant_trader.data.providers fred NDX --start 2024-01-02 --end 2025-01-01
    .\.venv\Scripts\python.exe -B -m quant_trader.data.providers alpha_vantage TQQQ --start 2010-02-09 --end 2026-10-19
    .\.venv\Scripts\python.exe -B -m quant_trader.data.imports --prices prices.csv --metadata metadata.json --splits splits.csv --distributions distributions.csv

All new work uses data/v1.1-qc, separate from the research database and prior
bundles. Successful imports retain byte-for-byte original source files and
SHA-256 manifests. Splits and distributions are stored in separate files as
well as the compatibility actions.json. Reads verify all files; writes never
overwrite datasets. Failed attempts receive unique records without promoting
invalid data. raw.json is the legacy raw-payload filename; it may contain CSV
bytes. Provider raw bodies remain separate from canonical transformation files.

Canonical local CSV schema
--------------------------

NDX prices header: session,close. ETF prices header:
session,open,high,low,close,volume,adjusted_close. Order is exact. Dates are ISO
YYYY-MM-DD, one row per Nasdaq session, sorted ascending. ETF OHLC is raw
as-traded; adjusted-only files are not accepted as raw. Empty/negative/nonfinite
prices, invalid bounds, gaps, duplicates and unexpected sessions are rejected.

splits.csv header: session,numerator,denominator, with new shares / old shares.
distributions.csv header: ex_session,pay_session,amount,basis. Amount is USD per
post-split share on the ex-date; basis must be post_split_share. Payment date
may be blank, but then cash-accounting readiness remains blocked. Pay date
cannot precede ex-date. Explicit header-only action files are required for
ETF periods with no actions. An action on the first row needs a preceding
session context and is rejected until that context is supplied.

Metadata must have exactly these keys (replace values with actual provenance)::

    {
      "symbol": "TQQQ",
      "provider_symbol": "TQQQ",
      "convention": "alpha_vantage_daily_adjusted",
      "source_url": "https://www.alphavantage.co/query",
      "retrieved_at": "2026-10-19T18:00:00Z",
      "start": "2024-01-02",
      "end_exclusive": "2025-01-01",
      "currency": "USD",
      "timezone": "America/New_York"
    }

For NDX use symbol NDX, provider_symbol NASDAQ100 and convention
fred_nasdaq100_close with the FRED source URL. Conventions are a small registry
backed by provider documentation; unknown conventions are rejected. A local
sidecar is provenance supplied by the importer, not proof of provider
authenticity. Verify original exports and independent action evidence before
execution certification. Never relabel a different provider's adjusted data
with one of these conventions just to pass validation.

Adjustment calculations
------------------------

For split ratio s on session t, raw historical prices before t are divided by
the product of subsequent supplied split ratios, anchored to the requested
window end. No session is added. These derived split prices must not be used
as historical raw order prices. Their anchor and complete supplied action set
are retained with the dataset. Raw volume is not silently adjusted.

Provider adjusted_close is retained separately. Check consecutive adjustment
factors f=adjusted_close/raw_close against s/(1-s*d/prior_raw_close), with d
the post-split cash distribution. Relative tolerance is 0.001 to accommodate
vendor rounding; discrepancies are rejected, not repaired. This backward-
adjustment convention is explicitly distinct from cash-holder total returns.
The exact factor equation, share basis and tolerance are research reconciliation
assumptions; the cited API documentation does not independently certify them.
They must be checked against actual ETF exports and issuer action records.

Cash total return for session t is s*(raw_close+d)/prior_raw_close-1. A research
index starts at 100 and compounds those returns. It assumes same-session cash
reinvestment solely for this series, not spendable cash or a simulation fill.
Real dividend-payment cash accounting is a separate future ledger concern.
Reverse splits use the same ratio arithmetic. Unexplained split-neutral daily
moves above 35% require review and are rejected by this strict import path.

Availability and readiness
--------------------------

All imported bars are available no earlier than their captured retrieval
timestamp. Historical release times are not inferred from the session date,
FRED update time today or a generic five-minute close lag. As-of snapshots
therefore cannot leak these retrieved observations into earlier decisions.
Historical simulation requires a separately approved, versioned publication-
lag assumption or documented historical release timestamps. An approved lag
would be a research scenario; it is not enabled in this milestone.

Complete numerical/calendar validation is necessary but insufficient for
portfolio readiness. All new bundles remain execution_ready=False pending
independent reconciliation, historical-availability policy and complete ETF
price/action/payment-date coverage. Do not interpret signal_data_valid as a
claim that the full historical portfolio dataset is ready.
