"""Read-only live location capture; positions and Euler rotations use game units."""
import json
import math
import struct
from pathlib import Path
from locations import presets, validate_pose

ROOT = Path(__file__).resolve().parent


class LocationCapture:
    def __init__(self, binding):
        self.binding = binding
        self.client = binding.client
        schema = json.loads((ROOT / 'data/gamedata-schema.json').read_text(encoding='utf-8'))
        self.rows = {kind: [r for r in schema if r['type'] == kind]
                     for kind in ('Vector3', 'Float', 'String64')}

    def object(self, kind, field_hash):
        self.binding.validate()
        spec = {'Vector3': (0x3c0, 64), 'Float': (0x180, 40), 'String64': (0x600, 264)}
        offset, stride = spec[kind]
        heap = self.binding.assignments.heap
        header = self.client.read(self.binding.bool_desc['address'] + offset, 48)
        count = struct.unpack_from('<I', header, 8)[0]
        bank, lookup = struct.unpack_from('<QQ', header, 16)
        capacity = struct.unpack_from('<I', header, 36)[0]
        if count != len(self.rows[kind]) or not count <= capacity <= count * 4:
            raise ValueError('Location type descriptor changed; reconnect')
        if not (heap[0] <= bank < bank + count * stride <= heap[1] and
                heap[0] <= lookup < lookup + capacity * 8 <= heap[1]):
            raise ValueError('Location bank is outside the mapped heap')
        index = next(i for i, r in enumerate(self.rows[kind]) if r['hash'] == field_hash)
        table = self.client.read(lookup, capacity * 8)
        if struct.pack('<II', int(field_hash, 16), index) not in table:
            raise ValueError('Location runtime hash/index differs from this revision')
        address = bank + index * stride
        raw = self.client.read(address, stride)
        if raw[:8] != self.client.read(bank, 8):
            raise ValueError('Location object type changed; reconnect')
        return address, raw

    def field(self, kind, field_hash):
        address, raw = self.object(kind, field_hash)
        if kind == 'Vector3':
            return list(struct.unpack_from('<3f', raw, 36))
        if kind == 'Float':
            return struct.unpack_from('<f', raw, 28)[0]
        if struct.unpack_from('<Q', raw, 104)[0] != address + 116 or struct.unpack_from('<I', raw, 112)[0] != 64:
            raise ValueError('Location string wrapper changed')
        text = raw[116:180]
        if b'\0' not in text:
            raise ValueError('Unterminated location name')
        return text.split(b'\0', 1)[0].decode('ascii')

    def capture(self):
        session = self.binding.session_id
        if self.binding.object('ef2b60c2', 'Bool')[1][22]:
            raise ValueError('Wait for area loading to finish before saving a location')
        banc = self.field('String64', '1d6189da')
        if banc not in presets():
            raise ValueError('Loaded area is unavailable; wait for gameplay')
        position = self.field('Vector3', '307d7d97')
        yaw = self.field('Float', 'a4aee8cd')
        _, age_raw = self.binding.object('cea220d3', 'Bool')
        if age_raw[22] not in (0, 1):
            raise ValueError('Player age is updating; wait for gameplay')
        age = 'Child' if age_raw[22] else 'Adult'
        if session != self.binding.session_id or banc != self.field('String64', '1d6189da'):
            raise ValueError('Area changed during capture; try again after loading')
        # The map arrow is world yaw minus180 degrees. The loader takes radians.
        # Verified against FrontDekuTree's -1.4285694 rad ->98.14898 degree map yaw.
        facing = math.radians((yaw + 360) % 360 - 180)
        return validate_pose(dict(banc=banc, age=age, position=position, rotation=[0, facing, 0],
                                  rotation_units='radians', source='Sequence_CurrentBanc + CurrentPos + map yaw',
                                  cross_area_freshness_verified=True))
