"""Guarded sidefield plans for remake scales, strength, magic and defense.

Plans are side-effect-free. Callers also update tier pouch counts and execute
the combined audited CAS transaction; no gear strings or health fields change.
"""
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / 'research/enhancements-schema.json').read_text(encoding='utf-8'))


def upgrade_changes(slot_key, selected_actor):
    if slot_key not in SCHEMA['tiers']:
        raise ValueError('Unknown enhancement tier')
    tier = SCHEMA['tiers'][slot_key]
    if selected_actor is None:
        return {'enhancements': dict(tier['none'])}
    if selected_actor not in tier['choices']:
        raise ValueError('Actor is not valid for this enhancement tier')
    return {'enhancements': dict(tier['choices'][selected_actor])}


class EnhancementBindings:
    def __init__(self, bindings):
        self.bindings = bindings
        self.client = bindings.client
        self.connected = False

    @staticmethod
    def u64(data, offset=0):
        return struct.unpack_from('<Q', data, offset)[0]

    def bind(self):
        self.bindings.validate()
        self.client.status()
        bounds = self.client.search(struct.pack('<I', 89), max_hits=1, budget_ms=1)
        self.heap = int(bounds['start'], 16), int(bounds['end'], 16)
        self.descriptors = {}
        for kind, spec in SCHEMA['types'].items():
            address = self.bindings.bool_desc['address'] + spec['descriptor_from_bool']
            data = self.client.read(address, 40)
            count = struct.unpack_from('<I', data, 8)[0]
            bank, lookup = self.u64(data, 16), self.u64(data, 24)
            capacity = struct.unpack_from('<I', data, 36)[0]
            if count != spec['count'] or not count <= capacity <= count * 4:
                raise ValueError('Enhancement type descriptor mismatch')
            if not (self.heap[0] <= bank < bank + count * spec['stride'] <= self.heap[1] and
                    self.heap[0] <= lookup < lookup + capacity * 8 <= self.heap[1]):
                raise ValueError('Enhancement bank is outside game heap')
            table = self.bindings.read_chunks(lookup, capacity * 8)
            vtable = self.u64(self.client.read(bank, 8))
            if vtable % 8 or not 0x10000 < vtable < self.heap[0]:
                raise ValueError('Invalid enhancement type vtable')
            self.descriptors[kind] = dict(address=address, bank=bank, count=count,
                                          stride=spec['stride'], vtable=vtable)
            for field in SCHEMA['fields'].values():
                if field['type'] == kind and struct.pack('<II', int(field['hash'], 16), field['index']) not in table:
                    raise ValueError('Enhancement runtime hash/index mismatch')
        self.session_id = self.bindings.session_id
        self.connected = True
        return self.view()

    def validate(self):
        self.bindings.validate()
        if not self.connected or self.session_id != self.bindings.session_id:
            raise ValueError('Bind enhancements to this game session first')
        for desc in self.descriptors.values():
            data = self.client.read(desc['address'], 24)
            if self.u64(data, 16) != desc['bank'] or struct.unpack_from('<I', data, 8)[0] != desc['count']:
                self.connected = False
                raise ValueError('Enhancement bank changed; reconnect')

    def _object(self, field):
        desc = self.descriptors[field['type']]
        address = desc['bank'] + field['index'] * desc['stride']
        data = self.client.read(address, desc['stride'])
        if self.u64(data) != desc['vtable']:
            raise ValueError('Stale enhancement object')
        if field['type'] == 'Enum':
            count = struct.unpack_from('<I', data, 40)[0]
            pointer = self.u64(data, 48)
            if count != len(field['values']) or not self.heap[0] <= pointer < pointer + count * 4 <= self.heap[1]:
                raise ValueError('Invalid strength Enum value table')
            values = struct.unpack('<' + 'I' * count, self.client.read(pointer, count * 4))
            if values != tuple(field['values'].values()):
                raise ValueError('Strength Enum values differ from inspected revision')
        return address, data

    @staticmethod
    def _decode(field, data, offset):
        kind = field['type']
        if kind == 'Bool':
            value = data[offset]
            if value not in (0, 1):
                raise ValueError('Invalid defense Boolean')
            return bool(value)
        value = struct.unpack_from('<f' if kind == 'Float' else '<I', data, offset)[0]
        if kind == 'Enum':
            if value not in field['values'].values():
                raise ValueError('Unknown strength Enum value')
            return next(k for k, v in field['values'].items() if v == value)
        if 'legal_values' in field and value not in field['legal_values']:
            raise ValueError('Unknown enhancement tier value')
        if field['name'].endswith('.MP') and not 0 <= value <= 48:
            raise ValueError('Invalid magic counter')
        return value

    def view(self):
        self.validate()
        values = {}
        for name, field in SCHEMA['fields'].items():
            _, data = self._object(field)
            values[name] = self._decode(field, data, 22 if field['type'] == 'Bool' else 28)
        return values

    def write_plan(self, changes):
        self.validate()
        if not isinstance(changes, dict) or set(changes) - set(SCHEMA['fields']):
            raise ValueError('Unknown enhancement field')
        current = self.view()
        proposed = current | changes
        if (type(proposed['MPMax']) is not int or proposed['MPMax'] not in (0, 24, 48) or
                type(proposed['MP']) is not int or not 0 <= proposed['MP'] <= proposed['MPMax']):
            raise ValueError('Magic must fit its selected maximum')
        plan = []
        # Lower magic before reducing its maximum; raise maximum before refill.
        ordered = sorted(changes, key=lambda n: (0 if n == ('MP' if proposed['MPMax'] < current['MPMax'] else 'MPMax') else 1))
        for name in ordered:
            value, field = changes[name], SCHEMA['fields'][name]
            kind = field['type']
            address, data = self._object(field)
            if kind == 'Bool':
                if type(value) is not bool:
                    raise ValueError('Defense requires a Boolean')
                self._decode(field, data, 22)
                self._decode(field, data, 23)
                before = struct.unpack_from('<I', data, 20)[0]
                after = (before & 0xffff) | (int(value) << 16) | (int(value) << 24)
                if before != after:
                    plan.append(dict(address=address + 20, expected=before, value=after, field=name))
                continue
            if kind == 'Enum':
                if not isinstance(value, str) or value not in field['values']:
                    raise ValueError('Unknown strength tier')
                encoded = field['values'][value]
            elif kind == 'Float':
                if type(value) not in (int, float) or value not in field['legal_values']:
                    raise ValueError('Unknown scale dive depth')
                encoded = struct.unpack('<I', struct.pack('<f', value))[0]
            else:
                if type(value) is not int or not 0 <= value <= 48 or ('legal_values' in field and value not in field['legal_values']):
                    raise ValueError('Invalid magic tier or counter')
                encoded = value
            for offset, suffix in ((28, ' live'), (32, ' save copy')):
                self._decode(field, data, offset)
                before = struct.unpack_from('<I', data, offset)[0]
                if before != encoded:
                    plan.append(dict(address=address + offset, expected=before, value=encoded, field=name + suffix))
        return plan
