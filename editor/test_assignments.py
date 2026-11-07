import struct
import unittest
from assignments import AssignmentBindings
from test_live import Planned

class AssignmentTests(unittest.TestCase):
    def setUp(self):
        self.parent=Planned()
        self.b=AssignmentBindings(self.parent)
        self.b.validate=lambda:None
        self.b._enum=lambda field:None
        raw=bytearray(56);struct.pack_into('<II',raw,28,0xbe69de49,0xbe69de49)
        self.b._object=lambda field:(0x300000,raw)
    def test_ownership_required_and_legal_override(self):
        with self.assertRaises(ValueError):self.b.write_plan({'Child':'Boomerang'})
        self.parent.current['items']['Item_Boomerang']=True
        plan=self.b.write_plan({'Child':'Boomerang'})
        self.assertEqual([(r['address'],r['value']) for r in plan],[(0x30001c,0xd1b7e25f),(0x300020,0xd1b7e25f)])
    def test_rejects_gear_keys_and_unknown_symbols(self):
        for changes in ({'EquipWeapon':'Weapon_Sword_Kokiri'},{'Child':'not-an-item'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.b.write_plan(changes,require_owned=False)
    def test_none_is_noop_for_empty(self):
        self.assertEqual(self.b.write_plan({'Child':None}),[])

if __name__=='__main__':unittest.main()
