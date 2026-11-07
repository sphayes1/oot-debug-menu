"""Teleport transaction safety: publish last, rollback only before publication, never replay."""
import json
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from teleport import TeleportTransport, TRIGGER, AGE, MANUAL_AGE

POSE = dict(banc='KokiriForest_Child', age='Child', position=[1., 2., 3.],
            rotation=[0., .5, 0.], rotation_units='radians')


class Memory:
    def __init__(self):
        self.memory = bytearray(0x2000)
        self.calls = []
        self.fail_at = None
        self.fail_address = None
        self.lose_commit = False
        self.published = False

    def read(self, address, size):
        return bytes(self.memory[address:address + size])

    def compare_write(self, address, expected, value):
        self.calls.append((address, expected, value))
        if self.fail_at == len(self.calls) or self.fail_address == address:
            return {'swapped': False, 'readback_matches': False}
        actual = struct.unpack_from('<I', self.memory, address)[0]
        if actual != expected:
            return {'swapped': False, 'readback_matches': False}
        struct.pack_into('<I', self.memory, address, value)
        if address == 0x514:
            self.published = True
            if self.lose_commit:
                raise TimeoutError('Commit response lost')
        return {'swapped': True, 'readback_matches': True}


class Fields:
    def __init__(self, memory):
        self.memory = memory

    def object(self, kind, key):
        address = {'52046b85': 0x100, '1662143e': 0x200, '0b570ab2': 0x300, 'ee27bf71': 0x400}[key]
        if kind == 'String64':
            struct.pack_into('<Q', self.memory.memory, address + 104, address + 116)
            struct.pack_into('<I', self.memory.memory, address + 112, 64)
        return address, self.memory.read(address, 264 if kind == 'String64' else 64)

    def capture(self):
        return dict(POSE)

    def field(self, kind, key):
        return 'KokiriForest_Child' if key == '1d6189da' else ''


class TransactionTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = patch('teleport.ROOT', Path(self.directory.name))
        self.root.start(); self.addCleanup(self.root.stop)
        self.clock = patch('teleport.time.sleep', lambda _: None)
        self.clock.start(); self.addCleanup(self.clock.stop)
        self.memory = Memory()
        self.binding = SimpleNamespace(client=self.memory, session_id=('session', 1),
            schema={'source_sha256': 'revision'}, validate=lambda: None,
            assignments=SimpleNamespace(view=lambda: {'active_age': 'Child'}),
            object=lambda key, kind: (0x500, self.memory.read(0x500, 24)))
        self.transport = TeleportTransport(self.binding)
        self.transport.fields = Fields(self.memory)
        self.transport.validate = lambda: None
        self.transport.boolean = lambda key: False

    def audit(self):
        return json.loads(next(Path(self.directory.name).rglob('*.json')).read_text(encoding='utf-8'))

    def test_destination_is_complete_before_single_publication(self):
        result = self.transport.warp(POSE, 'revision')
        self.assertEqual(result['state'], 'arrived')
        self.assertEqual(self.memory.calls[-1][0], 0x514)
        self.assertEqual(sum(a == 0x514 for a, _, _ in self.memory.calls), 1)
        self.assertEqual(struct.unpack_from('<3f', self.memory.memory, 0x124), (1., 2., 3.))
        self.assertEqual(self.memory.read(0x474, 18), b'KokiriForest_Child')

    def test_preparation_conflict_rolls_back_without_publishing(self):
        self.memory.fail_at = 3
        with self.assertRaises(ValueError):
            self.transport.warp(POSE)
        self.assertFalse(self.memory.published)
        self.assertEqual(self.memory.read(0x124, 12), bytes(12))
        self.assertEqual(self.audit()['state'], 'cancelled-before-request')

    def test_lost_commit_response_never_retries_or_rolls_back_destination(self):
        self.memory.lose_commit = True
        with self.assertRaises(TimeoutError):
            self.transport.warp(POSE)
        self.assertEqual(sum(a == 0x514 for a, _, _ in self.memory.calls), 1)
        self.assertEqual(self.memory.calls[-1][0], 0x514)
        self.assertEqual(self.memory.read(0x474, 18), b'KokiriForest_Child')
        self.assertEqual(self.audit()['state'], 'uncertain-after-request')

    def test_wrong_revision_era_and_unknown_entry_do_not_write(self):
        for pose, revision in [(POSE, 'other'), (dict(POSE, age='Adult'), None),
                               (dict(POSE, entry='invented'), None),
                               (dict(POSE, rotation_units='degrees'), 'revision')]:
            with self.assertRaises(ValueError):
                self.transport.warp(pose, revision)
        self.assertEqual(self.memory.calls, [])

    def age_setup(self):
        self.binding.object = lambda key, kind: (
            {TRIGGER: 0x500, AGE: 0x600, MANUAL_AGE: 0x700}[key],
            self.memory.read({TRIGGER: 0x500, AGE: 0x600, MANUAL_AGE: 0x700}[key], 24))
        struct.pack_into('<I', self.memory.memory, 0x614, 0x01013412)
        self.adult_pose = dict(POSE, banc='HyruleField_Adult', age='Adult')
        self.transport.fields.field = lambda kind, key: 'HyruleField_Adult' if key == '1d6189da' else ''
        self.transport.fields.capture = lambda: dict(self.adult_pose if self.memory.published else POSE)

    def test_era_override_keeps_link_age_and_unlocks_bookmark_and_preset(self):
        for age in ('Adult', 'Child'):
            self.binding.object=lambda key,kind:({TRIGGER:0x500,AGE:0x600,MANUAL_AGE:0x700}[key],
                self.memory.read({TRIGGER:0x500,AGE:0x600,MANUAL_AGE:0x700}[key],24))
            struct.pack_into('<I',self.memory.memory,0x614,0x01013412)
            pose=dict(POSE, banc='HyruleField_Adult', age=age)
            self.transport.fields.field=lambda kind,key:'HyruleField_Adult' if key=='1d6189da' else ''
            self.transport.fields.capture=lambda:dict(pose, age='Child') if self.memory.published else dict(POSE)
            with self.assertRaises(ValueError):self.transport.warp(pose)
            result=self.transport.warp(pose,allow_any_era=True)
            self.assertEqual(result['expected_age'],'Child')
            self.assertTrue(result['allow_any_era'])
            self.assertEqual(result['actual']['age'],'Child')
            self.assertEqual(self.memory.read(0x614,4),bytes.fromhex('12340101'))
            self.assertEqual(self.memory.read(0x714,4),bytes.fromhex('00000100'))
            self.memory=Memory();self.binding.client=self.memory;self.transport.client=self.memory
            self.transport.fields=Fields(self.memory)

    def test_override_still_checks_revision_entry_and_option_type(self):
        for pose,revision,allow in [(POSE,'other',True),(dict(POSE,entry='made-up'),None,True),(POSE,None,1)]:
            with self.assertRaises(ValueError):self.transport.warp(pose,revision,allow_any_era=allow)
        self.assertEqual(self.memory.calls,[])

    def test_age_and_manual_override_prepared_before_one_publication(self):
        self.age_setup()
        result = self.transport.warp(self.adult_pose, target_age='Adult')
        self.assertEqual(result['actual']['age'], 'Adult')
        self.assertEqual(self.memory.calls[-1][0], 0x514)
        # Saved/current age false; lower metadata bits preserved.
        self.assertEqual(self.memory.read(0x614, 4), bytes.fromhex('12340000'))
        self.assertEqual(self.memory.read(0x714, 4), bytes.fromhex('00000100'))
        self.assertEqual(result['origin']['age'], 'Child')

    def test_explicit_age_switch_can_reload_same_child_area_as_adult(self):
        self.age_setup()
        pose=dict(POSE,age='Adult')
        self.transport.fields.field=lambda kind,key:POSE['banc'] if key=='1d6189da' else ''
        self.transport.fields.capture=lambda:dict(pose if self.memory.published else POSE)
        with self.assertRaises(ValueError):self.transport.warp(pose,target_age='Adult')
        result=self.transport.warp(pose,target_age='Adult',allow_any_era=True)
        self.assertEqual(result['actual']['banc'],POSE['banc'])
        self.assertEqual(result['actual']['position'],POSE['position'])
        self.assertEqual(result['expected_age'],'Adult')
        self.assertEqual(self.memory.read(0x614,4),bytes.fromhex('12340000'))
        self.assertEqual(self.memory.read(0x714,4),bytes.fromhex('00000100'))

    def test_failed_manual_override_restores_age_and_destination_before_publish(self):
        self.age_setup()
        self.memory.fail_address = 0x714
        with self.assertRaises(ValueError):
            self.transport.warp(self.adult_pose, target_age='Adult')
        self.assertFalse(self.memory.published)
        self.assertEqual(self.memory.read(0x614, 4), bytes.fromhex('12340101'))
        self.assertEqual(self.memory.read(0x124, 12), bytes(12))

    def test_age_lost_publication_keeps_request_and_never_replays(self):
        self.age_setup()
        self.memory.lose_commit = True
        with self.assertRaises(TimeoutError):
            self.transport.warp(self.adult_pose, target_age='Adult')
        self.assertEqual(sum(a == 0x514 for a, _, _ in self.memory.calls), 1)
        self.assertEqual(self.memory.read(0x614, 4), bytes.fromhex('12340000'))
        self.assertEqual(self.audit()['state'], 'uncertain-after-request')

    def test_age_requires_explicit_matching_opposite_era(self):
        self.age_setup()
        for age in ('Unknown', 'Child'):
            with self.assertRaises(ValueError):
                self.transport.warp(self.adult_pose, target_age=age)
        with self.assertRaises(ValueError):
            self.transport.warp(self.adult_pose)
        self.assertEqual(self.memory.calls, [])


if __name__ == '__main__':
    unittest.main()
