"""Ocarina selector publication, wrapper preservation and ordinary undo."""
import struct
import unittest
from types import SimpleNamespace
from ocarinas import write_plan,ACTORS,FIELD_HASH
from live import Bindings


class OcarinaTest(unittest.TestCase):
    def setUp(self):
        self.raw=bytearray(264);self.address=0x100000
        for wrapper in (24,104,184):
            struct.pack_into('<QI',self.raw,wrapper,self.address+wrapper+12,64)
        field=dict(hash=FIELD_HASH,type='String64')
        assignment=SimpleNamespace(validate=lambda:None,schema={'fields':{'EquipOcarina':field}},
            _string=lambda f:{'actor':bytes(self.raw[116:180]).split(b'\0')[0].decode()},
            _object=lambda f:(self.address,bytes(self.raw)))
        self.binding=SimpleNamespace(assignments=assignment)
        self.current={'counts':{ACTORS[0]:1,ACTORS[1]:0}}

    def execute(self,plan):
        for row in plan:
            off=row['address']-self.address
            self.assertEqual(struct.unpack_from('<I',self.raw,off)[0],row['expected'])
            struct.pack_into('<I',self.raw,off,row['value'])

    def test_grant_uses_item_alias_and_updates_both_copies(self):
        original=bytes(self.raw)
        plan=write_plan(self.binding,{ACTORS[0]:1},self.current)
        self.execute(plan)
        for offset in (116,196):self.assertEqual(self.raw[offset:offset+64].split(b'\0')[0],b'Item_Ocarina_Fairy')
        for a,b in ((0,116),(180,196),(260,264)):
            self.assertEqual(self.raw[a:b],original[a:b])

    def test_time_replacement_empties_prefix_before_tails_and_publish(self):
        self.execute(write_plan(self.binding,{ACTORS[0]:1},self.current))
        plan=write_plan(self.binding,{ACTORS[0]:0,ACTORS[1]:1},self.current)
        self.assertEqual(plan[0]['address'],self.address+116)
        self.assertEqual(plan[0]['value'],0)
        self.execute(plan)
        self.assertEqual(self.raw[116:180].split(b'\0')[0],b'Item_Ocarina_Time')
        self.assertEqual(self.raw[196:260].split(b'\0')[0],b'Item_Ocarina_Time')

    def test_removal_and_reversed_plan_restore_complete_strings(self):
        self.execute(write_plan(self.binding,{ACTORS[0]:1},self.current))
        before=bytes(self.raw)
        plan=write_plan(self.binding,{ACTORS[0]:0,ACTORS[1]:0},self.current)
        self.execute(plan);self.assertEqual(self.raw[116:180],bytes(64))
        self.execute([dict(address=r['address'],expected=r['value'],value=r['expected']) for r in reversed(plan)])
        self.assertEqual(bytes(self.raw),before)

    def test_unrelated_edits_do_not_change_equipment(self):
        self.assertEqual(write_plan(self.binding,{'Item_Bomb':1},self.current),[])

    def test_bad_wrapper_refused_before_writes(self):
        self.raw[112]=0
        with self.assertRaises(ValueError):write_plan(self.binding,{ACTORS[0]:1},self.current)

    def test_undo_validates_final_value_for_multi_stage_prefix(self):
        memory={4:20}
        writes=[dict(address=4,expected=10,value=0),dict(address=4,expected=0,value=20)]
        def cas(address,old,new):
            if memory[address]!=old:return {'swapped':False}
            memory[address]=new;return {'swapped':True}
        fake=SimpleNamespace(validate=lambda:None,session_id=('s',1),last_edit={'session':('s',1),'writes':writes},
            client=SimpleNamespace(u32=lambda a:memory[a],compare_write=cas),view=lambda:{})
        Bindings.undo(fake)
        self.assertEqual(memory[4],10)


if __name__=='__main__':unittest.main()
