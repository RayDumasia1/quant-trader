Seven-system NDX / TQQQ / SQQQ specification
===========================================

Identity: ``ndx-seven-system``, version ``1.1.0-research``.
Canonical parameters: ``configs/strategies/tqqq_sqqq_v1.1.json``.

All numerical choices below are explicit initial research assumptions. They
were not optimized, selected by historical profitability, or statistically
validated. This is a proposed strategy specification, not an asserted recovery
of an external or proprietary seven-system strategy. Changes require a new
version and parameter fingerprint.

Inputs and formulas
-------------------

Signals use the Nasdaq-100 PRICE index, NDX (Yahoo provider symbol ``^NDX``).
QQQ is a benchmark, never a substitute for NDX. TQQQ and SQQQ are the intended
long-held tradable ETFs. A negative directional vote means buying SQQQ, not
selling SQQQ short. ETF returns are not generated as three times index returns.

For session t, C is the completed-session NDX close. SMA(n) includes C and the
previous n-1 consecutive Nasdaq sessions. Define M=SMA(20), F=SMA(50),
T=SMA(200), E20=C/M-1 and E50=C/F-1. Bollinger U/L are SMA(20) +/- 2 times
the population standard deviation of those 20 closes (ddof=0).

Bull gate: C>T. Bear gate: C<T. Equality satisfies neither gate.
Cross above M: previous C<=previous M and current C>current M.
Cross below M: previous C>=previous M and current C<current M.
Cross below L: previous C>=previous L and current C<current L.

Both current and prior indicators must be ready. Default warm-up is 201
consecutive completed sessions, with no filling of missing observations.

Exact module rules
------------------

1. Momentum Long, TQQQ, direction +1:
   enter when bull gate, F>T, and cross above M. Exit when C<F or E20>=10%,
   or after 60 subsequent evaluation sessions.
2. Mean Reversion Long 1, TQQQ, direction +1:
   enter when bull gate and E20<=-3%. Exit when C>=M or bull gate fails,
   or after 10 subsequent evaluation sessions.
3. Mean Reversion Long 2, TQQQ, direction +1:
   enter when bull gate and C<L. Exit when C>=M or bull gate fails,
   or after 10 subsequent evaluation sessions.
4. Mean Reversion Long 3, TQQQ, direction +1:
   enter when bull gate and E50<=-5%. Exit when C>=M or bull gate fails,
   or after 15 subsequent evaluation sessions.
5. Momentum Short 1, SQQQ, direction -1:
   enter when bear gate, F<T, and cross below M. Exit when C>F or E20<=-10%,
   or after 30 subsequent evaluation sessions.
6. Momentum Short 2, SQQQ, direction -1:
   enter when bear gate and cross below L. Exit when C>=M or bear gate fails,
   or after 10 subsequent evaluation sessions.
7. Mean Reversion Short, SQQQ, direction -1:
   enter when bear gate, C>U and E20>=3%. Exit when C<=M or bear gate fails,
   or after 10 subsequent evaluation sessions.

Lifecycle and re-entry
----------------------

Each module independently maintains FLAT, ACTIVE or cooldown state. These
are virtual signal states, not broker positions or evidence of fills.

FLAT -> ACTIVE on entry if the exit predicate is false. If both predicates
are true while flat, stay flat. Entry sets holding_sessions=0. Each subsequent
consecutive session increments that counter. ACTIVE -> cooldown on exit or
holding limit; the holding limit has diagnostic priority if both apply.
An exit cannot reopen on the same session. One complete following session is
spent in cooldown without entry. The session after cooldown may re-enter if
the entry predicate holds. No pyramiding, partial exits, stops or intraday
price assumptions are introduced.

During ACTIVE, re-entry predicates do not reset the holding counter. After
an interrupted process, replay every missing session in order; counters may
not be advanced by a calendar-day approximation. A repeated or reversed
session is blocked without changing state. Invalid/missing/stale inputs
preserve state and return no actionable portfolio intent.

Signal aggregation
------------------

All seven modules continue independently. Same-side active votes combine into
one directional intent; vote count is not a size or leverage multiplier. If
both +1 and -1 votes are active, aggregate intent is zero (flat), with an
explicit conflict diagnostic. Virtual module states continue during conflict.
When conflict resolves, a surviving active vote may resume aggregate exposure
without a new module entry. This behavior must be represented explicitly in
the later portfolio simulator. It does not submit a liquidation order now.

No votes also means zero. Blocked or warm-up output uses direction=None, which
must not be mistaken for a flat instruction. Later risk and allocation layers
may reject intents; the strategy has no account balances, quantities, weights,
order types, broker access or execution-state assumptions.

Time and availability
---------------------

All timestamps must be timezone-aware. Calendar: Nasdaq regular sessions from
pandas_market_calendars 5.5.0, including early closes and DST. Initial data
publication assumption: market close plus five minutes. This is a conservative
research convention, not a provider publication-time guarantee.

Only bars whose availability is <= evaluation as_of may enter a snapshot.
Evaluation rejects future information and any claimed availability before the
calendar close plus five minutes. The latest expected completed session must
be present. Earliest execution is the next Nasdaq session open after the signal
session. If evaluation occurs at or after that open, it is blocked as a missed
next-session open. A later simulator must also enforce execution after the
decision time; this contract alone does not guarantee a fill.

No market-regime filter is applied in V1.1. Existing regime research remains
available but its breadth provenance is not certified. Any regime gate or
exposure cap is a separate future research hypothesis.
