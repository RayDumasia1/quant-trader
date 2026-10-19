"""V1.1 NDX research rules, with virtual signal state and zero execution code."""
from dataclasses import dataclass
import json
import math
from pathlib import Path

import pandas as pd

from quant_trader.data.calendar import latest_session, schedule, utc_timestamp
from quant_trader.data.datasets import canonical, checksum
from quant_trader.strategies.base import Intent, ModuleDiagnostic, ModuleState, Signal, StrategyState

RULES = {'momentum_long': ('TQQQ',1), 'dip_center':('TQQQ',1),
         'dip_band':('TQQQ',1), 'dip_fast':('TQQQ',1),
         'momentum_short':('SQQQ',-1), 'breakdown_band':('SQQQ',-1),
         'rally_band':('SQQQ',-1)}


@dataclass(frozen=True)
class Rule:
    system_id: str
    instrument: str
    direction: int
    rule: str
    max_hold: int
    extension: float


def aggregate(intents):
    votes = {intent.direction for intent in intents if intent.direction}
    if len(votes) > 1:
        return 0, 'conflict_opposing_votes_flat'
    return next(iter(votes), 0), 'same_side_votes_combined' if votes else 'no_active_systems'


class SevenSystemStrategy:
    required_price_inputs = ('NDX:price_index_close:NASDAQ:completed_session',)

    def __init__(self, config):
        # Frozen canonical copy prevents caller mutation from changing a running strategy.
        data = json.loads(canonical(config))
        allowed = {'strategy_id','version','assumption_status','trend_window','fast_window',
                   'center_window','band_window','band_std','cooldown_sessions','conflict_policy','modules'}
        if set(data) != allowed: raise ValueError('Unexpected or missing configuration keys')
        if any(not isinstance(data[key],str) or not data[key] for key in ['strategy_id','version','assumption_status']):
            raise ValueError('Strategy identity and assumption status must be explicit')
        if data['conflict_policy'] != 'opposing_votes_flat': raise ValueError('Unsupported conflict policy')
        for key in ['trend_window','fast_window','center_window','band_window']:
            if type(data[key]) is not int or data[key] < 2: raise ValueError('Invalid indicator period')
        if not 2 <= data['center_window'] <= data['fast_window'] <= data['trend_window']:
            raise ValueError('Require center <= fast <= trend')
        if not math.isfinite(data['band_std']) or data['band_std'] <= 0: raise ValueError('Invalid band deviation')
        if type(data['cooldown_sessions']) is not int or data['cooldown_sessions'] < 1: raise ValueError('Invalid cooldown')
        self.rules = tuple(Rule(**module) for module in data['modules'])
        if len(self.rules) != 7 or len({rule.system_id for rule in self.rules}) != 7 or {rule.rule for rule in self.rules} != set(RULES):
            raise ValueError('Exactly seven independent, unique systems are required')
        for rule in self.rules:
            if RULES[rule.rule] != (rule.instrument,rule.direction): raise ValueError('Instrument/direction mismatch')
            if type(rule.max_hold) is not int or rule.max_hold < 1 or not math.isfinite(rule.extension):
                raise ValueError('Invalid module parameters')
        self._config = canonical(data)
        self.parameter_id = checksum(self._config)
        self.strategy_id, self.version = data['strategy_id'], data['version']
        self.lookback = max(data['trend_window'],data['band_window']) + 1

    @classmethod
    def from_file(cls, path='configs/strategies/tqqq_sqqq_v1.1.json'):
        return cls(json.loads(Path(path).read_text()))

    def initial_state(self):
        return StrategyState(self.parameter_id, tuple(ModuleState(rule.system_id) for rule in self.rules))

    def features(self, closes):
        data = json.loads(self._config)
        frame = pd.DataFrame({'close':closes})
        frame['trend'] = frame.close.rolling(data['trend_window']).mean()
        frame['fast'] = frame.close.rolling(data['fast_window']).mean()
        frame['center'] = frame.close.rolling(data['center_window']).mean()
        middle = frame.close.rolling(data['band_window']).mean()
        sigma = frame.close.rolling(data['band_window']).std(ddof=0)
        frame['upper'] = middle + data['band_std'] * sigma
        frame['lower'] = middle - data['band_std'] * sigma
        frame['ext_center'] = frame.close / frame.center - 1
        frame['ext_fast'] = frame.close / frame.fast - 1
        return frame

    @staticmethod
    def conditions(rule, current, previous):
        c, p = current, previous
        bull, bear = c['close'] > c['trend'], c['close'] < c['trend']
        cross_up = p['close'] <= p['center'] and c['close'] > c['center']
        cross_down = p['close'] >= p['center'] and c['close'] < c['center']
        entry, exit_ = {
            'momentum_long': (bull and c['fast'] > c['trend'] and cross_up,
                              c['close'] < c['fast'] or c['ext_center'] >= rule.extension),
            'dip_center': (bull and c['ext_center'] <= rule.extension, c['close'] >= c['center']),
            'dip_band': (bull and c['close'] < c['lower'], c['close'] >= c['center']),
            'dip_fast': (bull and c['ext_fast'] <= rule.extension, c['close'] >= c['center']),
            'momentum_short': (bear and c['fast'] < c['trend'] and cross_down,
                               c['close'] > c['fast'] or c['ext_center'] <= rule.extension),
            'breakdown_band': (bear and p['close'] >= p['lower'] and c['close'] < c['lower'],
                               c['close'] >= c['center']),
            'rally_band': (bear and c['close'] > c['upper'] and c['ext_center'] >= rule.extension,
                           c['close'] <= c['center']),
        }[rule.rule]
        # Mean-reversion and short band systems also exit if their trend gate reverses.
        if rule.rule in {'dip_center','dip_band','dip_fast'}: exit_ = exit_ or not bull
        if rule.rule in {'breakdown_band','rally_band'}: exit_ = exit_ or not bear
        return bool(entry), bool(exit_)

    def transition(self, rule, state, *, session, entry, exit_):
        cooldown = json.loads(self._config)['cooldown_sessions']
        if state.active:
            held = state.holding_sessions + 1
            if held >= rule.max_hold or exit_:
                reason = 'maximum_holding_sessions' if held >= rule.max_hold else 'exit_condition'
                return ModuleState(rule.system_id,cooldown_remaining=cooldown), Intent(rule.system_id,rule.instrument,0,'exit',reason)
            return ModuleState(rule.system_id,True,state.entered_session,held), Intent(rule.system_id,rule.instrument,rule.direction,'hold','entry_intent_still_active')
        if state.cooldown_remaining:
            return ModuleState(rule.system_id,cooldown_remaining=state.cooldown_remaining-1), Intent(rule.system_id,rule.instrument,0,'cooldown','reentry_cooldown')
        # Do not open a signal already satisfying an exit condition.
        if entry and not exit_:
            return ModuleState(rule.system_id,True,session), Intent(rule.system_id,rule.instrument,rule.direction,'enter','entry_condition')
        return ModuleState(rule.system_id), Intent(rule.system_id,rule.instrument,0,'flat','entry_condition_not_met_or_exit_already_true')

    def evaluate(self, snapshot, state):
        as_of = utc_timestamp(snapshot.as_of)
        if state.parameter_id != self.parameter_id or tuple(s.system_id for s in state.modules) != tuple(r.system_id for r in self.rules):
            raise ValueError('State belongs to different strategy parameters or system order')
        for module in state.modules:
            if type(module.active) is not bool or type(module.holding_sessions) is not int or type(module.cooldown_remaining) is not int:
                raise ValueError('Invalid state types')
            if module.holding_sessions < 0 or module.cooldown_remaining < 0:
                raise ValueError('Negative state counters')
            if module.active:
                if module.entered_session is None or state.last_session is None or module.entered_session > state.last_session or module.cooldown_remaining:
                    raise ValueError('Inconsistent active signal state')
            elif module.entered_session is not None or module.holding_sessions:
                raise ValueError('Inconsistent flat signal state')
        latest = latest_session(as_of)
        def blocked(reason, status='blocked'):
            return Signal(self.strategy_id,self.version,self.parameter_id,snapshot.dataset_id,
                          as_of.isoformat(),None,latest['session'],None,status,(),None,reason,state,
                          module_diagnostics=tuple(ModuleDiagnostic(rule.system_id,rule.instrument,
                              module,module,None,None,(),None,None,None,reason)
                              for rule,module in zip(self.rules,state.modules)))
        if not snapshot.dataset_id: return blocked('missing_dataset_identifier')
        bars = snapshot.bars
        if not bars: return blocked('missing_ndx_data')
        if any(b.symbol != 'NDX' for b in bars): return blocked('wrong_signal_instrument')
        if any(not math.isfinite(b.close) or b.close <= 0 for b in bars): return blocked('invalid_close')
        if any(utc_timestamp(b.available_at) > as_of for b in bars): return blocked('future_information')
        sessions = [b.session for b in bars]
        if sessions != sorted(set(sessions)): return blocked('unordered_or_duplicate_sessions')
        if sessions[-1] != latest['session']: return blocked('stale_or_future_session')
        if state.last_session is not None:
            if state.last_session >= latest['session']: return blocked('duplicate_or_reversed_evaluation')
            subsequent = schedule(state.last_session, latest['session'])
            if len(subsequent) != 2 or subsequent[0]['session'] != state.last_session:
                return blocked('state_requires_sequential_session_replay')
        relevant = bars[-self.lookback:]
        expected = schedule(relevant[0].session, latest['session'])
        if [b.session for b in relevant] != [row['session'] for row in expected]: return blocked('missing_or_nonmarket_session')
        if any(utc_timestamp(bar.available_at) < utc_timestamp(row['available_at']) for bar,row in zip(relevant,expected)):
            return blocked('availability_before_completed_session')
        if len(relevant) < self.lookback: return blocked('indicator_warmup', 'warmup')
        frame = self.features([bar.close for bar in relevant])
        current, previous = frame.iloc[-1].to_dict(), frame.iloc[-2].to_dict()
        new_states, intents, conditions = [], [], []
        for rule, module in zip(self.rules,state.modules):
            entry, exit_ = self.conditions(rule,current,previous)
            new_state, intent = self.transition(rule,module,session=latest['session'],entry=entry,exit_=exit_)
            new_states.append(new_state); intents.append(intent)
            conditions.append((entry,exit_))
        direction, reason = aggregate(intents)
        later = schedule(latest['session'], (as_of + pd.Timedelta(days=14)).date())
        next_open = next(row['open_at'] for row in later if row['session'] > latest['session'])
        if utc_timestamp(next_open) <= as_of:
            return blocked('missed_next_session_open')
        available_at = max((utc_timestamp(bar.available_at) for bar in relevant)).isoformat()
        accepted = sum(intent.direction == direction for intent in intents) if direction else 0
        attribution = []
        for rule,before,after,intent,(entry,exit_) in zip(self.rules,state.modules,new_states,intents,conditions):
            c,p = current,previous
            checks = {'bull_gate':c['close']>c['trend'], 'bear_gate':c['close']<c['trend'],
                      'close_below_fast':c['close']<c['fast'], 'close_above_fast':c['close']>c['fast'],
                      'at_or_above_center':c['close']>=c['center'], 'at_or_below_center':c['close']<=c['center'],
                      'below_lower_band':c['close']<c['lower'], 'above_upper_band':c['close']>c['upper'],
                      'cross_above_center':p['close']<=p['center'] and c['close']>c['center'],
                      'cross_below_center':p['close']>=p['center'] and c['close']<c['center'],
                      'cross_below_lower':p['close']>=p['lower'] and c['close']<c['lower'],
                      'fast_above_trend':c['fast']>c['trend'], 'fast_below_trend':c['fast']<c['trend'],
                      'extension_center_ge_threshold':c['ext_center']>=rule.extension,
                      'extension_center_le_threshold':c['ext_center']<=rule.extension,
                      'extension_fast_le_threshold':c['ext_fast']<=rule.extension,
                      'holding_limit_reached':before.active and before.holding_sessions+1>=rule.max_hold,
                      'cooldown_blocks_entry':not before.active and before.cooldown_remaining>0}
            contributes = bool(direction and intent.direction==direction)
            attribution.append(ModuleDiagnostic(rule.system_id,rule.instrument,before,after,entry,exit_,
                tuple(sorted((name,bool(value)) for name,value in checks.items())),intent.direction,
                intent.direction if contributes else 0,1/accepted if contributes else 0.0,
                'suppressed_by_conflict' if not direction and intent.direction else intent.reason))
        return Signal(self.strategy_id,self.version,self.parameter_id,snapshot.dataset_id,
                      as_of.isoformat(),available_at,latest['session'],next_open,'ready',tuple(intents),
                      direction,reason,StrategyState(self.parameter_id,tuple(new_states),latest['session']),
                      tuple(sorted(current.items())),tuple(attribution))
