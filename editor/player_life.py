"""Bind the active Player Life component; current-health writes use one guarded CAS.

Addresses are discovered per session. No GameData notifications, retries, automatic
rollback, maximum-health writes or magic writes are performed here.
"""
import json
import struct
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BOOL_VTABLE_RVA = 0x4c20658
LIFE_VTABLE_RVA = 0x4b4c460
VALUE_VTABLE_RVA = 0x4b63438


class PlayerLifeBindings:
    def __init__(self, bindings, audit_dir=None):
        self.bindings = bindings
        self.client = bindings.client
        self.audit_dir = Path(audit_dir) if audit_dir else ROOT/'runtime/player-life-audits'
        self.connected = False

    @staticmethod
    def u64(data, offset=0):
        return struct.unpack_from('<Q', data, offset)[0]

    def in_heap(self, address, size):
        return address % 4 == 0 and self.heap[0] <= address < address + size <= self.heap[1]

    def _capability(self):
        self.bindings.validate()
        if self.client.status().get('live_inventory_enabled') is not True:
            raise ValueError('Player health editing requires the opt-in inventory transport')

    def _candidate(self, component):
        if component % 8 or not self.in_heap(component, 0x1d20):
            return None
        header = self.client.read(component, 0x20)
        if self.u64(header) != self.module_base + LIFE_VTABLE_RVA:
            return None
        owner = self.u64(header, 0x18)
        if not self.in_heap(owner, 0x278):
            return None
        owner_data = self.client.read(owner, 0x278)
        name, context = self.u64(owner_data, 0x20), self.u64(owner_data, 0x270)
        if not self.in_heap(name, 7) or self.client.read(name, 7) != b'Player\0':
            return None
        if (context % 8 or not self.in_heap(context, 0x2c0) or
                self.u64(self.client.read(context + 0x2b8, 8)) != component):
            return None
        pointers = self.client.read(component + 0x1c10, 16)
        current, maximum = self.u64(pointers), self.u64(pointers, 8)
        if current == maximum:
            return None
        values = []
        for pointer, field_hash in ((current, 0x31ab5580), (maximum, 0xfbe01da1)):
            if pointer % 8 or not self.in_heap(pointer, 16):
                return None
            data = self.client.read(pointer, 16)
            if (self.u64(data) != self.module_base + VALUE_VTABLE_RVA or
                    struct.unpack_from('<I', data, 12)[0] != field_hash):
                return None
            values.append(struct.unpack_from('<I', data, 8)[0])
        if not 0 <= values[0] <= values[1] <= 80 or values[1] < 12 or values[1] % 4:
            return None
        return dict(component=component, owner=owner, context=context,
                    current_pointer=current, max_pointer=maximum,
                    current=values[0], maximum=values[1])

    def bind(self):
        self.connected = False
        self._capability()
        self.session_id = tuple(self.bindings.session_id)
        self.module_base = self.u64(self.client.read(self.bindings.bool_desc['bank'], 8)) - BOOL_VTABLE_RVA
        if self.module_base < 0x10000 or self.module_base % 4096:
            raise ValueError('Player Life module relocation is invalid')
        cursor = None
        candidates = {}
        for _ in range(256):
            params = dict(max_hits=64, budget_ms=250)
            if cursor:
                params['start'] = cursor
            result = self.client.search(struct.pack('<Q', self.module_base + LIFE_VTABLE_RVA), **params)
            if cursor is None:
                self.heap = int(result['start'], 16), int(result['end'], 16)
            for hit in result['hits']:
                component = int(hit, 16)
                try:
                    candidate = self._candidate(component)
                except ValueError:
                    candidate = None
                if candidate:
                    candidates[component] = candidate
            if result['complete']:
                break
            next_cursor = result.get('next')
            if not next_cursor or next_cursor == cursor:
                raise ValueError('Player Life search did not advance')
            cursor = next_cursor
        else:
            raise ValueError('Player Life search budget exhausted')
        if len(candidates) != 1:
            raise ValueError('Expected one uniquely validated active Player Life component')
        self.bound = next(iter(candidates.values()))
        self.connected = True
        return self.read()

    def _guard(self, capability=False):
        if capability:
            self._capability()
        else:
            self.bindings.validate()
        if not self.connected or tuple(self.bindings.session_id) != self.session_id:
            raise ValueError('Player Life session changed; connect again')
        if self.u64(self.client.read(self.bindings.bool_desc['bank'], 8)) != self.module_base + BOOL_VTABLE_RVA:
            raise ValueError('Player Life module changed; connect again')
        candidate = self._candidate(self.bound['component'])
        keys = ('component', 'owner', 'context', 'current_pointer', 'max_pointer')
        if candidate is None or any(candidate[key] != self.bound[key] for key in keys):
            raise ValueError('Active Player Life owner or typed fields changed; connect again')
        return candidate

    def read(self):
        data = self._guard()
        return dict(current=data['current'], maximum=data['maximum'],
                    hearts=data['current']/4, max_hearts=data['maximum']/4,
                    session=self.session_id, current_edit_supported=True,
                    max_edit_supported=False, magic_edit_supported=False)

    def _save(self, path, receipt):
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(receipt, indent=2)+'\n')
        temporary.replace(path)

    def write_current(self, expected, value):
        if any(type(number) is not int or not 0 <= number <= 80 for number in (expected, value)):
            raise ValueError('Current health must be integer quarter-hearts in 0..80')
        before = self._guard(capability=True)
        if value > before['maximum']:
            raise ValueError('Current health cannot exceed maximum health')
        path = self.audit_dir/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-')+uuid.uuid4().hex+'.json')
        receipt = dict(session=self.session_id, field='Life', transport='active_player_single_cas',
            address=before['current_pointer']+8, expected=expected, value=value, before=before,
            state='prepared', audit_path=str(path), automatic_retry=False, automatic_rollback=False,
            hud_effect_verified=False, save_file_effect_verified=False)
        self._save(path, receipt)
        receipt['state'] = 'cas_in_flight'
        self._save(path, receipt)
        try:
            final = self._guard()
            if value > final['maximum']:
                raise ValueError('Maximum health changed before the edit')
        except Exception as error:
            receipt.update(state='refused_before_cas', error=str(error))
            self._save(path, receipt)
            raise
        try:
            result = self.client.compare_write(final['current_pointer']+8, expected, value)
        except Exception as error:
            receipt.update(state='uncertain_no_retry', error=str(error))
            self._save(path, receipt)
            raise RuntimeError(f'Health edit outcome uncertain; do not retry. Audit: {path}') from error
        receipt['response'] = result
        if not isinstance(result, dict) or type(result.get('swapped')) is not bool:
            receipt['state'] = 'uncertain_no_retry'
            self._save(path, receipt)
            raise RuntimeError(f'Health edit response unrecognized; do not retry. Audit: {path}')
        if result.get('swapped') is True:
            receipt['state'] = 'applied' if result.get('actual') == value and result.get('readback_matches') is True else 'applied_concurrent_change'
        else:
            receipt['state'] = 'expected_mismatch_no_change'
        try:
            receipt['after'] = self.read()
        except Exception as error:
            receipt['observation_error'] = str(error)
        self._save(path, receipt)
        return receipt
