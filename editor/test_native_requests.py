"""In-memory fake transport tests. Never connects to an emulator."""
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_requests import NativeRequests, FIELDS, BOOL_VTABLE_RVA, validate_values


class FakeClient:
    def __init__(self, base=0x80e4f000):
        self.base = base
        self.mem = {}
        self.enabled = True
        self.responses = []
        self.calls = []
        self.queue_headers = []
        self.default_queue_header = 0
        self.header_reads = 0
        self.task = 0x2100040000
        self.hits = [hex(self.task)]
        self.put(0x2100004000, struct.pack('<Q', base + BOOL_VTABLE_RVA))
        self.put(0x21000002c0, struct.pack('<QIIQQIII', base + 0x4c1f280, 1259, 0,
                                        0x2100010000, 0x2100030000, 1259, 2518, 512))
        for n, (key, index, _) in enumerate(FIELDS.values()):
            self.put(0x2100030000 + n * 8, struct.pack('<II', key, index))
            self.put(0x2100010000 + index * 40, struct.pack('<Q', base + 0x4c20718))
        self.put(self.task, struct.pack('<Q', base + 0x4c64158))
        self.put(self.task + 0x18, struct.pack('<Q', base + 0x3dc1161))
        self.put(base + 0x3dc1161, b'GameData\0')
        self.put(self.task + 0xa0, struct.pack('<Q', 0x2100041000))
        self.put(0x2100041000, struct.pack('<Q', 0x2100041030))
        self.put(0x2100041030, b'GameData/GameDataList.Product.110.byml\0')

    def put(self, address, data):
        self.mem.update({address + n: value for n, value in enumerate(data)})

    def read(self, address, size):
        return bytes(self.mem.get(address + n, 0) for n in range(size))

    def status(self):
        return {'gamedata_int_enqueue_enabled': self.enabled}

    def search(self, pattern, **params):
        return dict(start='0x2100000000', end='0x2100080000', complete=True, hits=self.hits)

    def call(self, method, params, timeout=None):
        if method == 'read_memory':
            assert params == dict(address='0x21000002f8', size=4)
            assert 0 < timeout <= 0.5
            self.header_reads += 1
            header = self.queue_headers.pop(0) if self.queue_headers else self.default_queue_header
            return dict(hex=struct.pack('<I', header).hex())
        self.calls.append((method, params.copy()))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeBindings:
    def __init__(self, base=0x80e4f000):
        self.client = FakeClient(base)
        self.session_id = (123, 'fresh-process')
        self.actual_session = self.session_id
        self.bool_desc = dict(address=0x2100000200, bank=0x2100004000)
        self.int_desc = dict(address=0x21000002c0, bank=0x2100010000)

    def validate(self):
        if self.actual_session != self.session_id:
            raise ValueError('Session changed')

    def read_chunks(self, address, size):
        return self.client.read(address, size)


class NativeRequestTests(unittest.TestCase):
    def test_idle_hint_waits_for_empty_then_sends_once(self):
        self.bindings.client.queue_headers = [2, 0]
        self.bindings.client.responses = [dict(queued=True)]
        receipt = self.native.set_int('MP', 0, 24, busy_retries=3, wait_for_idle_ms=200)
        self.assertEqual(self.bindings.client.header_reads, 2)
        self.assertEqual(len(self.bindings.client.calls), 1)
        self.assertTrue(receipt['attempts'][0]['idle_hint']['ready'])

    def test_idle_hint_timeout_sends_no_native_request(self):
        self.bindings.client.default_queue_header = 2
        receipt = self.native.set_int('MP', 0, 24, busy_retries=3, wait_for_idle_ms=2)
        self.assertEqual(self.bindings.client.calls, [])
        self.assertEqual(receipt['state'], 'busy_no_changes')
        self.assertEqual(receipt['attempts'][0]['state'], 'not_sent_idle_hint')
        self.assertIn('no native request sent', receipt['attempts'][0]['response']['reason'])

    def test_idle_hint_does_not_resend_uncertain_request(self):
        self.bindings.client.responses = [TimeoutError('unknown enqueue outcome')]
        with self.assertRaisesRegex(RuntimeError, 'do not retry'):
            self.native.set_int('MP', 0, 24, busy_retries=3, wait_for_idle_ms=200)
        self.assertEqual(len(self.bindings.client.calls), 1)
        self.assertEqual(self.bindings.client.header_reads, 1)

    def test_idle_hint_rejects_out_of_range_budget(self):
        for budget in (-1, 501, True, 1.5):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                self.native.set_int('MP', 0, 24, wait_for_idle_ms=budget)
        self.assertEqual(self.bindings.client.calls, [])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.directory.cleanup)
        self.bindings = FakeBindings()
        self.native = NativeRequests(self.bindings, self.directory.name)
        self.native.bind()

    def test_bind_is_read_only_and_relocates(self):
        self.assertEqual(self.native.module_base, 0x80e4f000)
        self.assertEqual(self.bindings.client.calls, [])
        other = NativeRequests(FakeBindings(0x8016a000), self.directory.name)
        self.assertEqual(other.bind()['module_base'], 0x8016a000)

    def test_exact_rpc_and_no_retry_after_accept(self):
        self.bindings.client.responses = [dict(queued=True, busy=False, changed=True)]
        receipt = self.native.set_int('MP', 0, 24, busy_retries=3)
        self.assertEqual(len(self.bindings.client.calls), 1)
        method, params = self.bindings.client.calls[0]
        self.assertEqual(method, 'set_gamedata_int')
        self.assertEqual(params, dict(task='0x2100040000', int_descriptor='0x21000002c0',
                                     module_base='0x80e4f000', hash='0x76b18200', index=965,
                                     expected=0, value=24))
        self.assertFalse(receipt['actor_effect_verified'])
        self.assertEqual(json.loads(Path(receipt['audit_path']).read_text(encoding='utf-8'))['state'], 'queued_effect_unverified')

    def test_explicit_busy_only_can_retry(self):
        self.bindings.client.responses = [dict(queued=False, busy=True, changed=False), dict(queued=True)]
        receipt = self.native.set_int('Life', 0, 12, busy_retries=1)
        self.assertEqual(len(receipt['attempts']), 2)

    def test_busy_default_does_not_retry(self):
        self.bindings.client.responses = [dict(queued=False, busy=True, changed=False)]
        self.assertEqual(self.native.set_int('MP', 0, 24)['state'], 'busy_no_changes')
        self.assertEqual(len(self.bindings.client.calls), 1)

    def test_busy_with_unknown_change_never_retries(self):
        self.bindings.client.responses = [dict(queued=False, busy=True)]
        self.native.set_int('MP', 0, 24, busy_retries=3)
        self.assertEqual(len(self.bindings.client.calls), 1)

    def test_mismatch_no_retry(self):
        self.bindings.client.responses = [dict(queued=False, busy=False, changed=False, actual=5)]
        self.native.set_int('MP', 0, 24, busy_retries=3)
        self.assertEqual(len(self.bindings.client.calls), 1)

    def test_uncertain_timeout_is_audited_and_never_retries(self):
        self.bindings.client.responses = [TimeoutError('connection dropped')]
        with self.assertRaisesRegex(RuntimeError, 'do not retry'):
            self.native.set_int('MP', 0, 24, busy_retries=3)
        self.assertEqual(len(self.bindings.client.calls), 1)
        receipts = list(Path(self.directory.name).glob('*.json'))
        self.assertEqual(json.loads(receipts[0].read_text(encoding='utf-8'))['state'], 'uncertain_no_retry')

    def test_missing_capability_refuses(self):
        self.bindings.client.enabled = False
        with self.assertRaises(ValueError):
            self.native.set_int('MP', 0, 24)
        self.assertEqual(self.bindings.client.calls, [])

    def test_session_change_refuses(self):
        self.bindings.actual_session = (999, 'different')
        with self.assertRaises(ValueError):
            self.native.set_int('MP', 0, 24)
        self.assertEqual(self.bindings.client.calls, [])

    def test_bad_hash_table_refuses_bind(self):
        self.bindings.client.put(0x2100030000, struct.pack('<II', 0x31ab5580, 964))
        with self.assertRaises(ValueError):
            self.native.bind()

    def test_duplicate_task_refuses_bind(self):
        self.bindings.client.put(self.bindings.client.task + 0x200, self.bindings.client.read(self.bindings.client.task, 0xa8))
        self.bindings.client.hits.append(hex(self.bindings.client.task + 0x200))
        with self.assertRaises(ValueError):
            self.native.bind()

    def test_illegal_values_and_semantics_refused(self):
        for args in [('rupees', 0, 5), ('MP', 0, 49), ('MPMax', 0, 1), ('MaxLife', 12, 13),
                     ('Life', -1, 12), ('Life', 0, True), ('MP', 0, 1.0)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                validate_values(*args)

    def test_later_observation_does_not_resend(self):
        self.bindings.client.responses = [dict(queued=True)]
        receipt = self.native.set_int('MP', 0, 24)
        self.bindings.client.put(self.native.bank + 965 * 40 + 28, struct.pack('<I', 24))
        self.assertEqual(self.native.observe(receipt)['current'], 24)
        self.assertEqual(len(self.bindings.client.calls), 1)
        self.assertFalse(receipt['hud_effect_verified'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
