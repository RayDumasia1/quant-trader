Quant Trader foundations
=======================

V1.1 additions
--------------

The reviewed foundation is preserved. The seven-system research specification,
deterministic strategy contract and immutable historical-ingestion adapter are
documented in ``docs/strategy-v1.1.rst``, ``docs/interface-v1.1.rst`` and
``docs/data-v1.1.rst``. Initial rules live in
``configs/strategies/tqqq_sqqq_v1.1.json``. These parameters have not been
optimized or validated for profitability. There is no portfolio simulation
or broker integration. Review the V1.1 completion report before proceeding.

The existing stock-research commands remain available. Reusable calculations
and a read-only repository now live in ``quant_trader``. V1.1 adds a separate
research strategy; no broker adapter or order-submission path is implemented.

Run from this directory using the existing Windows environment::

    .\.venv\Scripts\python.exe -m unittest discover -s tests -v
    .\.venv\Scripts\python.exe -m quant_trader validate --as-of 2026-10-19 --output artifacts/validation-2026-10-19.json

Validation exits 1 when it reports warnings, 0 when clear. It opens DuckDB
read-only, fingerprints the database before and after, and writes only a new
report. Output files are never overwritten. Run against a quiescent database;
an external writer changing the file invalidates the report.

Dependencies
------------

``pyproject.toml`` pins direct dependencies to the environment inspected during
the assessment. ``requirements.lock.txt`` records all installed distributions
on Windows/Python 3.14.7. It is an environment snapshot, not a portable,
hash-verified resolver lock. V1.1 adds pandas_market_calendars 5.5.0 and its
calendar dependencies; legacy direct dependency versions are preserved.

Research compatibility and data safety
--------------------------------------

Legacy commands are now inert on import. Explicitly running them retains their
original behavior, including destructive rebuilds in some commands. Do not run
those rebuild commands against existing records without explicit approval.
This foundation phase does not change or regenerate stored research results.

``compute_daily_scores`` preserves the original formulas. The extracted regime
function defaults to requiring breadth as well as the other inputs; missing
inputs produce no regime or exposure. The legacy regime command explicitly
selects its original readiness behavior for compatibility. The new calculation
is versioned ``strict-breadth-v1`` and is not persisted over existing results.

All features include the current completed session. They cannot justify a fill
at that same close. The repository's as-of date bounds rows but does not turn
revised adjusted history into point-in-time data. Future-outcome research labels
are not exposed by the repository.

Validation checks target coverage, staleness, numerical OHLC bounds, missing
membership prices, legacy breadth readiness and differences from SPY sessions.
SPY is a session proxy, not an authoritative exchange calendar. Provider
provenance, corporate actions and true membership effective dates still need
verification. Reports fingerprint data but do not retain immutable snapshots.

Next review gate
----------------

Review the proposed V1.1 rules and data-readiness report before approving
historical portfolio simulation. Public requests for all four assets were
blocked with HTTP 429; no new datasets were populated. An approved source for
NDX and verifiable ETF execution prices/corporate actions is still required.
Existing-record repairs and broker integration remain outside this milestone.

The percentile weighting issue, monthly-membership uncertainty, missing prices
and mixed-provider adjustment concerns remain documented research limitations.
The standalone FMP probe now reads ``FMP_API_KEY`` from the environment. Both
manual probes are inert on import and are not executed by the test suite.
Use environment-managed credentials when integrating external services, and
never put credentials in reports.
