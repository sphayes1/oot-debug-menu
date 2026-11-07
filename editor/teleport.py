"""Revision-checked native scene-change transport for the isolated debug profile."""
import hashlib
import json
import math
import re
import struct
import time
import uuid
from datetime import datetime
from pathlib import Path
from location_capture import LocationCapture
from locations import validate_pose, presets

ROOT = Path(__file__).resolve().parent
MOD = ROOT / 'runtime/load/0400486024DEC000/Debug Teleport (test)'
TRIGGER = '3fc35576'  # DebugParam.IsRequestedResetGimmick, redirected only in this profile.
BOOLS = (TRIGGER, 'ef2b60c2', '9a9506e7', '604aebe1', 'c2f987db', '2884dfbb', 'da576eaa', '7325ce62')
AGE = 'cea220d3'  # Sequence_IsChildhood, saved Bool.
MANUAL_AGE = '86724737'  # DebugParam.IsSetChildhoodManually; loader consumes it once.


class TeleportTransport:
    def __init__(self, binding):
        self.binding = binding
        self.client = binding.client
        self.fields = LocationCapture(binding)
        self.areas = presets()

    def boolean(self, key):
        self.binding.validate()
        address, data = self.binding.object(key, 'Bool')
        if data[22] not in (0, 1):
            raise ValueError('Scene state is updating; wait for gameplay')
        return bool(data[22])

    def validate(self, *, age_reload=False):
        b = self.binding
        b.validate()
        status = self.client.status()
        if status['paused']:
            raise ValueError('Resume the emulator before teleporting')
        manifest = json.loads((MOD / 'manifest.json').read_text(encoding='utf-8'))
        if age_reload and manifest.get('age_reload_protocol') != 1:
            raise ValueError('Install the updated age-reload module and relaunch the debug game first')
        session = json.loads((ROOT / 'runtime/session.json').read_text(encoding='utf-8'))
        started = datetime.fromisoformat(re.sub(r'(\.\d{6})\d+', r'\1', session['started'])).timestamp()
        for name, expected in manifest['files'].items():
            path = MOD / name
            if path.stat().st_mtime > started or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('Teleport files changed; relaunch the debug game')
        base = b.bool_desc['vtable'] - 0x4c20658
        if self.client.read(base + 0x3304228, 4) != struct.pack('<I', 0x3940a661):
            raise ValueError('Launch the debug game with its teleport module first')
        header = self.client.read(b.bool_desc['address'], 40)
        lookup, capacity = struct.unpack_from('<Q', header, 24)[0], struct.unpack_from('<I', header, 36)[0]
        table = b.read_chunks(lookup, capacity * 8)
        for key in (*BOOLS, AGE, MANUAL_AGE, '7325ce62'):
            if struct.pack('<II', int(key, 16), b.indices['Bool'][key]) not in table:
                raise ValueError('Scene-state hash/index does not match this game revision')
        # Main's native event selector gives active events priority over debug requests.
        slot = struct.unpack('<Q', self.client.read(base + 0x4c7e090, 8))[0]
        manager = struct.unpack('<Q', self.client.read(slot, 8))[0]
        if not b.assignments.heap[0] <= manager < b.assignments.heap[1]:
            raise ValueError('Scene event manager is unavailable')
        if struct.unpack('<Q', self.client.read(manager + 0x68, 8))[0]:
            raise ValueError('Finish the conversation or event before teleporting')
        if any(self.boolean(key) for key in BOOLS):
            raise ValueError('Close game menus and wait for area loading to finish')
        if self.fields.field('String64', 'ee27bf71'):
            raise ValueError('Another area change is pending')

    def warp(self, pose, revision=None, timeout=180, *, target_age=None, allow_any_era=False):
        if type(allow_any_era) is not bool:
            raise ValueError('Invalid era override')
        pose = validate_pose(pose)
        if pose['banc'] not in self.areas or len(pose['banc'].encode('ascii')) > 63:
            raise ValueError('Unknown destination area')
        entry = pose.get('entry', '')
        if not isinstance(entry, str) or len(entry.encode('ascii')) > 63:
            raise ValueError('Invalid destination entry')
        if entry and entry not in self.areas[pose['banc']]:
            raise ValueError('Unknown destination entry')
        if revision and revision != self.binding.schema['source_sha256']:
            raise ValueError('This bookmark belongs to a different game revision')
        if revision and pose.get('rotation_units') != 'radians':
            raise ValueError('This bookmark predates verified facing capture; save the location again')
        active_age = self.binding.assignments.view()['active_age']
        if target_age is not None and (target_age not in ('Child', 'Adult') or
                                       target_age != pose['age'] or target_age == active_age):
            raise ValueError('Choose the other player age and its matching destination')
        cross_era = allow_any_era
        if target_age is None and not cross_era and pose['age'] != active_age:
            raise ValueError('Choose a destination for the current player era')
        if not cross_era and (('_Adult' in pose['banc'] and pose['age'] != 'Adult') or ('_Child' in pose['banc'] and pose['age'] != 'Child')):
            raise ValueError('Destination era differs from the current player')
        expected_age = target_age if target_age is not None else active_age if cross_era else pose['age']
        self.validate()
        origin = self.fields.capture()
        session = self.binding.session_id
        writes = []

        def prepare(kind, key, payload):
            address, raw = self.fields.object(kind, key)
            offset = 116 if kind == 'String64' else 36
            if kind == 'String64' and (struct.unpack_from('<Q', raw, 104)[0] != address + 116 or
                                       struct.unpack_from('<I', raw, 112)[0] != 64):
                raise ValueError('Destination string layout changed')
            for i in range(0, len(payload), 4):
                old = struct.unpack_from('<I', raw, offset + i)[0]
                new = struct.unpack_from('<I', payload, i)[0]
                if old != new:
                    writes.append(dict(address=address + offset + i, expected=old, value=new))

        prepare('Vector3', '52046b85', struct.pack('<3f', *pose['position']))
        prepare('Vector3', '1662143e', struct.pack('<3f', *pose['rotation']))
        prepare('String64', '0b570ab2', entry.encode('ascii').ljust(64, b'\0'))
        prepare('String64', 'ee27bf71', pose['banc'].encode('ascii').ljust(64, b'\0'))
        override_age = target_age is not None or cross_era
        if override_age:
            # Era-specific areas normally force their configured player age.
            # The override also asks the loader to retain the current model age.
            requested_age = target_age if target_age is not None else active_age
            for key, value, saved in ((AGE, requested_age == 'Child', True), (MANUAL_AGE, True, False)):
                address, raw = self.binding.object(key, 'Bool')
                if raw[22] not in (0, 1) or (saved and raw[23] not in (0, 1)):
                    raise ValueError('Age state is updating; wait for gameplay')
                if key == AGE and bool(raw[22]) != (active_age == 'Child'):
                    raise ValueError('Age changed while preparing the request')
                if key == MANUAL_AGE and raw[22]:
                    raise ValueError('A manual age change is already pending')
                old = struct.unpack_from('<I', raw, 20)[0]
                new = ((old & 0xffff) | (int(value) << 16) | (int(value) << 24)) if saved else old | 0x10000
                if old != new:
                    writes.append(dict(address=address + 20, expected=old, value=new))
        path = ROOT / 'runtime/teleport-audits' / (uuid.uuid4().hex + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        audit = dict(session=session, origin=origin, destination=pose, state='preparing', writes=writes,
                     target_age=target_age, allow_any_era=allow_any_era, expected_age=expected_age)
        completed = []
        committed = False
        try:
            path.write_text(json.dumps(audit, indent=2) + '\n')
            for row in writes:
                self._cas(row)
                completed.append(row)
            # Destination is complete before publishing the single native request flag.
            address, raw = self.binding.object(TRIGGER, 'Bool')
            if raw[22] != 0:
                raise ValueError('Another scene request started during preparation')
            old = struct.unpack_from('<I', raw, 20)[0]
            committed = True  # A lost response must never cause replay/rollback after publication.
            self._cas(dict(address=address + 20, expected=old, value=old | 0x10000))
            audit['state'] = 'requested'
            path.write_text(json.dumps(audit, indent=2) + '\n')
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                time.sleep(.5)
                self.binding.validate()
                if (not self.boolean(TRIGGER) and not self.boolean('ef2b60c2') and
                        not self.boolean('9a9506e7') and
                        self.fields.field('String64', 'ee27bf71') == '' and
                        self.fields.field('String64', '1d6189da') == pose['banc']):
                    actual = self.fields.capture()
                    distance = math.dist(actual['position'], pose['position'])
                    if distance > 3:
                        raise ValueError('Area loaded, but the requested standing position was not reached')
                    if actual['age'] != expected_age:
                        raise ValueError('Area loaded, but player age does not match the request')
                    if override_age and self.boolean(MANUAL_AGE):
                        # The loader clears this after creating the requested resident actors.
                        continue
                    audit.update(state='arrived', actual=actual, position_error=distance)
                    return audit
            raise TimeoutError('Area loading did not finish in time. No request was repeated; inspect the game.')
        except Exception as exc:
            audit.update(state='uncertain-after-request' if committed else 'cancelled-before-request', error=str(exc))
            if not committed:
                for row in reversed(completed):
                    try:
                        self.client.compare_write(row['address'], row['value'], row['expected'])
                    except Exception:
                        pass
            raise
        finally:
            path.write_text(json.dumps(audit, indent=2) + '\n')

    def _cas(self, row):
        result = self.client.compare_write(row['address'], row['expected'], row['value'])
        if not result.get('swapped') or not result.get('readback_matches'):
            raise ValueError('Game state changed during the teleport request; no automatic retry')
