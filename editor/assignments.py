"""Remake equipment reads and guarded selected-item CAS plans; no N64 offsets.

Requires connected live.Bindings. No method executes writes. Gear strings remain
read-only; selected-item plans use legal Enum hashes and enforce ownership.
"""
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class AssignmentBindings:
    def __init__(self, bindings):
        self.bindings = bindings
        self.client = bindings.client
        self.schema = json.loads((ROOT / 'research/assignments-schema.json').read_text(encoding='utf-8'))
        self.connected = False

    @staticmethod
    def u64(data, offset=0):
        return struct.unpack_from('<Q', data, offset)[0]

    def bind(self):
        self.bindings.validate()
        self.client.status()
        bounds = self.client.search(struct.pack('<I', 130), max_hits=1, budget_ms=1)
        self.heap = int(bounds['start'], 16), int(bounds['end'], 16)
        self.descriptors = {}
        for kind, spec in self.schema['types'].items():
            address = self.bindings.bool_desc['address'] + spec['descriptor_from_bool']
            header = self.client.read(address, 80)
            count = struct.unpack_from('<I', header, 8)[0]
            bank, lookup = self.u64(header, 16), self.u64(header, 24)
            capacity = struct.unpack_from('<I', header, 36)[0]
            if count != spec['count'] or not count <= capacity <= count * 4:
                raise ValueError('Assignment type descriptor differs from inspected revision')
            if not (self.heap[0] <= bank < bank + count * spec['stride'] <= self.heap[1] and
                    self.heap[0] <= lookup < lookup + capacity * 8 <= self.heap[1]):
                raise ValueError('Assignment type bank is outside the game heap')
            table = self.client.read(lookup, capacity * 8)
            vtable = self.u64(self.client.read(bank, 8))
            if vtable % 8 or not 0x10000 < vtable < self.heap[0]:
                raise ValueError('Invalid assignment object vtable')
            self.descriptors[kind] = dict(address=address, bank=bank, count=count,
                                          stride=spec['stride'], vtable=vtable)
            for field in self.schema['fields'].values():
                if field['type'] == kind and struct.pack('<II', int(field['hash'], 16), field['index']) not in table:
                    raise ValueError('Assignment runtime hash/index mismatch')
        bool_header = self.client.read(self.bindings.bool_desc['address'], 40)
        bool_lookup = self.u64(bool_header, 24)
        bool_capacity = struct.unpack_from('<I', bool_header, 36)[0]
        if not self.heap[0] <= bool_lookup < bool_lookup + bool_capacity * 8 <= self.heap[1]:
            raise ValueError('Assignment Bool lookup is outside the heap')
        bool_table = self.bindings.read_chunks(bool_lookup, bool_capacity * 8)
        for row in [self.schema['age_flag'], *self.schema['bottle_validity'].values()]:
            if self.bindings.indices['Bool'].get(row['hash']) != row['index'] or struct.pack('<II', int(row['hash'], 16), row['index']) not in bool_table:
                raise ValueError('Assignment Bool runtime hash/index mismatch')
        self.session_id = self.bindings.session_id
        self.connected = True
        return self.view()

    def validate(self):
        self.bindings.validate()
        if not self.connected or self.bindings.session_id != self.session_id:
            raise ValueError('Bind assignments to the current game session first')
        for desc in self.descriptors.values():
            data = self.client.read(desc['address'], 24)
            if self.u64(data, 16) != desc['bank'] or struct.unpack_from('<I', data, 8)[0] != desc['count']:
                self.connected = False
                raise ValueError('Assignment bank changed; reconnect')

    def _object(self, field):
        desc = self.descriptors[field['type']]
        address = desc['bank'] + field['index'] * desc['stride']
        data = self.client.read(address, desc['stride'])
        if self.u64(data) != desc['vtable']:
            raise ValueError('Stale assignment object')
        return address, data

    def _enum(self, field):
        _, data = self._object(field)
        count = struct.unpack_from('<I', data, 40)[0]
        pointer = self.u64(data, 48)
        if count != len(field['values']) or not self.heap[0] <= pointer < pointer + count * 4 <= self.heap[1]:
            raise ValueError('Invalid selected-item legal value table')
        values = struct.unpack('<' + 'I' * count, self.client.read(pointer, count * 4))
        if tuple(field['values'].values()) != values:
            raise ValueError('Selected-item legal values differ from inspected revision')
        current = struct.unpack_from('<I', data, 28)[0]
        if current not in values:
            raise ValueError('Unknown selected-item symbol')
        symbol = next(k for k, v in field['values'].items() if v == current)
        return dict(symbol=symbol, hash=f'{current:08x}',
                    actors=self.schema['symbol_actors'].get(symbol, []),
                    mapping_known=symbol == 'Empty' or symbol in self.schema['symbol_actors'])

    def _string(self, field):
        address, data = self._object(field)
        # Default/current/save-copy each use an 80-byte fixed string wrapper.
        # All three pointers must reference their own inline64 buffer.
        for offset in (24, 104, 184):
            if self.u64(data, offset) != address + offset + 12 or struct.unpack_from('<I', data, offset + 8)[0] != 64:
                raise ValueError('Equipment string layout differs from inspected revision')
            if b'\0' not in data[offset + 12:offset + 76]:
                raise ValueError('Unterminated equipment actor string')
        actor = data[116:180].split(b'\0', 1)[0].decode('ascii')
        if actor and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,62}', actor):
            raise ValueError('Equipment string is not an actor identifier')
        icon = ROOT / 'assets/icons' / (actor + '.png')
        return dict(actor=actor, known_actor=not actor or actor in self.schema['known_actors'],
                    icon=icon.relative_to(ROOT).as_posix() if actor and icon.exists() else None)

    def view(self):
        self.validate()
        result = {'equipped': {}, 'assignments': {}}
        for name, field in self.schema['fields'].items():
            if field['type'] == 'Enum':
                result['assignments'][name] = self._enum(field)
            else:
                result['equipped'][name] = self._string(field)
        # Only explicit actor identifiers qualify; empty/default strings do not
        # infer an equipped item from ownership or from N64 age conventions.
        result['equipped_actor_ids'] = [r['actor'] for r in result['equipped'].values() if r['actor']]
        _, age_data = self.bindings.object(self.schema['age_flag']['hash'], 'Bool')
        if age_data[22] not in (0, 1):
            raise ValueError('Invalid active age flag')
        result['active_age'] = 'Child' if age_data[22] else 'Adult'
        return result

    def write_plan(self, changes, require_owned=True):
        """Plan Enum-only changes, e.g. {'Child': 'Boomerang'}; no writes occur.

        None and 'Empty' both clear a selected item. Gear string keys are rejected.
        Both live and save-facing Enum words are updated in returned CAS records.
        """
        self.validate()
        if not isinstance(changes, dict) or set(changes) - {'Adult', 'Child'}:
            raise ValueError('Only Adult/Child selected-item Enums can be edited')
        owned = self.bindings.view()['items'] if require_owned else {}
        plan = []
        for age, symbol in changes.items():
            symbol = 'Empty' if symbol is None else symbol
            field = self.schema['fields'][age]
            if not isinstance(symbol, str) or symbol not in field['values']:
                raise ValueError('Unknown selected-item symbol')
            self._enum(field)  # validates the exact current legal value table
            if require_owned and symbol != 'Empty':
                if symbol in self.schema['bottle_validity']:
                    validity = self.schema['bottle_validity'][symbol]
                    _, data = self.bindings.object(validity['hash'], 'Bool')
                    if data[22] != 1 or not owned.get(symbol, False):
                        raise ValueError('Selected bottle must be owned and valid')
                else:
                    actors = self.schema['symbol_actors'].get(symbol, [])
                    if not actors or not any(owned.get(actor, False) for actor in actors):
                        raise ValueError('Selected item needs a mapped owned pouch actor')
            address, data = self._object(field)
            value = field['values'][symbol]
            for offset, suffix in ((28, ' live'), (32, ' save copy')):
                before = struct.unpack_from('<I', data, offset)[0]
                if before not in field['values'].values():
                    raise ValueError('Unknown existing selected-item Enum')
                if before != value:
                    plan.append(dict(address=address + offset, expected=before, value=value,
                                     field=age + ' selected item (' + symbol + ')' + suffix))
        return plan
