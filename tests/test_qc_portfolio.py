from dataclasses import replace
import unittest

from quant_trader.portfolio.contracts import AllocationDecision, ExistingPosition, ModuleBudget, RiskPolicy, SizingRequest
import test_qc_strategy


class PortfolioContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_qc_strategy.TargetedStrategyTests.setUpClass()
        fixture=test_qc_strategy.TargetedStrategyTests()
        cls.signal=fixture.strategy.evaluate(fixture.snapshot([60]*150+[100]*50+[94]),fixture.strategy.initial_state())

    def request(self,**kwargs):
        base=SizingRequest(self.signal,self.signal.signal_at,10000,RiskPolicy(),'complete',.1,self.signal.signal_at)
        return replace(base,**kwargs)

    def decision(self,weight,cash=None):
        return AllocationDecision('ready',(ModuleBudget('mean_reversion_long_1','TQQQ',weight),),1-weight if cash is None else cash,('fixture',))

    def test_pilot_cap_and_separate_higher_scenario(self):
        self.decision(.25).validate(self.request())
        with self.assertRaises(ValueError):self.decision(.26).validate(self.request())
        self.decision(.5).validate(self.request(policy=RiskPolicy(max_etf_exposure=.5)))

    def test_volatility_scales_cap_and_uses_available_observation(self):
        self.decision(.125).validate(self.request(volatility=.2))
        with self.assertRaises(ValueError):self.decision(.126).validate(self.request(volatility=.2))
        with self.assertRaises(ValueError):self.request(volatility_available_at='2099-01-01T00:00:00Z')
        with self.assertRaises(ValueError):self.decision(.1).validate(self.request(volatility=None,volatility_available_at=None))

    def test_unavailable_is_not_flat_or_forced_liquidation(self):
        request=self.request(data_status='missing',positions=(ExistingPosition('TQQQ',10,None,None),))
        AllocationDecision('unavailable',None,None,('preserve existing quantities; block increases',)).validate(request)
        with self.assertRaises(ValueError):AllocationDecision('unavailable',(),1,()).validate(request)
        with self.assertRaises(ValueError):self.decision(.1).validate(request)

    def test_cash_attribution_and_position_limits(self):
        with self.assertRaises(ValueError):self.decision(.2,cash=.9).validate(self.request())
        with self.assertRaises(ValueError):self.decision(-.1).validate(self.request())
        with self.assertRaises(ValueError):self.decision(.2).validate(self.request(policy=RiskPolicy(max_position_exposure=.1)))
        wrong=AllocationDecision('ready',(ModuleBudget('momentum_short_1','SQQQ',.1),),.9,())
        with self.assertRaises(ValueError):wrong.validate(self.request())
        with self.assertRaises(ValueError):self.request(positions=(ExistingPosition('TQQQ',10,100,'2099-01-01T00:00:00Z'),))


if __name__=='__main__':unittest.main()
