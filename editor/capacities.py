"""Guarded ammo/wallet capacity reads and CAS plans from remake metadata.

No method mutates memory. The live editor owns execution, rollback and receipts.
"""
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / 'research/capacity-schema.json').read_text(encoding='utf-8'))


def upgrade_changes(slot_key, selected_actor):
    """Pure tier selection -> capacity changes; merge with pouch count changes."""
    if slot_key not in SCHEMA['upgrades']:
        raise ValueError('No validated ammo capacity for this upgrade')
    group = SCHEMA['upgrades'][slot_key]
    if selected_actor is not None and selected_actor not in group['choices']:
        raise ValueError('Item is not a tier in this capacity picker')
    value = group['none_capacity'] if selected_actor is None else group['choices'][selected_actor]
    return {'capacities': {group['semantic']: value}}


def capacities_from_counts(counts):
    """Pure full pouch snapshot -> highest owned tier capacities (for Give All)."""
    values = {}
    for group in SCHEMA['upgrades'].values():
        owned = [capacity for actor, capacity in group['choices'].items() if counts.get(actor, 0) > 0]
        values[group['semantic']] = max(owned, default=group['none_capacity'])
    return {'capacities': values}


class CapacityBindings:
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
        desc = self.bindings.int_desc
        header = self.client.read(desc['address'], 40)
        count = struct.unpack_from('<I', header, 8)[0]
        capacity = struct.unpack_from('<I', header, 36)[0]
        lookup = self.u64(header, 24)
        if count != len(self.bindings.schema['Int']) or not count <= capacity <= count * 4:
            raise ValueError('Capacity Int descriptor differs from the inspected revision')
        bounds = self.client.search(struct.pack('<I', count), max_hits=1, budget_ms=1)
        heap = int(bounds['start'], 16), int(bounds['end'], 16)
        if not heap[0] <= lookup < lookup + capacity * 8 <= heap[1]:
            raise ValueError('Capacity lookup is outside the game heap')
        table = self.bindings.read_chunks(lookup, capacity * 8)
        for row in SCHEMA['fields'].values():
            if self.bindings.indices['Int'].get(row['hash']) != row['index']:
                raise ValueError('Capacity schema index mismatch')
            if struct.pack('<II', int(row['hash'], 16), row['index']) not in table:
                raise ValueError('Capacity runtime hash/index mismatch')
            self.bindings.object(row['hash'], 'Int')  # verifies object vtable
        self.session_id = self.bindings.session_id
        self.connected = True
        return self.view()

    def validate(self):
        self.bindings.validate()
        if not self.connected or self.bindings.session_id != self.session_id:
            raise ValueError('Bind capacities to the current game session first')

    def view(self):
        self.validate()
        result = {}
        for name, row in SCHEMA['fields'].items():
            _, data = self.bindings.object(row['hash'], 'Int')
            value = struct.unpack_from('<i', data, 28)[0]
            if value not in row['legal_values']:
                raise ValueError('Unknown capacity value for ' + name)
            result[name] = value
        return result

    def write_plan(self, changes):
        """Plan semantic capacities, e.g. {'Arrow': 40, 'Rupee': 500}."""
        self.validate()
        if not isinstance(changes, dict) or set(changes) - set(SCHEMA['fields']):
            raise ValueError('Unknown capacity field')
        plan = []
        for name, value in changes.items():
            row = SCHEMA['fields'][name]
            if type(value) is not int or value not in row['legal_values']:
                raise ValueError('Capacity is not a tier in the inspected remake metadata')
            address, data = self.bindings.object(row['hash'], 'Int')
            for offset, suffix in ((28, ' live'), (32, ' save copy')):
                before = struct.unpack_from('<i', data, offset)[0]
                if before not in row['legal_values']:
                    raise ValueError('Unknown existing capacity value for ' + name)
                if before != value:
                    plan.append(dict(address=address + offset, expected=before, value=value,
                                     field=name + ' MaxNum' + suffix))
        return plan
