Shared strategy interface V1.1
==============================

``quant_trader.strategies.base.Strategy`` is the common deterministic protocol.
It declares strategy_id, version, required_price_inputs, initial_state() and
evaluate(snapshot, state). The concrete implementation is SevenSystemStrategy.

The immutable inputs are:

* PriceBar: canonical symbol, session, close and information available_at.
* Snapshot: timezone-aware as_of, dataset identifier and tuple of bars.
* StrategyState: parameter fingerprint, tuple of independent module states
  and last processed session.

``as_of_snapshot`` truncates observations by availability. For actual ingestion
bundles, ``snapshot_from_dataset`` verifies dataset checksums, requires NDX
identity and signal-data validation, and creates the as-of view. Directly
constructed snapshots remain useful for synthetic tests; callers are
responsible for retaining their source and identifier. The parameter SHA-256
is computed from canonical JSON including strategy identity and all settings.

Output Signal includes identity/version, parameter and dataset identifiers,
signal_at, information_available_at, session, earliest_execution_at, status,
per-system intents with reasons, aggregate portfolio_direction, diagnostic
indicator values and the next immutable signal state. Serialize with
``dataclasses.asdict`` and persist alongside input dataset and source revision
when a run ledger is implemented. Persistent strategy state and the run ledger
are outside V1.1.

The targeted QC extension adds module_diagnostics: seven immutable
ModuleDiagnostic objects with predicate availability, before/after state,
requested and accepted directions, nominal attribution and suppression reasons.
The existing Signal fields and positional construction remain compatible.
Portfolio contracts are specified independently in portfolio-risk-v1.1-qc.rst;
no concrete position sizer or execution algorithm is implemented.

Status ready means signal evaluation succeeded. It says nothing about ETF
dataset readiness, account permission, sizing, broker position or an order
fill. Status blocked or warmup returns no actionable exposure and unchanged
state. Invalid parameter/state identities raise ValueError. No order or broker
interface is exposed.

Example (requires a successfully acquired NDX dataset)::

    from quant_trader.data.datasets import DatasetStore
    from quant_trader.strategies.base import snapshot_from_dataset
    from quant_trader.strategies.seven_system import SevenSystemStrategy

    strategy = SevenSystemStrategy.from_file()
    snapshot = snapshot_from_dataset(
        DatasetStore(), dataset_id, as_of="2026-10-16T20:05:00Z")
    result = strategy.evaluate(snapshot, strategy.initial_state())

Replaying history requires one session at a time, retaining result.state.
The same input snapshot, state and parameter bytes produce the same output.
There is no random seed, optimization, clock read or network call in evaluate.
Calendar library version must also be retained with the environment.
