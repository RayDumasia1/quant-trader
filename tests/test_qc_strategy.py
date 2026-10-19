from dataclasses import replace
from unittest.mock import patch
import unittest

import pandas as pd

from quant_trader.data.calendar import schedule
from quant_trader.strategies.base import ModuleState, PriceBar, StrategyState, as_of_snapshot
from quant_trader.strategies.seven_system import SevenSystemStrategy


class TargetedStrategyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.strategy=SevenSystemStrategy.from_file()
        cls.calendar=schedule('2024-01-02','2025-01-31')

    def snapshot(self,closes):
        bars=tuple(PriceBar('NDX',row['session'],float(close),row['available_at'])
                   for row,close in zip(self.calendar,closes))
        return as_of_snapshot(bars,as_of=bars[-1].available_at,dataset_id='synthetic-qc')

    def test_three_mean_reversion_entries_overlap_without_triple_exposure_vote(self):
        result=self.strategy.evaluate(self.snapshot([60]*150+[100]*50+[94]),self.strategy.initial_state())
        ids={'mean_reversion_long_1','mean_reversion_long_2','mean_reversion_long_3'}
        entries=[intent for intent in result.intents if intent.action=='enter']
        self.assertEqual({intent.system_id for intent in entries},ids)
        self.assertEqual(result.portfolio_direction,1)
        self.assertEqual(len(result.module_diagnostics),7)
        for diagnostic in result.module_diagnostics:
            if diagnostic.system_id in ids:
                self.assertTrue(diagnostic.entry_condition)
                self.assertAlmostEqual(diagnostic.attribution_fraction,1/3)
        follow=self.strategy.evaluate(self.snapshot([60]*150+[100]*50+[94,95]),result.state)
        self.assertEqual(sum(i.action=='hold' for i in follow.intents),3)
        self.assertAlmostEqual(sum(d.attribution_fraction for d in follow.module_diagnostics),1)

    def test_controlled_indicator_reversals_conflict_timeout_and_cooldown(self):
        # Fixed indicator fixtures exercise state integration, not market returns.
        strategy=self.strategy;modules=list(strategy.initial_state().modules)
        index=next(i for i,r in enumerate(strategy.rules) if r.rule=='momentum_short')
        modules[index]=ModuleState(strategy.rules[index].system_id,True,self.calendar[172]['session'],27)
        state=StrategyState(strategy.parameter_id,tuple(modules),self.calendar[199]['session'])
        defaults={'close':94.,'trend':70.,'fast':100.,'center':100.,'lower':97.,'upper':105.,'ext_center':-.06,'ext_fast':-.06}
        days=[{}, {'close':68.,'fast':75.,'center':70.,'lower':65.,'ext_center':-.03,'ext_fast':-.09},
              {'close':69.,'fast':75.,'center':70.,'lower':65.,'ext_center':-.01,'ext_fast':-.08},
              {'close':72.,'fast':80.,'center':76.,'lower':73.,'ext_center':-.05,'ext_fast':-.10},
              {'close':68.,'fast':75.,'center':70.,'lower':65.,'ext_center':-.03,'ext_fast':-.09},
              {'close':74.,'fast':80.,'center':78.,'lower':75.,'ext_center':-.05,'ext_fast':-.07},
              {'close':73.,'fast':80.,'center':78.,'lower':75.,'ext_center':-.06,'ext_fast':-.09}]
        outputs=[];previous=defaults
        for offset,overrides in enumerate(days):
            current={**defaults,**overrides}
            frame=pd.DataFrame([previous,current])
            with patch.object(strategy,'features',return_value=frame):
                result=strategy.evaluate(self.snapshot([100.]*(201+offset)),state)
            self.assertEqual(result.status,'ready');outputs.append(result);state=result.state;previous=current
        self.assertEqual(outputs[0].reason,'conflict_opposing_votes_flat')
        self.assertEqual(outputs[0].portfolio_direction,0)
        self.assertTrue(any(d.reason=='suppressed_by_conflict' for d in outputs[0].module_diagnostics))
        self.assertEqual(outputs[1].portfolio_direction,-1)
        self.assertEqual(next(i for i in outputs[2].intents if i.system_id=='momentum_short_1').reason,'maximum_holding_sessions')
        self.assertEqual(next(i for i in outputs[3].intents if i.system_id=='momentum_short_1').action,'cooldown')
        self.assertTrue(all(i.action=='cooldown' for i in outputs[5].intents if i.system_id.startswith('mean_reversion_long')))
        self.assertEqual(outputs[6].portfolio_direction,1)

    def test_missing_data_preserves_active_state_and_unavailable_attribution(self):
        closes=[60]*150+[100]*50+[94]
        first=self.strategy.evaluate(self.snapshot(closes),self.strategy.initial_state())
        missing=replace(self.snapshot(closes+[95]),bars=self.snapshot(closes).bars)
        blocked=self.strategy.evaluate(missing,first.state)
        self.assertIsNone(blocked.portfolio_direction);self.assertEqual(blocked.state,first.state)
        self.assertEqual(len(blocked.module_diagnostics),7)
        self.assertTrue(all(d.entry_condition is None and d.attribution_fraction is None for d in blocked.module_diagnostics))
        flat=self.strategy.evaluate(self.snapshot([100]*201),self.strategy.initial_state())
        self.assertEqual(flat.portfolio_direction,0);self.assertEqual(flat.status,'ready')
        self.assertTrue(all(d.attribution_fraction==0 for d in flat.module_diagnostics))

    def test_attributions_cannot_observe_future_and_baseline_is_200(self):
        closes=[60]*150+[100]*50+[94]
        old=self.snapshot(closes);future=self.snapshot(closes+[1000])
        future=as_of_snapshot(future.bars,as_of=old.as_of,dataset_id=old.dataset_id)
        self.assertEqual(self.strategy.evaluate(old,self.strategy.initial_state()),self.strategy.evaluate(future,self.strategy.initial_state()))
        self.assertEqual(self.strategy.lookback,201)


if __name__=='__main__':unittest.main()
