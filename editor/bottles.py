"""Guarded, side-effect-free bottle Enum binding and CAS write planning.

Requires an already connected live.Bindings. No controller input, implicit grants,
or memory mutation occurs here. Callers execute and audit returned CAS plans.
"""
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ICONS = {
    'Empty': 'Item_Bottle', 'RedPotion': 'Item_Bottle_RedPotion',
    'GreenPotion': 'Item_Bottle_GreenPotion', 'BluePotion': 'Item_Bottle_BluePotion',
    'BlueFire': 'Item_Bottle_BlueFire', 'Fish': 'Item_Bottle_Fish',
    'Letter': 'Item_Bottle_Letter', 'BigPoe': 'Item_Bottle_BigPoe',
    'Poe': 'Item_Bottle_Poe', 'Bug': 'Item_Bottle_Bug',
    'Fairy': 'Item_Bottle_Fairy', 'MaxMilk': 'Item_Bottle_Milk',
    'HalfMilk': 'Item_Bottle_HalfMilk',
}


class BottleBindings:
    def __init__(self, bindings):
        self.bindings = bindings
        self.client = bindings.client
        self.schema = json.loads((ROOT / 'research/bottle-schema.json').read_text(encoding='utf-8'))
        self.connected = False

    @staticmethod
    def u64(data, offset=0):
        return struct.unpack_from('<Q', data, offset)[0]

    def bind(self):
        self.bindings.validate()
        self.client.status()
        descriptor = self.bindings.bool_desc['address'] + self.schema['descriptor_from_bool']
        data = self.client.read(descriptor, 80)
        count = struct.unpack_from('<I', data, 8)[0]
        bank, lookup = self.u64(data, 16), self.u64(data, 24)
        capacity = struct.unpack_from('<I', data, 36)[0]
        if count != self.schema['enum_count'] or not count <= capacity <= count * 4:
            raise ValueError('Bottle Enum descriptor does not match this game revision')
        # Search reports the actual guest heap bounds; no address survives a launch.
        heap = self.client.search(struct.pack('<I', count), max_hits=1, budget_ms=1)
        lower, upper = int(heap['start'], 16), int(heap['end'], 16)
        if not (lower <= bank < bank + count * 56 <= upper and
                lower <= lookup < lookup + capacity * 8 <= upper):
            raise ValueError('Bottle Enum table is outside the game heap')
        table = self.client.read(lookup, capacity * 8)
        vtable = self.u64(self.client.read(bank, 8))
        if vtable % 8 or not 0x10000 < vtable < lower:
            raise ValueError('Invalid bottle Enum vtable')
        self.descriptor, self.bank, self.vtable = descriptor, bank, vtable
        self.heap = lower, upper
        self.session_id = self.bindings.session_id
        for row in self.schema['slots'].values():
            if struct.pack('<II', int(row['hash'], 16), row['index']) not in table:
                raise ValueError('Bottle Enum runtime hash/index mismatch')
            self._object(row)
        bool_header = self.client.read(self.bindings.bool_desc['address'], 40)
        bool_lookup = self.u64(bool_header, 24)
        bool_capacity = struct.unpack_from('<I', bool_header, 36)[0]
        if not lower <= bool_lookup < bool_lookup + bool_capacity * 8 <= upper:
            raise ValueError('Bottle validity lookup is outside the game heap')
        bool_table = self.bindings.read_chunks(bool_lookup, bool_capacity * 8)
        for row in self.schema['slots'].values():
            if struct.pack('<II', int(row['valid_hash'], 16), row['valid_index']) not in bool_table:
                raise ValueError('Bottle validity runtime hash/index mismatch')
        self.connected = True
        return self.view()

    def validate(self):
        self.bindings.validate()
        if not self.connected or self.bindings.session_id != self.session_id:
            raise ValueError('Bind bottles to the current game session first')
        header = self.client.read(self.descriptor, 24)
        if self.u64(header, 16) != self.bank or struct.unpack_from('<I', header, 8)[0] != self.schema['enum_count']:
            self.connected = False
            raise ValueError('Bottle Enum bank changed; reconnect')

    def _object(self, row):
        address = self.bank + row['index'] * 56
        data = self.client.read(address, 56)
        count = struct.unpack_from('<I', data, 40)[0]
        pointer = self.u64(data, 48)
        if self.u64(data) != self.vtable or count != len(row['values']):
            raise ValueError('Bottle Enum object or legal value count changed')
        if not self.heap[0] <= pointer < pointer + count * 4 <= self.heap[1]:
            raise ValueError('Bottle Enum legal values point outside the heap')
        actual_values = struct.unpack('<' + 'I' * count, self.client.read(pointer, count * 4))
        if tuple(row['values'].values()) != actual_values:
            raise ValueError('Bottle contents differ from the inspected game revision')
        current = struct.unpack_from('<I', data, 28)[0]
        if current not in actual_values:
            raise ValueError('Unknown current bottle content')
        return address, current

    def view(self):
        self.validate()
        result = {}
        for slot, row in sorted(self.schema['slots'].items()):
            _, current = self._object(row)
            symbol = next(name for name, value in row['values'].items() if value == current)
            stock = self.bindings.items[slot]['stock_hash']
            _, data = self.bindings.object(stock, 'Int')
            owned = struct.unpack_from('<i', data, 28)[0] > 0
            _, valid_data = self.bindings.object(row['valid_hash'], 'Bool')
            if valid_data[22] not in (0, 1):
                raise ValueError('Invalid bottle menu visibility flag')
            result[slot] = dict(content=symbol, hash=f'{current:08x}', owned=owned,
                                valid=bool(valid_data[22]),
                                icon='assets/icons/' + ICONS[symbol] + '.png')
        return result

    def write_plan(self, changes, require_owned=True, make_valid=False):
        """Return live and save-copy CAS records; caller owns execution/rollback.

        Example: {'BottleA': 'Fairy', 'BottleB': 'RedPotion'}.
        Empty means an owned empty bottle, not deletion of its StockNum.
        Set make_valid=True to enable the sibling menu flag in this same plan.
        By default validity is planned separately by validity_plan(count_changes).
        """
        self.validate()
        if not isinstance(changes, dict) or set(changes) - set(self.schema['slots']):
            raise ValueError('Unknown bottle slot')
        current_view = self.view()
        plan = []
        for slot, symbol in changes.items():
            row = self.schema['slots'][slot]
            if not isinstance(symbol, str) or symbol not in row['values']:
                raise ValueError('Unknown bottle content')
            if require_owned and not current_view[slot]['owned']:
                raise ValueError('Grant the bottle before changing its contents')
            address, expected = self._object(row)
            value = row['values'][symbol]
            save_copy = self.client.u32(address + 32)
            if save_copy not in row['values'].values():
                raise ValueError('Unknown saved bottle content')
            for offset, before, suffix in ((28, expected, ' live'), (32, save_copy, ' save copy')):
                if before != value:
                    plan.append(dict(address=address + offset, expected=before, value=value,
                                     field=slot + ' BottleItem (' + symbol + ')' + suffix))
            if make_valid:
                plan.extend(self.validity_plan({slot: True}))
        return plan

    def validity_plan(self, changes):
        """Plan live and save-copy IsValid bytes; preserve metadata bytes20/21."""
        self.validate()
        if (not isinstance(changes, dict) or set(changes) - set(self.schema['slots']) or
                any(type(value) is not bool for value in changes.values())):
            raise ValueError('Unknown bottle slot or invalid visibility value')
        plan = []
        for slot, valid in changes.items():
            row = self.schema['slots'][slot]
            address, data = self.bindings.object(row['valid_hash'], 'Bool')
            if data[22] not in (0, 1) or data[23] not in (0, 1):
                raise ValueError('Invalid bottle menu visibility flag')
            before = struct.unpack_from('<I', data, 20)[0]
            after = (before & 0xffff) | (int(valid) << 16) | (int(valid) << 24)
            if before != after:
                plan.append(dict(address=address + 20, expected=before, value=after,
                                 field=slot + ' IsValid'))
        return plan
