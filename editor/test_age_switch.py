"""Age switching must bookmark before publication and retain the captured pose."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from age_switch import AgeSwitch


class AgeSwitchTest(unittest.TestCase):
    def setUp(self):
        self.origin=dict(banc='KokiriForest_Child',age='Child',position=[90.3,115.49,-27.9],
            rotation=[0.,-1.4,0.],rotation_units='radians',source='fresh capture')
        self.store=Mock()
        self.store.save.return_value={'id':'saved','pose':copy.deepcopy(self.origin)}
        self.binding=SimpleNamespace(schema={'source_sha256':'revision'})
        self.transport=SimpleNamespace(binding=self.binding,validate=Mock(),
            fields=SimpleNamespace(capture=Mock(side_effect=lambda:copy.deepcopy(self.origin))),
            warp=Mock(return_value={'state':'arrived'}))
        p=patch('age_switch.TeleportTransport',return_value=self.transport);p.start();self.addCleanup(p.stop)

    def test_bookmark_precedes_warp_and_same_area_coordinates_facing_are_retained(self):
        def warp(pose,revision,**options):
            self.store.save.assert_called_once()
            self.assertEqual(pose,dict(self.origin,age='Adult',entry=''))
            self.assertEqual(revision,'revision')
            self.assertEqual(options,{'target_age':'Adult','allow_any_era':True})
            return {'state':'arrived'}
        self.transport.warp.side_effect=warp
        switch=AgeSwitch(self.binding,self.store);result=switch.switch('Adult')
        self.assertEqual(self.store.save.call_args.args[1],self.origin)
        self.assertEqual(result['origin_bookmark']['pose']['age'],'Child')
        self.assertEqual(switch.last_bookmark['id'],'saved')

    def test_age_neutral_area_and_adult_to_child_keep_exact_area(self):
        self.origin.update(banc='FireTemple',age='Adult')
        AgeSwitch(self.binding,self.store).switch('Child')
        self.assertEqual(self.transport.warp.call_args.args[0],dict(self.origin,age='Child',entry=''))

    def test_failed_bookmark_does_not_request_native_switch(self):
        self.store.save.side_effect=OSError('Disk full')
        with self.assertRaises(OSError):AgeSwitch(self.binding,self.store).switch('Adult')
        self.transport.warp.assert_not_called()

    def test_failed_native_switch_keeps_recovery_bookmark_and_is_not_retried(self):
        self.transport.warp.side_effect=TimeoutError('Uncertain native request')
        switch=AgeSwitch(self.binding,self.store)
        with self.assertRaises(TimeoutError):switch.switch('Adult')
        self.assertEqual(switch.last_bookmark['id'],'saved')
        self.transport.warp.assert_called_once()

    def test_invalid_or_same_age_and_busy_game_do_not_save_or_warp(self):
        for age in ('Unknown','Child'):
            with self.assertRaises(ValueError):AgeSwitch(self.binding,self.store).switch(age)
        self.transport.validate.side_effect=ValueError('Event is active')
        with self.assertRaises(ValueError):AgeSwitch(self.binding,self.store).switch('Adult')
        self.store.save.assert_not_called();self.transport.warp.assert_not_called()


if __name__=='__main__':unittest.main()
