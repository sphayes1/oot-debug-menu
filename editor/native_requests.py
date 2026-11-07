"""Guarded native GameData requests; never retries an accepted or uncertain request.

Importing or binding is read-only. Only set_int() invokes the explicit enqueue RPC.
RAM observations do not establish player-component, HUD, or save-file behavior.
"""
import json
import struct
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BOOL_VTABLE_RVA = 0x4c20658
FIELDS = {'Life': (0x31ab5580, 963, 80), 'MaxLife': (0xfbe01da1, 964, 80),
          'MP': (0x76b18200, 965, 48), 'MPMax': (0x12d63a97, 967, 48)}


def validate_values(field, expected, value):
    if field not in FIELDS:
        raise ValueError('Only Life, MaxLife, MP and MPMax have reviewed native requests')
    limit = FIELDS[field][2]
    if any(type(v) is not int or not 0 <= v <= limit for v in (expected, value)):
        raise ValueError('Expected/value is outside the reviewed integer range')
    if field == 'MaxLife' and (value < 12 or value % 4):
        raise ValueError('MaxLife must be whole hearts in [12,80]')
    if field == 'MPMax' and value not in (0, 24, 48):
        raise ValueError('MPMax must be 0,24,48')


class NativeRequests:
    def __init__(self, bindings, audit_dir=None):
        self.bindings = bindings
        self.client = bindings.client
        self.audit_dir = Path(audit_dir) if audit_dir else ROOT / 'runtime/native-request-audits'
        self.connected = False

    @staticmethod
    def u64(data, offset=0):
        return struct.unpack_from('<Q', data, offset)[0]

    def _status(self):
        self.bindings.validate()
        status = self.client.status()
        if status.get('gamedata_int_enqueue_enabled') is not True:
            raise ValueError('This game build does not enable reviewed native GameData requests')
        return status

    def _heap_range(self, address, size):
        return self.heap[0] <= address and address + size <= self.heap[1]

    def _task_identity(self, task):
        if task % 8 or not self._heap_range(task, 0xa8):
            return False
        data = self.client.read(task, 0xa8)
        if self.u64(data) != self.module_base + 0x4c64158:
            return False
        name = self.u64(data, 0x18)
        resource = self.u64(data, 0xa0)
        if not self._heap_range(resource, 88):
            return False
        resource_data = self.client.read(resource, 48)
        return (self.client.read(name, 9) == b'GameData\0' and
                self.u64(resource_data) == resource + 48 and
                self.client.read(resource + 48, 39) == b'GameData/GameDataList.Product.110.byml\0')

    def bind(self):
        self.connected = False
        self._status()
        self.session_id = tuple(self.bindings.session_id)
        bool_vtable = self.u64(self.client.read(self.bindings.bool_desc['bank'], 8))
        self.module_base = bool_vtable - BOOL_VTABLE_RVA
        if self.module_base < 0x10000 or self.module_base % 4096:
            raise ValueError('Fresh Bool vtable does not resolve the inspected main module')
        self.descriptor = self.bindings.int_desc['address']
        header = self.client.read(self.descriptor, 96)
        self.bank, lookup = self.u64(header, 16), self.u64(header, 24)
        if (self.u64(header) != self.module_base + 0x4c1f280 or
                struct.unpack_from('<I', header, 8)[0] != 1259 or
                struct.unpack_from('<II', header, 32) != (1259, 2518) or
                self.bank != self.bindings.int_desc['bank']):
            raise ValueError('Native request Int descriptor revision mismatch')
        cursor = None
        candidates = set()
        pattern = struct.pack('<Q', self.module_base + 0x4c64158)
        for _ in range(128):
            parameters = dict(max_hits=64, budget_ms=250)
            if cursor:
                parameters['start'] = cursor
            result = self.client.search(pattern, **parameters)
            if cursor is None:
                self.heap = int(result['start'], 16), int(result['end'], 16)
            for hit in result['hits']:
                address = int(hit, 16)
                try:
                    if self._task_identity(address):candidates.add(address)
                except (ValueError,struct.error):
                    continue  # A vtable word alone does not identify a task object.
            if result['complete']:
                break
            next_cursor = result.get('next')
            if not next_cursor or next_cursor == cursor:
                raise ValueError('Native task search failed to advance')
            cursor = next_cursor
        else:
            raise ValueError('Native task search budget exhausted; no request sent')
        if len(candidates) != 1:
            raise ValueError('Expected one uniquely identified GameData task')
        self.task = candidates.pop()
        if not self._heap_range(self.bank, 1259 * 40) or not self._heap_range(lookup, 2518 * 8):
            raise ValueError('Native Int table is outside the application heap')
        table = self.bindings.read_chunks(lookup, 2518 * 8)
        rows = list(struct.iter_unpack('<II', table))
        for field_hash, index, _ in FIELDS.values():
            if [row for row in rows if row[0] == field_hash] != [(field_hash, index)]:
                raise ValueError('Native request hash/index table mismatch')
        self.connected = True
        self._guard()
        return dict(session=self.session_id, module_base=self.module_base,
                    task=self.task, int_descriptor=self.descriptor, read_only_binding=True)

    def _guard(self):
        self._status()
        if not self.connected or tuple(self.bindings.session_id) != self.session_id:
            raise ValueError('Native request session changed; bind again')
        if (self.bindings.int_desc['address'] != self.descriptor or
                self.bindings.int_desc['bank'] != self.bank or
                self.u64(self.client.read(self.descriptor + 16, 8)) != self.bank):
            raise ValueError('Native request Int bank changed; bind again')
        if (self.u64(self.client.read(self.bindings.bool_desc['bank'], 8)) !=
                self.module_base + BOOL_VTABLE_RVA or not self._task_identity(self.task)):
            raise ValueError('Native request binding changed; bind again')

    def read(self, field):
        self._guard()
        if field not in FIELDS:
            raise ValueError('Unknown reviewed native field')
        _, index, _ = FIELDS[field]
        data = self.client.read(self.bank + index * 40, 40)
        if self.u64(data) != self.module_base + 0x4c20718:
            raise ValueError('Native request Int object vtable mismatch')
        return dict(current=struct.unpack_from('<I', data, 28)[0],
                    saved_copy=struct.unpack_from('<I', data, 32)[0],
                    observation='GameData RAM only; actor/HUD/save-file effect unverified')

    def _save(self, path, receipt):
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(receipt, indent=2) + '\n')
        temporary.replace(path)

    def _idle_hint(self, milliseconds):
        deadline = time.monotonic() + milliseconds / 1000
        polls = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return dict(ready=False, polls=polls, reason='idle hint deadline expired; no native request sent')
            try:
                result = self.client.call('read_memory',
                    dict(address=hex(self.descriptor + 56), size=4), timeout=remaining)
                data = bytes.fromhex(result['hex'])
                header = struct.unpack('<I', data)[0]
            except Exception as error:
                return dict(ready=False, polls=polls, reason='idle hint read failed; no native request sent', error=str(error))
            polls += 1
            if header & 0xfffff == 0:
                return dict(ready=True, polls=polls, header=header,
                            observation='Timing hint only; endpoint independently rechecks the boundary')
            time.sleep(min(0.0015, max(0, deadline - time.monotonic())))

    def set_int(self, field, expected, value, *, busy_retries=0, wait_for_idle_ms=0):
        validate_values(field, expected, value)
        if type(busy_retries) is not int or not 0 <= busy_retries <= 3:
            raise ValueError('busy_retries must be 0..3; accepted/uncertain requests never retry')
        if type(wait_for_idle_ms) is not int or not 0 <= wait_for_idle_ms <= 500:
            raise ValueError('wait_for_idle_ms must be an integer in 0..500')
        self._guard()
        field_hash, index, _ = FIELDS[field]
        params = dict(task=hex(self.task), int_descriptor=hex(self.descriptor),
                      module_base=hex(self.module_base), hash=hex(field_hash), index=index,
                      expected=expected, value=value)
        path = self.audit_dir / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-') + uuid.uuid4().hex + '.json')
        receipt = dict(session=self.session_id, field=field, params=params, attempts=[],
                       before=self.read(field), state='prepared', audit_path=str(path),
                       wait_for_idle_ms=wait_for_idle_ms,
                       actor_effect_verified=False, hud_effect_verified=False, save_file_effect_verified=False)
        self._save(path, receipt)
        for attempt in range(busy_retries + 1):
            self._guard()
            receipt['state'] = 'request_in_flight'
            receipt['attempts'].append(dict(number=attempt + 1, state='in_flight'))
            self._save(path, receipt)
            if wait_for_idle_ms:
                hint = self._idle_hint(wait_for_idle_ms)
                receipt['attempts'][-1]['idle_hint'] = hint
                if not hint['ready']:
                    receipt['state'] = 'busy_no_changes'
                    receipt['attempts'][-1].update(state='not_sent_idle_hint',
                        response=dict(queued=False, busy=True, changed=False, reason=hint['reason']))
                    break
            try:
                result = self.client.call('set_gamedata_int', params)
            except Exception as error:
                receipt['state'] = 'uncertain_no_retry'
                receipt['attempts'][-1].update(state='uncertain', error=str(error))
                self._save(path, receipt)
                raise RuntimeError(f'Native request outcome uncertain; do not retry. Audit: {path}') from error
            receipt['attempts'][-1].update(state='response_received', response=result)
            if not isinstance(result, dict):
                receipt['state'] = 'unrecognized_no_retry'
                break
            if result.get('queued') is True:
                receipt['state'] = 'queued_effect_unverified'
                break
            if (result.get('queued') is False and result.get('busy') is True and
                    result.get('changed') is False):
                receipt['state'] = 'busy_no_changes'
                self._save(path, receipt)
                if attempt < busy_retries:
                    time.sleep(0.02)
                    continue
                break
            receipt['state'] = 'refused_or_unrecognized_no_retry'
            break
        try:
            receipt['after'] = self.read(field)
        except Exception as error:
            receipt['observation_error'] = str(error)
        self._save(path, receipt)
        return receipt

    def observe(self, receipt):
        """Record another readback without sending or retrying a native request."""
        if tuple(receipt['session']) != tuple(self.bindings.session_id):
            raise ValueError('Cannot observe a different game session')
        observation = self.read(receipt['field'])
        receipt.setdefault('later_observations', []).append(observation)
        self._save(Path(receipt['audit_path']), receipt)
        return observation
