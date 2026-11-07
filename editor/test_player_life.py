"""Offline fake-memory tests for active player health. No emulator connections."""
import struct
import tempfile
import unittest
from pathlib import Path
from player_life import PlayerLifeBindings, BOOL_VTABLE_RVA, LIFE_VTABLE_RVA, VALUE_VTABLE_RVA


class Client:
    def __init__(self, base):
        self.base, self.memory, self.calls = base, {}, []
        self.enabled, self.timeout = True, False
        self.pages, self.searches = [[0x2100020000]], 0
        self.put(0x2100010000, struct.pack('<Q', base+BOOL_VTABLE_RVA))
        self.component(0x2100020000, 0x2100040000)

    def component(self, address, owner):
        self.put(address, struct.pack('<Q', self.base+LIFE_VTABLE_RVA))
        self.put(address+0x18, struct.pack('<Q', owner))
        self.put(owner+0x20, struct.pack('<Q', owner+0x1000))
        self.put(owner+0x1000, b'Player\0')
        self.put(owner+0x270, struct.pack('<Q', owner+0x2000))
        self.put(owner+0x2000+0x2b8, struct.pack('<Q', address))
        self.put(address+0x1c10, struct.pack('<QQ', 0x2100080000, 0x2100080010))
        self.put(0x2100080000, struct.pack('<QII', self.base+VALUE_VTABLE_RVA, 10, 0x31ab5580))
        self.put(0x2100080010, struct.pack('<QII', self.base+VALUE_VTABLE_RVA, 12, 0xfbe01da1))

    def put(self, address, data):
        self.memory.update({address+i:value for i,value in enumerate(data)})

    def read(self, address, size):
        return bytes(self.memory.get(address+i, 0) for i in range(size))

    def status(self):
        return dict(live_inventory_enabled=self.enabled)

    def search(self, pattern, **kwargs):
        assert pattern == struct.pack('<Q', self.base+LIFE_VTABLE_RVA)
        page = self.pages[self.searches]
        self.searches += 1
        return dict(start=kwargs.get('start','0x2100000000'), end='0x2100100000',
                    hits=list(map(hex,page)), complete=self.searches==len(self.pages), next='0x2100030000')

    def compare_write(self, address, expected, value):
        self.calls.append((address,expected,value))
        if self.timeout: raise TimeoutError('unknown outcome')
        actual = struct.unpack('<I',self.read(address,4))[0]
        swapped = actual == expected
        if swapped:
            self.put(address,struct.pack('<I',value))
            actual = value
        return dict(swapped=swapped, actual=actual, readback_matches=actual==value)


class Bindings:
    def __init__(self, base=0x80a42000):
        self.client = Client(base)
        self.bool_desc = dict(bank=0x2100010000)
        self.session_id = (1,'one')
        self.actual_session = self.session_id

    def validate(self):
        if self.actual_session != self.session_id: raise ValueError('Session changed')


class PlayerLifeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.directory.cleanup)
        self.binding = Bindings()
        self.life = PlayerLifeBindings(self.binding,self.directory.name)
        self.life.bind()

    def test_binding_is_read_only_and_relocation_is_fresh(self):
        self.assertEqual(self.life.read()['current'],10)
        self.assertEqual(self.binding.client.calls,[])
        other=PlayerLifeBindings(Bindings(0x8016a000),self.directory.name)
        self.assertEqual(other.bind()['maximum'],12)

    def test_single_current_cas_and_audit(self):
        receipt=self.life.write_current(10,11)
        self.assertEqual(receipt['state'],'applied')
        self.assertEqual(self.binding.client.calls,[(0x2100080008,10,11)])
        self.assertEqual(receipt['after']['hearts'],2.75)
        self.assertTrue(Path(receipt['audit_path']).exists())
        self.assertFalse(receipt['automatic_rollback'])
        self.assertFalse(receipt['save_file_effect_verified'])

    def test_mismatch_preserves_health_no_retry(self):
        receipt=self.life.write_current(12,8)
        self.assertEqual(receipt['state'],'expected_mismatch_no_change')
        self.assertEqual(self.life.read()['current'],10)
        self.assertEqual(len(self.binding.client.calls),1)

    def test_uncertain_never_retries_or_rolls_back(self):
        self.binding.client.timeout=True
        with self.assertRaisesRegex(RuntimeError,'do not retry'):
            self.life.write_current(10,8)
        self.assertEqual(len(self.binding.client.calls),1)

    def test_session_change_blocks_write(self):
        self.binding.actual_session=(2,'two')
        with self.assertRaises(ValueError):self.life.write_current(10,8)
        self.assertEqual(self.binding.client.calls,[])

    def test_capability_required_each_write(self):
        self.binding.client.enabled=False
        with self.assertRaises(ValueError):self.life.write_current(10,8)
        self.assertEqual(self.binding.client.calls,[])

    def test_owner_relation_revalidated_each_write(self):
        self.binding.client.put(0x21000422b8,struct.pack('<Q',0))
        with self.assertRaises(ValueError):self.life.write_current(10,8)
        self.assertEqual(self.binding.client.calls,[])

    def test_wrapper_hash_revalidated_each_write(self):
        self.binding.client.put(0x210008000c,struct.pack('<I',0xfbe01da1))
        with self.assertRaises(ValueError):self.life.write_current(10,8)
        self.assertEqual(self.binding.client.calls,[])

    def test_values_bound_by_actual_maximum(self):
        for value in (13,81,-1,True,2.5):
            with self.subTest(value=value),self.assertRaises(ValueError):self.life.write_current(10,value)
        self.assertEqual(self.binding.client.calls,[])

    def test_search_must_finish_all_pages(self):
        binding=Bindings()
        binding.client.pages=[[0x2100020000],[]]
        life=PlayerLifeBindings(binding,self.directory.name)
        life.bind()
        self.assertEqual(binding.client.searches,2)

    def test_multiple_player_candidates_refused(self):
        binding=Bindings()
        binding.client.component(0x2100030000,0x2100060000)
        binding.client.pages=[[0x2100020000,0x2100030000]]
        with self.assertRaises(ValueError):PlayerLifeBindings(binding,self.directory.name).bind()

    def test_no_maximum_or_magic_writer(self):
        self.assertFalse(hasattr(self.life,'write_maximum'))
        self.assertFalse(self.life.read()['max_edit_supported'])
        self.assertFalse(self.life.read()['magic_edit_supported'])


if __name__=='__main__': unittest.main(verbosity=2)
