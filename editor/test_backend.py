import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import backend

FIXTURE=backend.ROOT/'tests-local/progress.sav'

def synthetic_save():
    """Construct a typed table from the public schema, without any player save."""
    rows=list(backend.TYPES.items())
    table_end=0x28+8*len(rows)
    strings=sum(kind=='String64' for _,kind in rows)
    data=bytearray(table_end+64*strings+32)
    struct.pack_into('<III',data,0,0x01020304,0x002d80eb,table_end)
    pointer=table_end;referenced=False
    for index,(key,kind) in enumerate(rows):
        value=0
        if kind=='String64':
            value=pointer
            if not referenced:
                text=b'Armor_Adult_HeavyBoot';data[pointer:pointer+len(text)]=text;referenced=True
            pointer+=64
        struct.pack_into('<II',data,0x28+index*8,key,value)
    offsets={key:0x2c+index*8 for index,(key,_) in enumerate(rows)}
    for key,value in ((backend.STATS['health'],12),(backend.STATS['max_health'],12),
                      (int(backend.ITEMS['Armor_Adult_HeavyBoot']['stock_hash'],16),1)):
        struct.pack_into('<i',data,offsets[key],value)
    data[-16:]=b'preserved-footer'
    return bytes(data)


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.raw=synthetic_save()
        self.save=backend.Save(self.raw)

    def test_known_inventory(self):
        view=self.save.view()
        self.assertTrue(view['items']['Armor_Adult_HeavyBoot'])
        self.assertFalse(view['items']['Weapon_Sword_Kokiri'])
        self.assertEqual((view['rupees'],view['health'],view['max_health']),(0,12,12))

    def test_only_declared_fields_change(self):
        result,writes=self.save.patched({'rupees':123,'health':20,'max_health':20,
                                       'items':{'Weapon_Sword_Kokiri':True,'Weapon_Shield_Deku':True}})
        self.assertEqual(len(writes),7)
        allowed={byte for row in writes for byte in range(row['offset'],row['offset']+4)}
        self.assertEqual(len(result),len(self.raw))
        self.assertTrue(all(index in allowed for index,(a,b) in enumerate(zip(self.raw,result)) if a!=b))
        self.assertEqual(backend.Save(result).view()['rupees'],123)

    def test_invalid_changes_rejected(self):
        cases=[{'rupees':201},{'rupees':-1},{'rupees':True},{'health':100},
               {'max_health':13},{'items':{'unknown':True}},{'items':{'Weapon_Sword_Kokiri':1}},
               {'unmapped_field':1}]
        for changes in cases:
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.save.patched(changes)

    def test_corrupt_headers_rejected(self):
        for offset,value in [(0,0),(4,1),(8,0xffffffff)]:
            data=bytearray(self.raw);struct.pack_into('<I',data,offset,value)
            with self.assertRaises(ValueError):backend.Save(data)

    def test_removing_referenced_equipment_is_rejected(self):
        with self.assertRaises(ValueError):self.save.patched({'items':{'Armor_Adult_HeavyBoot':False}})

    def test_unknown_bytes_preserved_and_noop(self):
        result,writes=self.save.patched({})
        self.assertEqual(result,self.raw)
        self.assertEqual(writes,[])


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=backend.ROOT)
        self.root=Path(self.temp.name)
        self.patch=patch.object(backend,'ROOT',self.root)
        self.patch.start()
        self.path=self.root/f'runtime/nand/user/save/0000/user/{backend.TITLE}/slot_00/progress.sav'
        self.path.parent.mkdir(parents=True)
        self.raw=synthetic_save();self.path.write_bytes(self.raw)

    def tearDown(self):
        self.patch.stop();self.temp.cleanup()

    def test_apply_backup_restore(self):
        directory=backend.apply(self.path,{'rupees':123},backend.digest(self.raw),guard=lambda:None)
        self.assertEqual((directory/'progress.sav').read_bytes(),self.raw)
        self.assertEqual(backend.Save(self.path.read_bytes()).view()['rupees'],123)
        backend.restore(directory,guard=lambda:None)
        self.assertEqual(self.path.read_bytes(),self.raw)

    def test_stale_save_and_running_game_do_not_write(self):
        with self.assertRaises(ValueError):backend.apply(self.path,{'rupees':123},'stale',guard=lambda:None)
        def running():raise ValueError('game running')
        with self.assertRaises(ValueError):backend.apply(self.path,{'rupees':123},backend.digest(self.raw),guard=running)
        self.assertEqual(self.path.read_bytes(),self.raw)

    def test_external_profile_rejected(self):
        with self.assertRaises(ValueError):backend.assert_target(FIXTURE)

    def test_restore_preserves_newer_progress(self):
        directory=backend.apply(self.path,{'rupees':123},backend.digest(self.raw),guard=lambda:None)
        self.path.write_bytes(backend.Save(self.path.read_bytes()).patched({'rupees':124})[0])
        with self.assertRaises(ValueError):backend.restore(directory,guard=lambda:None)
        self.assertEqual(backend.Save(self.path.read_bytes()).view()['rupees'],124)


if __name__=='__main__':unittest.main()
