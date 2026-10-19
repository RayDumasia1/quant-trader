V1.1 targeted QC and historical data-readiness report
====================================================

Review date: October 19, 2026, America/New_York. Base commit: b7ff754.
Targeted implementation and tests are complete. Historical portfolio readiness
remains INCOMPLETE. No portfolio backtest, optimization, Alpaca integration,
broker credential creation or order submission was performed.

Strategy review and implementation diff
---------------------------------------

The default remains a 200-session trend SMA with 201-session warm-up. A
250-session SMA is documented only as a future versioned research variant.
The original configuration bytes and parameter fingerprint are unchanged:

    d76141b963ef49b448156683f80d20eff78d03e4429a0f302e4fa74ef80e9beb

AST comparisons against b7ff754 confirmed unchanged conditions, transition,
features, initial_state, constructor and aggregate functions. Direct baseline
comparisons of all pre-existing Signal fields also matched for five synthetic
scenarios: valid flat, overlapping dip, warm-up, rising and declining prices.
No strategy predicate defect was identified and no trading rule was changed.

The additive Signal.module_diagnostics contains all seven module identities,
before/after state, entry/exit condition booleans, named predicates, requested
and accepted direction, nominal attribution fraction and suppression reasons.
Blocked/warm-up values remain None; a valid flat has accepted direction zero.
These are signal attribution diagnostics, not realized profit contributions.

Three mean-reversion long entries can overlap without tripling the aggregate
direction or proposed total budget. A controlled sequential indicator fixture
verified long overlap plus an existing short intent: conflict produces flat,
virtual states continue, a bear reversal exits the long modules, the short
holding limit triggers, and cooldowns block early re-entry through subsequent
reversals. Synthetic state tests are not historical portfolio simulations.

Portfolio allocation and risk design
------------------------------------

See portfolio-risk-v1.1-qc.rst. Typed contracts live in
quant_trader/portfolio/contracts.py; no concrete allocator is implemented.
The 25% gross ETF cap is an initial conservative pilot research scenario.
Separate higher-cap scenarios remain supported and are contract-tested.

The design separates sizing from signals, reserves idle cash, specifies a
volatility-dependent cap, position/portfolio controls, missing-data position
preservation, costs/turnover and module subledger reconciliation. Unavailable
allocation is None, not a synthetic liquidation target. Current diagnostics
do not claim to have attributed realized PnL, because no fills or PnL exist.

Data acquisition and real validation evidence
---------------------------------------------

Authorized alternatives and local import capabilities are implemented:

* FRED NASDAQ100 -> canonical NDX price-index close, with original response
  bytes, retrieval timestamp and an explicitly documented identity mapping.
* Alpha Vantage daily-adjusted ETF API -> raw as-traded OHLCV, provider adjusted
  close and separate split/distribution exports. No key is created; an existing
  ALPHAVANTAGE_API_KEY and appropriate provider entitlement are required.
* Canonical local CSV import with exact headers, source sidecar, known price
  conventions, separate action files and checksum-verified immutable bundles.

Actual available new data:

* NDX 2024: successful FRED HTTP 200; 252 sessions, 2024-01-02 to 2024-12-31.
  Complete requested calendar, positive finite closes, continuity and known
  closing-index convention passed. No OHLC range or volume was fabricated.
* That same real slice was successfully imported through the local CSV path.
  It is a second immutable representation of ONE upstream series, not another
  independent set of 252 observations. Both bundle checksums were verified.
* Full NDX request, 2010-02-09 through exclusive 2026-10-19: HTTP 200, rejected.
  Source has 4,198 valued observations through 2026-10-15, missing 2026-10-16
  and containing a valued non-session 2019-04-19 observation. No values were
  silently dropped, substituted or filled to make this request pass.
* TQQQ/SQQQ/QQQ alternative API acquisition: explicitly blocked by missing
  ALPHAVANTAGE_API_KEY. No remote ETF success is claimed.
* The Stooq TQQQ public probe returned HTTP 404; no certified Stooq adapter or
  adjustment convention is asserted. Earlier Yahoo failures remain unchanged.

NDX real-data bundle ID:

    9511631220fb4a0f780d0152f0cceefd0b20154286bbc8a04f9d5a05ec8bfe35

NDX real CSV-import bundle ID:

    8f643370b63d8cad50df6e4e3809a6cbac0dc18405fed73a6121a1385d323e7b

Both are retrieval snapshots with execution_ready=False. All observations are
available no earlier than their actual retrieval, not backdated to the original
close. A real-data snapshot at 2024-12-31 correctly exposes ZERO bars from
these later-retrieved bundles. Therefore complete calendar validation does
not establish historical decision-time availability. A future versioned
publication-lag scenario or documented release timestamps still needs review.

Existing research QQQ history remains 1,029 rows, 2022-07-01 to 2026-08-07;
it was not relabeled as unadjusted or promoted into an ETF execution dataset.
No existing DuckDB table or record was modified and no migration was performed.
The research database still matches its foundation SHA-256:

    d4d5371b580a0b4a49df316f21951c966b599b5c94feab9539dcd8cb51c6287d

Machine-readable evidence is in artifacts/readiness-v1.1-qc.json. Raw public
responses, metadata, rejected attempts and accepted datasets are retained under
data/v1.1-qc/, excluded from Git. Actual ingestion failures are preserved rather
than converted into empty datasets carrying a success status.

Tests actually executed
-----------------------

Final full regression suite: 48 passed, zero failures/errors/skips, 18.277 seconds.
Command: .venv/Scripts/python.exe -B -m unittest discover -s tests -v.
Full per-test output: artifacts/tests-v1.1-qc.txt.

The original 30 passing tests were preserved. Eighteen additional tests cover:

* Three-way mean-reversion overlap and attribution without vote multiplication.
* Sequential reversal/conflict, holding-limit and cooldown behavior.
* Missing active-state preservation, unavailable versus valid flat diagnostics,
  decision-time truncation and baseline trend-period preservation.
* Pilot/higher caps, volatility scaling, timestamps, cash and position limits,
  inactive-module rejection and unavailable existing-position handling.
* Raw versus adjusted prices, 2:1 and 1:5 split arithmetic, distributions,
  adjustment-factor mismatches, metadata conventions, session gaps/duplicates,
  source retention, reproducible IDs and malformed sidecar failure handling.
* FRED holiday markers and historical availability; ETF response identity,
  missing API key behavior, HTTP failure isolation and report key redaction.

The foundation regression still compares all 569,237 stored scoring rows and
1,029 legacy regime rows. These checks establish compatibility, not proof of
economic validity of the original formulas. pip check reported no broken
requirements. No packages were added or upgraded during this QC milestone.
All 42 Python files compiled without bytecode writes. A targeted source/secret
scan reviewed 55 files and found no candidate credentials; this is not an
exhaustive security audit. git diff --check passed.

An initial 47-test run had one error: a missing FRED trading-session marker
was rejected as generic ValueError instead of structured CoverageError. The
classification was corrected, then all 47 passed in 18.431 seconds. A separate
malformed-sidecar regression was added; the final 48-test run above passed.
No invalid dataset had been accepted by the earlier classification behavior.
No strategy rule was changed to obtain a passing result.

Unresolved research assumptions and readiness recommendation
-----------------------------------------------------------

1. All original strategy thresholds, holding limits and cooldown rules remain
   research assumptions; no optimization, profitability or statistical claim.
2. A 250-session trend requires a new variant/version, 251-session warm-up and
   independent evaluation. It has not been run in this milestone.
3. The 25% cap, equal accepted-module budgets, zero idle-cash return, 20-session
   volatility, 10% reference volatility, 0 commission / 2.5 half-spread / 5
   slippage bps are initial scenario assumptions, not execution estimates.
4. Drawdown/daily-loss/turnover thresholds and restart policies still need
   approval before portfolio simulation. No arbitrary stop was added to rules.
5. Historical release timestamps and revision vintages are not certified.
   The original five-minute lag remains only the existing signal-framework
   convention; it is not assigned to newly retrieved FRED/ETF observations.
6. CSV provenance is supplied by the importer, not cryptographic provider
   authentication. Independent prices/actions must be reconciled before use.
7. Split/share-basis assumptions, distribution reinvestment calculation and
   0.001 adjustment-factor tolerance need real ETF/issuer comparison. Exact
   vendor adjustment arithmetic is not independently certified by API docs.
8. ETF payment dates may be unavailable from the API and must not be invented.
   The cash total-return research index is distinct from spendable cash.
9. Existing breadth/membership/scoring/outcome limitations remain unchanged.
   No market-regime gate is silently applied to the seven-system strategy.

Recommendation: NOT READY for the first full historical portfolio backtest.
First approve a bounded evaluation period (2024 is a validated NDX candidate),
obtain complete raw ETF/action datasets, resolve source discrepancies, approve
availability and risk scenarios and reconcile corporate actions/payment dates.
Only then review a separate simulation implementation milestone. No need to
replace the current strategy or rewrite the existing research database.

Complete implementation inventory
----------------------------------

Created:

* quant_trader/data/imports.py
* quant_trader/data/providers.py
* quant_trader/portfolio/__init__.py
* quant_trader/portfolio/contracts.py
* tests/test_qc_imports.py
* tests/test_qc_portfolio.py
* tests/test_qc_strategy.py
* docs/imports-v1.1-qc.rst
* docs/portfolio-risk-v1.1-qc.rst
* docs/qc-v1.1-report.rst

Modified:

* README.rst
* docs/interface-v1.1.rst
* docs/strategy-v1.1.rst
* quant_trader/data/datasets.py (additive source/action bundle members)
* quant_trader/strategies/base.py (additive diagnostics type/field)
* quant_trader/strategies/seven_system.py (diagnostics only)

Removed: none. No strategy parameter file, existing research script, previous
test file, dependency manifest or existing dataset was modified. New bundles
are additive; no database schema migration is required.

Generated evidence includes the QC readiness report, full test log, real FRED
and real CSV summaries, ETF failure summary, raw probes and unique attempt
records. These remain local and Git-ignored. Review the tracked source and
specifications before proceeding; no remote repository push is performed.
