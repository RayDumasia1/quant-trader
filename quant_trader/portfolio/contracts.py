"""Boundary validation for a future independent allocation implementation."""
from dataclasses import dataclass
import math
from typing import Protocol

from quant_trader.data.calendar import utc_timestamp
from quant_trader.strategies.base import Signal


@dataclass(frozen=True)
class RiskPolicy:
    max_etf_exposure: float = .25
    volatility_target: float = .10
    volatility_lookback: int = 20
    commission_bps: float = 0.0
    slippage_bps: float = 5.0
    half_spread_bps: float = 2.5
    max_position_exposure: float | None = None

    def __post_init__(self):
        if not math.isfinite(self.max_etf_exposure) or not 0<=self.max_etf_exposure<=1:
            raise ValueError('Exposure cap is a fraction of NAV in [0,1]')
        if not math.isfinite(self.volatility_target) or self.volatility_target<=0 or self.volatility_lookback<2:
            raise ValueError('Invalid volatility parameters')
        if self.max_position_exposure is not None and (not math.isfinite(self.max_position_exposure) or not 0<=self.max_position_exposure<=1):
            raise ValueError('Invalid position exposure cap')
        if any(not math.isfinite(x) or x<0 for x in [self.commission_bps,self.slippage_bps,self.half_spread_bps]):
            raise ValueError('Invalid cost assumptions')


@dataclass(frozen=True)
class ExistingPosition:
    instrument: str
    shares: float
    mark: float | None
    mark_available_at: str | None


@dataclass(frozen=True)
class SizingRequest:
    signal: Signal
    decision_at: str
    nav: float
    policy: RiskPolicy
    data_status: str
    volatility: float | None = None
    volatility_available_at: str | None = None
    positions: tuple[ExistingPosition, ...] = ()

    def __post_init__(self):
        stamp=utc_timestamp(self.decision_at)
        if stamp<utc_timestamp(self.signal.signal_at) or not math.isfinite(self.nav) or self.nav<=0:
            raise ValueError('Invalid decision time or NAV')
        if self.signal.information_available_at and utc_timestamp(self.signal.information_available_at)>stamp:
            raise ValueError('Signal information is not yet available')
        if self.data_status not in {'complete','missing','stale'}: raise ValueError('Invalid data status')
        if len({position.instrument for position in self.positions})!=len(self.positions): raise ValueError('Duplicate holdings')
        for position in self.positions:
            if position.instrument not in {'TQQQ','SQQQ'} or not math.isfinite(position.shares) or position.shares<0:
                raise ValueError('Invalid existing position')
            if position.mark is not None:
                if not math.isfinite(position.mark) or position.mark<=0 or position.mark_available_at is None:
                    raise ValueError('Invalid existing mark')
                if utc_timestamp(position.mark_available_at)>stamp: raise ValueError('Future existing mark')
            elif self.data_status=='complete': raise ValueError('Complete data requires a mark')
        if self.volatility is not None:
            if not math.isfinite(self.volatility) or self.volatility<=0 or self.volatility_available_at is None:
                raise ValueError('Invalid volatility observation')
            if utc_timestamp(self.volatility_available_at)>stamp: raise ValueError('Future volatility observation')


@dataclass(frozen=True)
class ModuleBudget:
    system_id: str
    instrument: str
    weight: float


@dataclass(frozen=True)
class AllocationDecision:
    status: str
    budgets: tuple[ModuleBudget, ...] | None
    cash_weight: float | None
    reasons: tuple[str, ...]

    def validate(self, request):
        if self.status=='unavailable':
            if self.budgets is not None or self.cash_weight is not None:
                raise ValueError('Unavailable is not a liquidation target')
            return
        if self.status!='ready' or request.data_status!='complete' or request.signal.status!='ready':
            raise ValueError('Unavailable inputs cannot produce new targets')
        if self.budgets is None or self.cash_weight is None: raise ValueError('Ready requires explicit targets')
        by_id={intent.system_id:intent for intent in request.signal.intents}
        if len({b.system_id for b in self.budgets})!=len(self.budgets): raise ValueError('Duplicate attribution')
        for budget in self.budgets:
            intent=by_id.get(budget.system_id)
            if intent is None or budget.instrument not in {'TQQQ','SQQQ'} or budget.instrument!=intent.instrument:
                raise ValueError('Unknown module or instrument')
            if not math.isfinite(budget.weight) or budget.weight<0: raise ValueError('Invalid module budget')
            if budget.weight and (not intent.direction or intent.direction!=request.signal.portfolio_direction):
                raise ValueError('Suppressed/inactive signal cannot receive allocation')
        exposure=sum(b.weight for b in self.budgets)
        if request.policy.max_position_exposure is not None:
            for instrument in ['TQQQ','SQQQ']:
                if sum(b.weight for b in self.budgets if b.instrument==instrument)>request.policy.max_position_exposure+1e-12:
                    raise ValueError('Position exposure exceeds cap')
        if exposure and request.volatility is None: raise ValueError('Missing volatility blocks exposure targets')
        cap=request.policy.max_etf_exposure
        if request.volatility is not None: cap*=min(1,request.policy.volatility_target/request.volatility)
        if exposure>cap+1e-12: raise ValueError('ETF exposure exceeds cap')
        if not math.isfinite(self.cash_weight) or self.cash_weight<0 or not math.isclose(exposure+self.cash_weight,1,abs_tol=1e-12):
            raise ValueError('Cash plus ETF weights must equal NAV')


class PositionSizer(Protocol):
    def allocate(self, request: SizingRequest) -> AllocationDecision: ...
