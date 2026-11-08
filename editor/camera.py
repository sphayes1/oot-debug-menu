"""Revision-checked native free camera. Only unsaved request fields are written."""
import json
import math
import struct
import time

from location_capture import LocationCapture
from position import PositionTransport, coordinates
from teleport import TeleportTransport, MOD

SENTINEL = '__OOT_FREE_CAMERA_V1__'
FLAG = '0b570ab2'  # Sequence_ReservedNextStartPosName; shared song/entrance mailbox.
EYE = '527fa715'   # DebugParam.OverrideTraversePos.
AT = '1662143e'    # Sequence_ReservedNextCancelSleepRot.


def view_pose(matrix):
    if len(matrix) != 12 or not all(math.isfinite(v) for v in matrix):
        raise ValueError('Camera matrix is unavailable')
    rows = [matrix[i:i+3] for i in (0, 4, 8)]
    if any(abs(sum(v*v for v in row)-1) > .01 for row in rows):
        raise ValueError('Camera rotation is not ready')
    if any(abs(sum(rows[i][k]*rows[j][k] for k in range(3))) > .01
           for i, j in ((0, 1), (0, 2), (1, 2))):
        raise ValueError('Camera rotation is not orthogonal')
    eye = coordinates([-sum(matrix[row*4+axis]*matrix[row*4+3] for row in range(3))
                       for axis in range(3)])
    forward = [-v for v in rows[2]]
    return dict(eye=eye, yaw=math.atan2(forward[0], forward[2]),
                pitch=math.asin(max(-1., min(1., forward[1]))))


def look_at(eye, yaw, pitch):
    if not all(math.isfinite(v) for v in (yaw, pitch)) or abs(pitch) > math.radians(89):
        raise ValueError('Invalid camera direction')
    cp = math.cos(pitch)
    return coordinates([eye[0]+10*math.sin(yaw)*cp,
                        eye[1]+10*math.sin(pitch), eye[2]+10*math.cos(yaw)*cp])


def fly(pose, side=0., forward=0., vertical=0., distance=0., dx=0., dy=0.):
    """Camera-relative flight; Y is world height. Diagonals retain the same speed."""
    yaw = pose['yaw']-dx*.004
    pitch = max(-math.radians(89), min(math.radians(89), pose['pitch']-dy*.004))
    cp, sp, sy, cy = math.cos(pitch), math.sin(pitch), math.sin(yaw), math.cos(yaw)
    direction = [-side*cy+forward*sy*cp, vertical+forward*sp, side*sy+forward*cy*cp]
    scale = max(1., math.sqrt(sum(v*v for v in direction)))
    eye = coordinates([pose['eye'][i]+distance*direction[i]/scale for i in range(3)])
    return dict(eye=eye, yaw=yaw, pitch=pitch)


class Camera:
    def __init__(self, binding):
        self.binding = binding
        self.client = binding.client
        self.fields = LocationCapture(binding)
        self.scene = TeleportTransport(binding)
        self.active = False
        self.pose = None
        self.session_id = None
        self.area = None
        self.previous = None
        self.last_check = 0.

    def read(self):
        self.binding.validate()
        base = self.binding.bool_desc['vtable']-0x4c20658
        u64 = lambda address: struct.unpack('<Q', self.client.read(address, 8))[0]
        if u64(base+0x4c7dda0) != base+0x4e371e8:
            raise ValueError('Camera module revision differs')
        manager = u64(base+0x4e371e8)
        lo, hi = self.binding.assignments.heap
        if not lo <= manager < manager+0x3b10 <= hi or u64(manager) != base+0x4b73d20:
            raise ValueError('Camera manager changed; reconnect')
        return view_pose(struct.unpack('<12f', self.client.read(manager+0x3ab0, 48)))

    def _cas(self, address, expected, value):
        if expected == value:
            return
        result = self.client.compare_write(address, expected, value)
        if not result.get('swapped') or not result.get('readback_matches'):
            raise ValueError('Camera request changed during publication; reconnect before retrying')

    def _vector(self, key, value):
        payload = struct.pack('<3f', *coordinates(value))
        address, raw = self.fields.object('Vector3', key)
        for offset in range(0, 12, 4):
            self._cas(address+36+offset, struct.unpack_from('<I', raw, 36+offset)[0],
                      struct.unpack_from('<I', payload, offset)[0])

    def _flag(self, expected, value):
        address, raw = self.fields.object('String64', FLAG)
        if (struct.unpack_from('<Q', raw, 104)[0] != address+116 or
                struct.unpack_from('<I', raw, 112)[0] != 64):
            raise ValueError('Camera mailbox layout differs')
        if raw[116:180].split(b'\0')[0].decode('ascii') != expected:
            raise ValueError('Camera mailbox belongs to another operation')
        payload = value.encode('ascii').ljust(64, b'\0')
        # Publish the first word last; clearing it first disables the native branch.
        order = [*range(4, 64, 4), 0] if value else range(0, 64, 4)
        for offset in order:
            self._cas(address+116+offset, struct.unpack_from('<I', raw, 116+offset)[0],
                      struct.unpack_from('<I', payload, offset)[0])

    def enable(self):
        self.scene.validate()
        if json.loads((MOD/'manifest.json').read_text()).get('camera_protocol') != 1:
            raise ValueError('Launch the updated debug game to use free flight')
        if self.fields.field('String64', FLAG):
            raise ValueError('Song/teleport mailbox is busy; disable an existing free camera first')
        pose = self.read()
        self.session_id = tuple(self.binding.session_id)
        self.area = self.fields.capture()['banc']
        self.previous = (self.fields.field('Vector3', EYE), self.fields.field('Vector3', AT))
        try:
            self._vector(EYE, pose['eye'])
            self._vector(AT, look_at(**pose))
            self.scene.validate()
            self._flag('', SENTINEL)
            self.active = True
            self.pose = pose
            self.last_check = 0.
            # Observe the rendered camera, not just a successful memory write.
            end = time.monotonic()+3
            start = self.client.status()['presents']
            while time.monotonic() < end:
                if self.client.status()['presents'] >= start+3:
                    if math.dist(self.read()['eye'], pose['eye']) < .15:
                        return pose
                time.sleep(.015)
            raise TimeoutError('Native camera did not acknowledge the requested view')
        except Exception:
            self.disable()
            raise

    def disable(self):
        # A fresh editor can recover a camera left enabled by a crashed client.
        # Never write addresses or payloads from a previous emulator session.
        if self.session_id is not None and tuple(self.binding.session()) != self.session_id:
            self.active = False
            self.previous = None
            return
        self.binding.validate()
        flag = self.fields.field('String64', FLAG)
        if flag == SENTINEL:
            self._flag(SENTINEL, '')
        if flag in ('', SENTINEL) and self.previous is not None:
            self._vector(EYE, self.previous[0])
            self._vector(AT, self.previous[1])
        self.active = False
        self.previous = None

    def check(self):
        if not self.active:
            return
        if tuple(self.binding.session()) != self.session_id:
            self.active = False
            raise ValueError('Emulator session changed; reconnect the camera')
        if self.fields.field('String64', FLAG) != SENTINEL:
            self.active = False
            raise ValueError('Camera mailbox changed; free flight stopped')
        if self.fields.capture()['banc'] != self.area:
            self.disable()
            raise ValueError('Area changed; free flight was disabled')
        try:
            self.scene.validate()
        except Exception:
            self.disable()
            raise
        self.last_check = time.monotonic()

    def update(self, pose):
        if not self.active:
            raise ValueError('Enable free flight first')
        eye = coordinates(pose['eye'])
        at = look_at(eye, pose['yaw'], pose['pitch'])
        if time.monotonic()-self.last_check > .2:
            self.check()
        try:
            self._vector(EYE, eye)
            self._vector(AT, at)
        except Exception:
            try:
                self.disable()
            except Exception:
                pass  # Preserve the original failure; recovery stays available in the UI.
            raise
        self.pose = dict(eye=eye, yaw=pose['yaw'], pitch=pose['pitch'])
        return self.pose

    def teleport(self):
        self.check()
        if not self.active or self.pose is None:
            raise ValueError('Enable free flight before teleporting to the camera')
        actual = self.read()['eye']
        if math.dist(actual, self.pose['eye']) > .2:
            raise ValueError('Camera is still moving; release the flight controls and try again')
        return PositionTransport(self.binding).move(actual, expected_area=self.area)
