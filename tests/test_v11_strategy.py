from dataclasses import replace
import json
import math
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from quant_trader.data.calendar import schedule
from quant_trader.strategies.base import Intent, ModuleState, PriceBar, Snapshot, as_of_snapshot
from quant_trader.strategies.seven_system import SevenSystemStrategy, aggregate


class StrategyV11Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.strategy=SevenSystemStrategy.from_file()
        cls.calendar=schedule('2024-01-02','2025-02-28')
        cls.bars=tuple(PriceBar('NDX',row['session'],100+i*.05+math.sin(i/3),row['available_at'])
                       for i,row in enumerate(cls.calendar))

    def snapshot(self,bars=None,as_of=None):
        return as_of_snapshot(self.bars if bars is None else bars,
                              as_of=as_of or self.calendar[-1]['available_at'],dataset_id='fixture-v1')

    def test_reproducibility_parameter_fingerprint_and_input_preservation(self):
        strategy=self.strategy;state=strategy.initial_state();snapshot=self.snapshot()
        result=strategy.evaluate(snapshot,state)
        self.assertEqual(result,strategy.evaluate(snapshot,state))
        self.assertEqual(state.last_session,None)
        self.assertEqual(result.status,'ready')
        self.assertGreater(pd.Timestamp(result.earliest_execution_at),pd.Timestamp(result.information_available_at))
        config=json.loads(strategy._config);config['band_std']=2.5
        other=SevenSystemStrategy(config)
        self.assertNotEqual(strategy.parameter_id,other.parameter_id)
        with self.assertRaises(ValueError): other.evaluate(snapshot,state)

    def test_future_prices_cannot_change_as_of_signal(self):
        stamp=self.calendar[230]['available_at']
        changed=self.bars[:231]+tuple(replace(bar,close=bar.close*100) for bar in self.bars[231:])
        a=self.strategy.evaluate(self.snapshot(as_of=stamp),self.strategy.initial_state())
        b=self.strategy.evaluate(self.snapshot(bars=changed,as_of=stamp),self.strategy.initial_state())
        self.assertEqual(a,b)
        malformed=Snapshot(stamp,'fixture',self.bars)
        self.assertEqual(self.strategy.evaluate(malformed,self.strategy.initial_state()).reason,'future_information')
        full=self.strategy.features([bar.close for bar in self.bars])
        prefix=self.strategy.features([bar.close for bar in self.bars[:231]])
        assert_frame_equal(full.iloc[:231],prefix)

    def test_warmup_period(self):
        for count,status in [(200,'warmup'),(201,'ready')]:
            bars=self.bars[:count]
            result=self.strategy.evaluate(self.snapshot(bars, bars[-1].available_at),self.strategy.initial_state())
            self.assertEqual(result.status,status)
            if status=='warmup': self.assertIsNone(result.portfolio_direction)

    def test_missing_stale_duplicate_and_wrong_symbol(self):
        state=self.strategy.initial_state()
        for bars,reason in [((), 'missing_ndx_data'), (self.bars[:-1],'stale_or_future_session'),
                            (self.bars[:-2]+self.bars[-1:],'missing_or_nonmarket_session'),
                            (self.bars+self.bars[-1:],'unordered_or_duplicate_sessions'),
                            (tuple(replace(b,symbol='QQQ') for b in self.bars),'wrong_signal_instrument')]:
            with self.subTest(reason=reason):
                result=self.strategy.evaluate(self.snapshot(bars),state)
                self.assertEqual(result.reason,reason)
                self.assertEqual(result.state,state)
                self.assertIsNone(result.portfolio_direction)

    def test_timestamp_and_availability_enforcement(self):
        with self.assertRaises(ValueError): self.snapshot(as_of='2025-02-28')
        bars=tuple(replace(bar,available_at=bar.session+'T00:00:00Z') for bar in self.bars)
        result=self.strategy.evaluate(self.snapshot(bars),self.strategy.initial_state())
        self.assertEqual(result.reason,'availability_before_completed_session')

    def test_every_system_entry_hold_exit_cooldown_and_reentry(self):
        for rule in self.strategy.rules:
            with self.subTest(system=rule.system_id):
                state=ModuleState(rule.system_id)
                state,intent=self.strategy.transition(rule,state,session='2025-01-02',entry=True,exit_=False)
                self.assertTrue(state.active);self.assertEqual(intent.action,'enter')
                state,intent=self.strategy.transition(rule,state,session='2025-01-03',entry=False,exit_=False)
                self.assertEqual(intent.action,'hold');self.assertEqual(state.holding_sessions,1)
                state,intent=self.strategy.transition(rule,state,session='2025-01-06',entry=True,exit_=True)
                self.assertEqual(intent.action,'exit');self.assertFalse(state.active)
                state,intent=self.strategy.transition(rule,state,session='2025-01-07',entry=True,exit_=False)
                self.assertEqual(intent.action,'cooldown')
                state,intent=self.strategy.transition(rule,state,session='2025-01-08',entry=True,exit_=False)
                self.assertEqual(intent.action,'enter')
                expired=replace(state,holding_sessions=rule.max_hold-1)
                expired,intent=self.strategy.transition(rule,expired,session='2025-01-09',entry=True,exit_=False)
                self.assertEqual(intent.reason,'maximum_holding_sessions')

    def test_rule_predicates_for_all_seven_systems(self):
        default={'close':100,'trend':90,'fast':95,'center':99,'lower':97,'upper':103,
                 'ext_center':.01,'ext_fast':.05}
        cases={
            'momentum_long': ({'close':100}, {'close':98,'center':99}),
            'dip_center': ({'close':95,'center':100,'ext_center':-.05}, {}),
            'dip_band': ({'close':95,'center':100,'lower':96}, {}),
            'dip_fast': ({'close':95,'center':100,'ext_fast':-.06}, {}),
            'momentum_short': ({'close':90,'trend':110,'fast':100,'center':95,'ext_center':-.05},{'close':96,'center':95}),
            'breakdown_band': ({'close':90,'trend':110,'center':95,'lower':91},{'close':92,'lower':91}),
            'rally_band': ({'close':105,'trend':110,'upper':104,'center':100,'ext_center':.05},{})}
        for rule in self.strategy.rules:
            current,previous=cases[rule.rule]
            with self.subTest(rule=rule.rule):
                entry,exit_=self.strategy.conditions(rule,{**default,**current},{**default,**previous})
                self.assertTrue(entry);self.assertFalse(exit_)

    def test_conflict_policy_has_no_sizing_or_order_submission(self):
        long=Intent('long','TQQQ',1,'hold','test')
        short=Intent('short','SQQQ',-1,'hold','test')
        self.assertEqual(aggregate([long,short]),(0,'conflict_opposing_votes_flat'))
        self.assertEqual(aggregate([long,long])[0],1)
        self.assertEqual(aggregate([short])[0],-1)
        self.assertEqual(aggregate([])[0],0)

    def test_exit_price_predicates_for_all_systems(self):
        default={'close':100,'trend':90,'fast':95,'center':99,'lower':97,'upper':103,
                 'ext_center':.01,'ext_fast':.05}
        for rule in self.strategy.rules:
            current={**default}
            if rule.rule=='momentum_long': current['close']=94
            elif rule.rule=='momentum_short': current['close']=96
            elif rule.rule=='breakdown_band': current.update(close=100,center=99,trend=110)
            elif rule.rule=='rally_band': current.update(close=99,center=100,trend=110)
            with self.subTest(system=rule.system_id):
                _,exit_=self.strategy.conditions(rule,current,default)
                self.assertTrue(exit_)

    def test_invalid_state_counters_are_rejected(self):
        state=self.strategy.initial_state()
        bad=replace(state,modules=(replace(state.modules[0],holding_sessions=-1),)+state.modules[1:])
        with self.assertRaises(ValueError): self.strategy.evaluate(self.snapshot(),bad)

    def test_late_signal_cannot_propose_an_open_in_the_past(self):
        result=self.strategy.evaluate(self.snapshot(as_of='2025-03-03T15:00:00Z'),self.strategy.initial_state())
        self.assertEqual(result.reason,'missed_next_session_open')
        self.assertIsNone(result.portfolio_direction)

    def test_state_must_be_replayed_sequentially(self):
        first=self.strategy.evaluate(self.snapshot(as_of=self.calendar[230]['available_at']),self.strategy.initial_state())
        duplicate=self.strategy.evaluate(self.snapshot(as_of=self.calendar[230]['available_at']),first.state)
        self.assertEqual(duplicate.reason,'duplicate_or_reversed_evaluation')
        skipped=self.strategy.evaluate(self.snapshot(as_of=self.calendar[232]['available_at']),first.state)
        self.assertEqual(skipped.reason,'state_requires_sequential_session_replay')
        next_=self.strategy.evaluate(self.snapshot(as_of=self.calendar[231]['available_at']),first.state)
        self.assertEqual(next_.status,'ready')


if __name__=='__main__': unittest.main()
