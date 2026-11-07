"""Verify live + serialization updates preserve defaults and metadata."""
import struct
import unittest
from unittest.mock import Mock
from live import Bindings
from bottles import BottleBindings

class Planned(Bindings):
    def __init__(self):
        super().__init__()
        self.current={'rupees':5,'health':12,'max_health':12,
                      'counts':{a:0 for a in self.items},'items':{a:False for a in self.items}}
        self.objects={}
        for i,key in enumerate(self.indices['Int']):
            raw=bytearray(40);struct.pack_into('<III',raw,24,0,0,0x12345678)
            self.objects[(key,'Int')]=(0x100000+i*40,raw)
        for i,key in enumerate(self.indices['Bool']):
            raw=bytearray(24);struct.pack_into('<I',raw,20,0x01003412)
            self.objects[(key,'Bool')]=(0x200000+i*24,raw)
    def view(self):return self.current
    def object(self,key,kind):return self.objects[(key,kind)]

class LivePlannerTests(unittest.TestCase):
    def setUp(self):self.b=Planned()
    def test_count_and_history_grant(self):
        writes=self.b._writes({'items':{'Weapon_Sword_Kokiri':True}})
        stock=self.b.object(self.b.items['Weapon_Sword_Kokiri']['stock_hash'],'Int')[0]
        self.assertEqual(writes[0]['address'],stock+28)
        self.assertEqual(writes[0]['value'],1)
        self.assertEqual(writes[1]['address'],stock+32)
        self.assertEqual(writes[1]['value'],1)
        self.assertEqual(len(writes),3)
        self.assertEqual(writes[2]['value'],0x01013412)
    def test_removal_retains_history(self):
        actor='Weapon_Sword_Kokiri';self.b.current['counts'][actor]=1
        a,d=self.b.object(self.b.items[actor]['stock_hash'],'Int');struct.pack_into('<I',d,28,1)
        writes=self.b._writes({'items':{actor:False}})
        self.assertEqual([(r['address'],r['value']) for r in writes],[(a+28,0),(a+32,0)])
    def test_live_and_save_copies_both_updated(self):
        writes=self.b._writes({'rupees':123})
        a,_=self.b.object(self.b.stats['rupees'],'Int')
        self.assertEqual([(r['address'],r['value']) for r in writes],[(a+28,123),(a+32,123)])
    def test_unmapped_and_out_of_range_rejected(self):
        for changes in ({'counts':{'unknown':1}},{'counts':{'Weapon_Sword_Kokiri':2}},
                        {'counts':{'Item_Bomb':-1}},{'items':{'Item_Bomb':1}},
                        {'health':20},{'max_health':20},{'address':0x1234}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.b._writes(changes)

    def test_wallet_capacity(self):
        self.assertEqual(self.b.wallet_capacity({}),200)
        self.assertEqual(self.b.wallet_capacity({'Item_Wallet_Medium':1}),500)
        self.assertEqual(self.b.wallet_capacity({'Item_Wallet_Large':1}),1000)
        with self.assertRaises(ValueError):self.b._writes({'rupees':201})
        self.b.current['counts']['Item_Wallet_Large']=1
        self.assertTrue(self.b._writes({'rupees':1000}))

class BottlePlannerTests(unittest.TestCase):
    def setUp(self):
        self.parent=Planned()
        self.b=BottleBindings(self.parent)
        self.b.validate=lambda:None
        self.b.view=lambda:{'BottleA':{'owned':True}}
        empty=self.b.schema['slots']['BottleA']['values']['Empty']
        self.b._object=lambda row:(0x300000,empty)
        self.b.client=Mock()
        self.b.client.u32.return_value=empty
    def test_contents_update_both_copies(self):
        plan=self.b.write_plan({'BottleA':'Fairy'})
        self.assertEqual([r['address'] for r in plan],[0x30001c,0x300020])
        self.assertEqual([r['value'] for r in plan],[0x6f49e357]*2)
    def test_visibility_preserves_metadata(self):
        row=self.b.validity_plan({'BottleA':True})[0]
        self.assertEqual(row['expected'],0x01003412)
        self.assertEqual(row['value'],0x01013412)
    def test_invalid_content_or_unowned_rejected(self):
        with self.assertRaises(ValueError):self.b.write_plan({'BottleA':'not-a-content'})
        self.b.view=lambda:{'BottleA':{'owned':False}}
        with self.assertRaises(ValueError):self.b.write_plan({'BottleA':'Fairy'})

if __name__=='__main__':unittest.main()
