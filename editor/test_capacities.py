import struct
import unittest
from capacities import CapacityBindings,SCHEMA,upgrade_changes
from test_live import Planned

class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.parent=Planned()
        for name,row in SCHEMA['fields'].items():
            _,data=self.parent.object(row['hash'],'Int')
            initial=200 if name=='Rupee' else 0
            struct.pack_into('<II',data,28,initial,initial)
        self.b=CapacityBindings(self.parent)
        self.b.validate=lambda:None
    def test_native_limits(self):
        self.assertEqual(upgrade_changes('wallet','Item_Wallet_Large'),{'capacities':{'Rupee':1000}})
        self.assertEqual(upgrade_changes('quiver','Item_Quiver_Medium'),{'capacities':{'Arrow':40}})
        self.assertEqual(upgrade_changes('bomb_bag',None),{'capacities':{'Bomb':0}})
    def test_both_live_and_save_words(self):
        plan=self.b.write_plan({'Arrow':40})
        a,_=self.parent.object(SCHEMA['fields']['Arrow']['hash'],'Int')
        self.assertEqual([(r['address'],r['value']) for r in plan],[(a+28,40),(a+32,40)])
    def test_rejects_wrong_game_limits_and_unknown_fields(self):
        for changes in ({'Rupee':999},{'Arrow':99},{'Arrow':True},{'unknown':30}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.b.write_plan(changes)
    def test_readback_is_actual_capacity(self):
        self.assertEqual(self.b.view()['Rupee'],200)
        self.assertEqual(self.b.view()['Arrow'],0)

if __name__=='__main__':unittest.main()
