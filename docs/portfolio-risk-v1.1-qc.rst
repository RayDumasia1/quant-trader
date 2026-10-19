Independent portfolio allocation and risk design
================================================

Status: design specification with typed boundary contracts. No allocation
algorithm, portfolio simulator, order planner or broker is implemented.

Pilot scenario and alternatives
-------------------------------

Initial pilot maximum combined TQQQ plus SQQQ market value is 25% of NAV.
This is a conservative research scenario, not an optimal parameter, target
live allocation or guarantee against loss. Cash is the remaining NAV weight.
Higher caps (for example 50%) must be separate, named, versioned research runs,
with their own cost/risk configuration. They are not automatically enabled.
Exposure is gross invested ETF market value, not netted underlying direction
or a claim that 25% capital means 25% market risk. No borrowing or short shares.

Boundary and future allocation algorithm
---------------------------------------

SizingRequest carries a completed Signal, decision timestamp, NAV snapshot,
RiskPolicy, ETF/mark data status, existing shares and available volatility
estimate. These are immutable contracts. No broker account identifier exists.
The contract rejects future marks, future volatility and future signal inputs.

A future PositionSizer.allocate implementation would perform:

1. Verify signal ready, usable ETF prices, NAV and valuation timestamps.
2. Resolve portfolio-level risk overrides independently of strategy state.
3. Set budget B = max_etf_exposure * min(1, reference_vol / observed_vol).
4. Divide B equally among accepted active same-side modules as an initial
   research allocation policy. Sum module budgets into a single ETF target.
   Overlap adds attribution channels, not multiples of B.
5. Apply per-position cap, portfolio gross cap, cash reserve and turnover
   constraints. Reduce before adding when a reversal would breach the cap.
6. Convert target value to whole shares at a documented executable reference,
   round down and retain residual cash. A fill engine must enforce available
   cash and next-open timing; none is implemented in this milestone.

AllocationDecision is either ready with explicit module weights and cash, or
unavailable with weights/cash=None. The current implementation validates these
boundaries but does not compute a target, change shares or simulate fills.
Weights plus cash must equal one, every positive module budget must correspond
to an accepted active direction and combined ETF weights must respect caps.
Actual holding values may drift beyond targets; the later engine must record
drift and bring it under the cap at the next valid executable opportunity.

Volatility and cash
-------------------

Proposed volatility observation: trailing 20 completed sessions of the intended
ETF's cash-total-return series, sample standard deviation annualized by sqrt(252).
All source prices and actions must be available at decision time. Historical
revisions cannot be passed off as contemporary observations. Record the exact
series/dataset and availability timestamp with every estimate.

The contract's initial reference_vol is 10% annualized. It is an ETF volatility
reference used to SCALE the cap, not a promise of 10% portfolio volatility.
The multiplier never exceeds one. Missing/zero/nonfinite volatility prevents
positive exposure targets. These choices are research assumptions requiring
review, not parameter optimization.

Pilot idle cash earns zero in the first proposed simulation. No implicit
interest, dividends, reinvestment or money-market returns are assumed. Testing
an interest-bearing cash alternative requires a separate point-in-time series
and configuration. Distribution receivables and payment dates must be tracked
separately from spendable cash; missing payment dates block certified cash
accounting rather than invent a payment date.

Risk controls and unavailable data
----------------------------------

Position controls: configurable maximum asset weight, gross ETF cap, no
pyramiding from duplicate votes, no short quantities, no borrowed capital,
participation/liquidity checks and finite positive execution prices.

Portfolio controls: configurable daily-loss, peak-to-trough drawdown and
turnover thresholds; reject risk increases after a breach, and define an
explicit next-valid-session reduction policy. Threshold values and any
freeze/restart policy require approval before a simulation; no new strategy
exit, stop-loss rule or numeric loss threshold is introduced here.

Missing NDX signal, stale ETF price, unavailable volatility or unreconciled
position data yields unavailable, never a synthetic flat or zero-price fill.
Preserve actual quantities and the most recent trusted valuation with a stale
flag. Block increases. If an exit intent exists, retain it as pending without
claiming execution. Independent reductions may occur only with valid tradable
prices and an approved risk policy. Do not fabricate zero PnL for unknown marks.
Replay missing strategy sessions when data returns before allocating again.

Costs and turnover
------------------

Research defaults in RiskPolicy: commission 0 bps, half-spread 2.5 bps and
additional slippage 5 bps on EACH executed side. These are scenario assumptions,
not estimates from historical execution. Record fees and spread separately to
avoid double counting. Use raw as-traded ETF prices for fills, split events for
share changes and cash distributions for receivables/cash; adjusted closes are
not executable prices. Later cost sensitivity runs must be separate scenarios.

Measure gross traded notional / pre-trade NAV at each rebalance, and report
both one-way and two-way turnover conventions explicitly. Reversal costs
include both the exit and entry. No holding cost or return is charged for an
unexecuted intent. A turnover cap must never defer an approved risk-reduction
exit merely to improve reported costs.

Module attribution
------------------

Signal.module_diagnostics records each module's before/after state, predicate
flags, requested/accepted direction and nominal attribution_fraction. These
fractions divide the accepted vote equally; they are not actual NAV weights or
realized performance. During conflict they are zero; unavailable signals use
None. Module virtual states continue even while conflict suppresses exposure.

In the future simulator, retain module subledgers with attributed shares and
cash. Assign net fills, fees, slippage and distributions deterministically in
proportion to module target deltas, with a documented residual rounding rule.
Pure ownership transfers between modules do not create fictitious broker
turnover. Module holdings sum to actual portfolio holdings; contributions,
costs, cash and residuals reconcile exactly to portfolio PnL. Suppressed signals
receive no realized holding return. Analyze individual systems and the combined
portfolio separately without treating overlapping trades as independent samples.
