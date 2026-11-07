"""One-shot native player position requests in the isolated debug profile."""
import json
import math
import struct
import time
import uuid
from teleport import TeleportTransport, ROOT, MOD

REQUEST = '7325ce62'  # DebugParam.IsOverrideTraversePos; consumed in MainUpdate.
DESTINATION = '527fa715'  # DebugParam.OverrideTraversePos, unsaved Vector3.
STEPS = (-100, -10, -1, 1, 10, 100)


def coordinates(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError('Enter X, Y and Z')
    if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1_000_000 for v in value):
        raise ValueError('Coordinates must be finite and within world bounds')
    return list(struct.unpack('<3f', struct.pack('<3f', *value)))


class PositionTransport:
    def __init__(self, binding):
        self.binding = binding
        self.scene = TeleportTransport(binding)
        self.client = binding.client

    def move(self, value=None, *, axis=None, delta=None, timeout=5, expected_area=None):
        if axis is None:
            desired = coordinates(value)
            if delta is not None:
                raise ValueError('Choose coordinates or an axis nudge')
        else:
            if value is not None or type(axis) is not int or axis not in range(3) or type(delta) not in (int, float) or delta not in STEPS:
                raise ValueError('Choose X/Y/Z and a supported nudge')
            desired = None
        self.scene.validate()
        if json.loads((MOD/'manifest.json').read_text(encoding='utf-8')).get('position_protocol') != 1:
            raise ValueError('Launch the updated debug game before moving coordinates')
        if self.scene.boolean(REQUEST):
            raise ValueError('A position request is already pending; do not repeat it')
        before = self.scene.fields.capture()
        if expected_area is not None and before['banc'] != expected_area:
            raise ValueError('Area changed since the coordinates were displayed; refresh before moving')
        if desired is None:
            desired = list(before['position'])
            desired[axis] += delta
            desired = coordinates(desired)
        address, raw = self.scene.fields.object('Vector3', DESTINATION)
        writes = []
        for i, new in enumerate(struct.unpack('<3I', struct.pack('<3f', *desired))):
            old = struct.unpack_from('<I', raw, 36 + i*4)[0]
            if old != new:
                writes.append(dict(address=address+36+i*4, expected=old, value=new))
        path = ROOT/'runtime/position-audits'/(uuid.uuid4().hex+'.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        audit = dict(session=self.binding.session_id, before=before, requested=desired,
                     axis=axis, delta=delta, writes=writes, state='preparing', automatic_retry=False)
        completed = []
        published = False
        def save():
            path.write_text(json.dumps(audit, indent=2)+'\n')
        try:
            save()
            for row in writes:
                self.scene._cas(row)
                completed.append(row)
            # Check gameplay again after preparation and publish the single flag last.
            self.scene.validate()
            if self.scene.fields.field('String64', '1d6189da') != before['banc']:
                raise ValueError('Area changed while preparing the move')
            flag, flag_raw = self.binding.object(REQUEST, 'Bool')
            if flag_raw[22] != 0:
                raise ValueError('Another position request started')
            old = struct.unpack_from('<I', flag_raw, 20)[0]
            published = True
            self.scene._cas(dict(address=flag+20, expected=old, value=old|0x10000))
            audit['state'] = 'requested'; save()
            end = time.monotonic()+timeout
            while time.monotonic() < end:
                if not self.scene.boolean(REQUEST):
                    # Allow the selector to observe false before another button request.
                    start_present = self.client.status()['presents']
                    while time.monotonic() < end and self.client.status()['presents'] < start_present+2:
                        time.sleep(.015)
                    audit.update(state='applied', after=self.scene.fields.capture())
                    return audit
                time.sleep(.015)
            raise TimeoutError('Position request not acknowledged. Inspect the game; no automatic retry.')
        except Exception as exc:
            audit.update(state='uncertain-after-request' if published else 'cancelled-before-request', error=str(exc))
            if not published:
                for row in reversed(completed):
                    try:
                        self.client.compare_write(row['address'], row['value'], row['expected'])
                    except Exception:
                        pass
            raise
        finally:
            save()
