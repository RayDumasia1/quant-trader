"""Immutable strategy inputs and signal-lifecycle state, independent of fills."""
from dataclasses import dataclass
from typing import Protocol

from quant_trader.data.calendar import utc_timestamp


@dataclass(frozen=True)
class PriceBar:
    symbol: str
    session: str
    close: float
    available_at: str


@dataclass(frozen=True)
class Snapshot:
    as_of: str
    dataset_id: str
    bars: tuple[PriceBar, ...]


def as_of_snapshot(bars, *, as_of, dataset_id):
    """Truncate at known information availability; never relabel future bars."""
    stamp = utc_timestamp(as_of)
    return Snapshot(stamp.isoformat(), dataset_id,
                    tuple(bar for bar in bars if utc_timestamp(bar.available_at) <= stamp))


def snapshot_from_dataset(store, dataset_id, *, as_of):
    """Verify immutable NDX bundle before selecting its as-of signal view."""
    import json
    manifest, bars = store.load(dataset_id)
    if manifest['provenance']['symbol'] != 'NDX':
        raise ValueError('Only NDX may supply signal prices')
    validation = json.loads((store.root/'datasets'/dataset_id/'validation.json').read_bytes())
    if not validation['signal_data_valid']:
        raise ValueError('Dataset did not pass signal-data validation')
    return as_of_snapshot(tuple(PriceBar(row['symbol'],row['session'],
                                        row['split_adjusted_close'],row['available_at'])
                                for row in bars), as_of=as_of,dataset_id=dataset_id)


@dataclass(frozen=True)
class ModuleState:
    system_id: str
    active: bool = False
    entered_session: str | None = None
    holding_sessions: int = 0
    cooldown_remaining: int = 0


@dataclass(frozen=True)
class StrategyState:
    parameter_id: str
    modules: tuple[ModuleState, ...]
    last_session: str | None = None


@dataclass(frozen=True)
class Intent:
    system_id: str
    instrument: str
    direction: int  # NDX directional vote: +1=TQQQ long, -1=SQQQ long, 0=flat
    action: str  # enter, hold, exit, flat, cooldown
    reason: str


@dataclass(frozen=True)
class Signal:
    strategy_id: str
    version: str
    parameter_id: str
    dataset_id: str
    signal_at: str
    information_available_at: str | None
    session: str | None
    earliest_execution_at: str | None
    status: str
    intents: tuple[Intent, ...]
    portfolio_direction: int | None  # No shares, weights, leverage or order type
    reason: str
    state: StrategyState
    diagnostics: tuple[tuple[str, float], ...] = ()


class Strategy(Protocol):
    strategy_id: str
    version: str
    required_price_inputs: tuple[str, ...]

    def initial_state(self) -> StrategyState: ...
    def evaluate(self, snapshot: Snapshot, state: StrategyState) -> Signal: ...
