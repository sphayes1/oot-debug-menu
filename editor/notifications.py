"""Inspect typed GameData change queues and plan notification writes.

No method executes writes. Separate localhost CAS calls cannot safely append to
an actively consumed guest ring. Pause is insufficient: a stopped consumer can
retain old ring state in registers and overwrite a new publication on resume.
inspect() provides research snapshots only; plan() deliberately refuses writes
until a GameData-safe boundary has been proved and implemented in the backend.
"""
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LAYOUT = {'Bool': (0, 24), 'Int': (0xc0, 40), 'Float': (0x180, 40), 'Enum': (0x240, 56)}


class NotificationBindings:
    def __init__(self, bindings):
        self.bindings = bindings
        self.client = bindings.client
        rows = json.loads((ROOT / 'data/gamedata-schema.json').read_text(encoding='utf-8'))
        self.schema = {kind: [row for row in rows if row['type'] == kind] for kind in LAYOUT}

    @staticmethod
    def u64(data, offset=0):
        return struct.unpack_from('<Q', data, offset)[0]

    @staticmethod
    def u32(data, offset=0):
        return struct.unpack_from('<I', data, offset)[0]

    def inspect(self, kind, key):
        self.bindings.validate()
        status = self.client.status()
        if kind not in LAYOUT:
            raise ValueError('Unsupported notification type')
        if not isinstance(key, str) or len(key) != 8:
            raise ValueError('Expected an inspected GameData field hash')
        key = key.lower()
        rows = self.schema[kind]
        matches = [i for i, row in enumerate(rows) if row['hash'] == key]
        if len(matches) != 1:
            raise ValueError('Field is not in this typed game revision')
        index = matches[0]
        relative, stride = LAYOUT[kind]
        address = self.bindings.bool_desc['address'] + relative
        data = self.client.read(address, 96)
        count = self.u32(data, 8)
        bank, lookup = self.u64(data, 16), self.u64(data, 24)
        lookup_capacity = self.u32(data, 36)
        ring, capacity = self.u64(data, 64), self.u32(data, 72)
        head, size, mask = self.u32(data, 76), self.u32(data, 80), self.u32(data, 88)
        if count != len(rows) or not count <= lookup_capacity <= count * 4:
            raise ValueError('Notification type descriptor mismatch')
        bounds = self.client.search(struct.pack('<I', count), max_hits=1, budget_ms=1)
        low, high = int(bounds['start'], 16), int(bounds['end'], 16)
        if not (low <= bank < bank + count * stride <= high and
                low <= lookup < lookup + lookup_capacity * 8 <= high and
                capacity == count and low <= ring < ring + capacity * 4 <= high):
            raise ValueError('Notification pointers or queue capacity do not match inspected heap layout')
        if not 0 <= head < capacity or not 0 <= size < capacity:
            raise ValueError('Notification queue is full or malformed')
        table = self.bindings.read_chunks(lookup, lookup_capacity * 8)
        if struct.pack('<II', int(key, 16), index) not in table:
            raise ValueError('Notification hash/index mismatch')
        vtable = self.u64(self.client.read(bank, 8))
        obj_address = bank + index * stride
        obj = self.client.read(obj_address, stride)
        if self.u64(obj) != vtable or vtable % 8 or not 0x10000 < vtable < low:
            raise ValueError('Notification object vtable mismatch')
        flags = self.u32(obj, 8)
        slot = ring + ((head + size) % capacity) * 4
        slot_before = self.client.u32(slot)
        writes = []

        def append(at, before, after, label):
            if before != after:
                writes.append(dict(address=at, expected=before, value=after, field=label))

        # 819f1c30..90: value live/save, save-pending byte20=0, changedbyte12=1,
        # ring hash append, size increment, object flags OR into manager mask.
        # Research ordering only. Full pause does not establish a safe boundary.
        changed_word = self.u32(obj, 12)
        pending_word = self.u32(obj, 20)
        append(obj_address + 20, pending_word, pending_word & 0xffffff00, 'clear save-pending byte20')
        append(obj_address + 12, changed_word, (changed_word & 0xffffff00) | 1, 'set changed byte12')
        append(slot, slot_before, int(key, 16), 'notification field hash payload')
        append(address + 88, mask, mask | flags, 'notification category mask')
        append(address + 80, size, size + 1, 'publish notification ring size')
        return dict(kind=kind, hash=key, index=index, descriptor=address, object=obj_address,
                    session=self.bindings.session_id, object_vtable=vtable,
                    ring=dict(pointer=ring, capacity=capacity, head=head, size=size, slot=slot),
                    object_flags=flags, category_mask=mask, writes=writes,
                    preconditions=[dict(address=address + 76, expected=head, field='ring head'),
                                   dict(address=address + 80, expected=size, field='ring size'),
                                   dict(address=address + 72, expected=capacity, field='ring capacity')],
                    requires_full_emulator_pause=True, safe_to_apply=False,
                    emulator_paused=bool(status.get('paused')),
                    boundary_proven=False,
                    warning='Research snapshot only. Pause alone is insufficient; a suspended consumer may retain stale queue state. Do not execute these output-ring writes.',
                    game_callback_effect_verified=False)

    def plan(self, kind, key):
        result = self.inspect(kind, key)
        if not result['safe_to_apply']:
            raise ValueError('Notification writes disabled: a GameData-safe consumer boundary has not been proved; Pause alone is insufficient')
        return result
