import struct
import unittest
from enhancements import EnhancementBindings,SCHEMA,upgrade_changes
from test_live import Planned

class EnhancementTests(unittest.TestCase):
    def setUp(self):
        self.b=EnhancementBindings(Planned())
        self.b.validate=lambda:None
        self.b.view=lambda:dict(DiveDepth=3.0,LiftGrade='None',MP=0,MPMax=0,IsDefenseUP=False)
        self.objects={}
        for i,(name,field) in enumerate(SCHEMA['fields'].items()):
            data=bytearray(56)
            if field['type']=='Float':struct.pack_into('<ff',data,28,3.0,3.0)
            if field['type']=='Enum':struct.pack_into('<II',data,28,field['values']['None'],field['values']['None'])
            self.objects[field['name']]=(0x400000+i*64,data)
        self.b._object=lambda field:self.objects[field['name']]
    def test_exact_remake_values(self):
        self.assertEqual(upgrade_changes('scale','Item_Scale_Gold'),{'enhancements':{'DiveDepth':9.0}})
        self.assertEqual(upgrade_changes('magic','Item_FairyBless_MPDouble'),{'enhancements':{'MP':48,'MPMax':48}})
    def test_float_and_boolean_encoding_preserve_metadata(self):
        plan=self.b.write_plan({'DiveDepth':9.0,'IsDefenseUP':True})
        self.assertEqual([r['value'] for r in plan],[0x41100000,0x41100000,0x01010000])
    def test_magic_capacity_is_written_before_refill(self):
        plan=self.b.write_plan({'MP':48,'MPMax':48})
        self.assertTrue(plan[0]['field'].startswith('MPMax'))
        self.assertEqual(len(plan),4)
        with self.assertRaises(ValueError):self.b.write_plan({'MP':48,'MPMax':24})
    def test_rejects_unmapped_tiers(self):
        for changes in ({'DiveDepth':12.0},{'LiftGrade':'Unknown'},{'IsDefenseUP':1}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.b.write_plan(changes)

if __name__=='__main__':unittest.main()
