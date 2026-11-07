"""Offline fake-memory tests; no game connection or emulator process required."""
import struct
import tempfile
import types
import unittest
from pathlib import Path
from test_player_life import Bindings
from player_life import PlayerLifeBindings
from player_magic import PlayerMagicBindings


class PlayerMagicTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.directory.cleanup)
        self.binding=Bindings()
        self.maximum=48
        self.binding.enhancements=types.SimpleNamespace(view=lambda:{'MPMax':self.maximum})
        self.life=PlayerLifeBindings(self.binding,self.directory.name)
        self.life.bind()
        self.component=0x21000a0000
        self.binding.client.put(0x2100042358,struct.pack('<Q',self.component))
        self.binding.client.put(self.component,struct.pack('<Q',self.binding.client.base+0x4b4dfc0))
        self.binding.client.put(self.component+0x18,struct.pack('<Q',0x2100040000))
        self.binding.client.put(self.component+0x1b78,struct.pack('<Q',self.binding.client.base+0x4b633f0))
        self.binding.client.put(self.component+0x1bb0,struct.pack('<II',0x76b18200,0x12d63a97))
        self.binding.client.put(self.component+0x1bbc,struct.pack('<I',24))
        self.magic=PlayerMagicBindings(self.life,self.directory.name)
        self.magic.bind()

    def test_binding_uses_existing_owner_without_search_or_writes(self):
        self.assertEqual(self.binding.client.searches,1)
        self.assertEqual(self.binding.client.calls,[])
        self.assertEqual(self.magic.read()['current'],24)
        self.assertEqual(self.magic.read()['maximum'],48)

    def test_single_cas_only_current_and_audited(self):
        before=dict(self.binding.client.memory)
        receipt=self.magic.write_current(24,48)
        self.assertEqual(receipt['state'],'applied')
        self.assertEqual(self.binding.client.calls,[(self.component+0x1bbc,24,48)])
        changed={k for k in self.binding.client.memory if self.binding.client.memory[k]!=before.get(k,0)}
        self.assertEqual(changed,{self.component+0x1bbc})
        self.assertTrue(Path(receipt['audit_path']).exists())
        self.assertFalse(receipt['automatic_retry'])
        self.assertFalse(receipt['automatic_rollback'])

    def test_pending_delta_blocks_write(self):
        self.binding.client.put(self.component+0x1b90,struct.pack('<i',-1))
        with self.assertRaisesRegex(ValueError,'pending'):self.magic.write_current(24,48)
        self.assertEqual(self.binding.client.calls,[])

    def test_owned_disabled_flags_block_write(self):
        self.binding.client.put(self.component+0x1b88,struct.pack('<I',1))
        with self.assertRaises(ValueError):self.magic.write_current(24,48)
        self.assertEqual(self.binding.client.calls,[])

    def test_typed_hash_and_vtable_revalidated(self):
        self.binding.client.put(self.component+0x1bb0,struct.pack('<I',0))
        with self.assertRaises(ValueError):self.magic.write_current(24,48)
        self.assertEqual(self.binding.client.calls,[])

    def test_reciprocal_owner_relation_revalidated(self):
        self.binding.client.put(self.component+0x18,struct.pack('<Q',0x2100060000))
        with self.assertRaises(ValueError):self.magic.write_current(24,48)
        self.assertEqual(self.binding.client.calls,[])

    def test_session_change_and_optin_block_writes(self):
        self.binding.client.enabled=False
        with self.assertRaises(ValueError):self.magic.write_current(24,48)
        self.binding.client.enabled=True
        self.binding.actual_session=(2,'two')
        with self.assertRaises(ValueError):self.magic.write_current(24,48)
        self.assertEqual(self.binding.client.calls,[])

    def test_capacity_is_game_data_restricted(self):
        self.maximum=25
        with self.assertRaises(ValueError):self.magic.write_current(24,25)
        self.maximum=24
        with self.assertRaises(ValueError):self.magic.write_current(24,25)
        self.assertEqual(self.binding.client.calls,[])

    def test_expected_mismatch_no_retry(self):
        receipt=self.magic.write_current(0,48)
        self.assertEqual(receipt['state'],'expected_mismatch_no_change')
        self.assertEqual(self.magic.read()['current'],24)
        self.assertEqual(len(self.binding.client.calls),1)

    def test_uncertain_no_retry_no_rollback(self):
        self.binding.client.timeout=True
        with self.assertRaisesRegex(RuntimeError,'do not retry'):self.magic.write_current(24,48)
        self.assertEqual(len(self.binding.client.calls),1)

    def test_no_capacity_writer(self):
        self.assertFalse(hasattr(self.magic,'write_capacity'))
        self.assertFalse(self.magic.read()['capacity_edit_supported'])


if __name__=='__main__':unittest.main(verbosity=2)
