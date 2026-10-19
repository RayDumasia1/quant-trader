Historical data ingestion and immutable storage V1.1
==================================================

Run from the workspace root::

    .\.venv\Scripts\python.exe -B -m quant_trader.data.ingestion --start 2010-02-09 --end 2026-10-19

The end is exclusive. Current potentially incomplete sessions are excluded.
This is an initial research coverage assumption, not a claim about instrument
inception or the optimal evaluation period. NDX warm-up consumes the first
201 available sessions; no ETF history is synthesized before inception.

The adapter makes one public chart request per explicit canonical instrument:
NDX -> ^NDX, TQQQ -> TQQQ, SQQQ -> SQQQ and QQQ -> QQQ. Symbol, instrument
type, Nasdaq exchange, USD currency and New York timezone must match. There
are no fallback providers, retries, silent symbol substitutions or repairs.
Provider/network errors leave that dataset unpopulated. A permission-approved
retry outside a failed sandbox network is an execution-environment retry,
not a second data-provider substitution.

Store layout (ignored by Git)::

    data/v1.1/
        attempts/<unique-attempt-id>/attempt.json
        attempts/<unique-attempt-id>/response.bin
        datasets/<sha256>/manifest.json
        datasets/<sha256>/raw.json
        datasets/<sha256>/bars.json
        datasets/<sha256>/actions.json
        datasets/<sha256>/calendar.json
        datasets/<sha256>/validation.json

attempt.json retains retrieval timestamp, exact request, provider identity,
coverage request, status, failure class, raw checksum and dataset identifier
when successful. response.bin preserves the HTTP body byte-for-byte when a
response was received; transport failures have no response file. Error bodies
and exception strings are not printed into reports. There are no credentials.

The dataset manifest records adapter/schema/calendar versions, adjustment
conventions and SHA-256 checksums for all bundle payloads. The dataset ID hashes
that canonical manifest identity. Retrieval timestamps live in linked attempt
records so identical source content and conventions can reuse a dataset ID.
Existing bundles are verified and reused, never overwritten. Reads verify all
checksums. A crash before the manifest is written leaves an incomplete bundle
that fails verification; no automatic deletion or repair is attempted.
This is application-level immutability with tamper detection, not OS-enforced
write-once storage. Keep the entire dataset and attempts directory for replay.

Price representations
---------------------

* raw.json is the untouched provider response, not a claim of raw economic
  unadjusted prices.
* split_adjusted_open/high/low/close retain Yahoo native quote values under an
  explicit, independently unverified split-adjustment assumption.
* distribution_adjusted_close retains Yahoo adjclose separately. It represents
  provider-adjusted return research, not an executable order price.
  distribution_adjusted_return is its adjacent-session ratio minus one; the
  first observation has no return. Incomplete series fail completeness checks.
* unadjusted_open/high/low/close are null because this provider response does
  not establish independently verified unadjusted OHLC. They are not reverse-
  engineered from incomplete action histories or silently copied from adjusted
  prices. Volume is provider-native with unverified adjustment convention.

Consequently every V1.1 bundle is execution_ready=False. A provider or approved
reconstruction methodology delivering verifiable unadjusted ETF prices and
complete corporate actions is a prerequisite for share-accounting simulation.
No adjustment-derived missing bars are created.

Validation
----------

Checks cover complete requested Nasdaq sessions, duplicates, unexpected
sessions, positive finite OHLC, OHLC bounds, volume, adjusted close, timezone
and symbol identity. Native absolute daily returns above 35% are flagged;
this threshold is a review heuristic, not an automatic correction. Action
checks flag invalid split ratios, invalid distributions, distributions above
prior close, split-like jumps in purported split-adjusted prices and unexplained
adjustment-factor changes. Dividend-factor disagreement is a warning under
the provider's assumed units. No independent issuer action reconciliation has
been completed.

Validation errors prevent dataset population. Anomalous returns and unexplained
factors prevent the signal_data_valid gate even if the evidence bundle is
retained. Five-minute close availability is a research assumption. Yahoo may
revise historical adjusted prices; preserving retrieval snapshots enables
replay but does not recreate historical point-in-time provider knowledge.

Sources reviewed
----------------

* Nasdaq calendar usage: https://pandas-market-calendars.readthedocs.io/en/latest/usage.html
* Provider processing reference: https://github.com/ranaroussi/yfinance/blob/main/yfinance/scrapers/history.py
* SQQQ daily investment objective: https://prod.proshares.com/our-etfs/leveraged-and-inverse/sqqq
* Issuer split announcements: https://www.proshares.com/press-releases/proshares-announces-etf-share-splits5

These explain implementation assumptions; they do not independently certify
the provider's returned records.
