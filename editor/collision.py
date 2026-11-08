"""Revision-guarded, read-only collision camera snapshots and overlay lifetime."""
import json
import math
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import sys
import time
import backend
from camera import view_pose
from location_capture import LocationCapture


def projection_matrix(values):
    if len(values) != 16 or not all(math.isfinite(v) for v in values):
        raise ValueError('Collision projection is unavailable')
    # Native perspective matrix, row-major; reject unrelated/stale memory.
    if (not .1 < values[0] < 20 or not .1 < abs(values[5]) < 20 or
            abs(values[14]+1) > .001 or abs(values[15]) > .001 or
            not -1.1 < values[10] < -.9 or values[11] >= 0 or
            any(abs(values[i]) > .001 for i in (1, 2, 3, 4, 6, 7, 8, 9, 12, 13))):
        raise ValueError('Collision camera projection layout differs')
    return list(values)


class CollisionReader:
    def __init__(self, binding):
        self.binding = binding
        self.fields = LocationCapture(binding)
        self.area_object = None
        self.area_session = None
        self.last_bind = 0.

    def read(self):
        b = self.binding
        b.validate()
        session = tuple(b.session_id)
        if b.object('ef2b60c2', 'Bool')[1][22]:
            return dict(waiting=True, session=list(session))
        base = b.bool_desc['vtable']-0x4c20658
        read = b.client.read
        u64 = lambda p: struct.unpack('<Q', read(p, 8))[0]
        if u64(base+0x4c7dda0) != base+0x4e371e8:
            raise ValueError('Collision camera module revision differs')
        manager = u64(base+0x4e371e8)
        lo, hi = b.assignments.heap
        if not lo <= manager < manager+0x3b90 <= hi or u64(manager) != base+0x4b73d20:
            raise ValueError('Collision camera manager changed; reconnect')
        # View and projection copied in a single bridge read.
        raw = read(manager+0x3ab0, 0xe0)
        view = list(struct.unpack_from('<12f', raw))
        pose = view_pose(view)
        projection = projection_matrix(struct.unpack_from('<16f', raw, 0xa0))
        # Bind the typed string through its hash table, then use guarded direct
        # reads for flight. Rewalking all location tables every frame costs ~100ms.
        if self.area_session != session or time.monotonic()-self.last_bind > 1:
            address, obj = self.fields.object('String64', '1d6189da')
            self.area_object = (address, obj[:8])
            self.area_session = session
            self.last_bind = time.monotonic()
        address, vtable = self.area_object
        obj = read(address, 180)
        if (obj[:8] != vtable or struct.unpack_from('<QI', obj, 104) != (address+116, 64) or
                b'\0' not in obj[116:180]):
            raise ValueError('Collision area object changed; reconnect')
        scene = obj[116:180].split(b'\0', 1)[0].decode('ascii')
        from locations import presets
        if scene not in presets() or b.object('ef2b60c2', 'Bool')[1][22]:
            return dict(waiting=True, session=list(session))
        if tuple(b.session()) != session:
            raise ValueError('Emulator session changed during collision read')
        return dict(scene=scene, eye=pose['eye'], view=view+[0., 0., 0., 1.],
                    projection=projection, pid=session[0], session=list(session))


class Overlay:
    """An isolated renderer; closing or losing the editor stops it automatically."""
    def __init__(self):
        self.process = None
        self.socket = None
        self.token = None
        self.port = None
        self.target = None
        self.log = None
        self.last_result = {}

    def start(self):
        if self.process is not None:
            self.stop()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('127.0.0.1', 0))
        self.socket.setblocking(False)
        self.port = self.socket.getsockname()[1]
        self.token = secrets.token_hex(24)
        self.target = None
        path = backend.ROOT/'runtime/collision-overlay.log'
        path.parent.mkdir(parents=True, exist_ok=True)
        self.log = path.open('w', encoding='utf-8')
        self.process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('collision_overlay.py')),
            '--parent', str(os.getpid()), '--port', str(self.port), '--token', self.token],
            stdout=self.log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.last_result = {}

    def send(self, **state):
        if self.socket and self.target:
            self.socket.sendto(json.dumps(dict(token=self.token, **state)).encode(), self.target)

    def poll(self):
        if not self.socket:
            return {}
        try:
            while True:
                raw, address = self.socket.recvfrom(65536)
                message = json.loads(raw)
                if message.get('token') == self.token:
                    self.target = address
                    self.last_result = message
        except BlockingIOError:
            pass
        if self.process and self.process.poll() is not None:
            raise RuntimeError('Collision renderer closed. See runtime/collision-overlay.log.')
        return self.last_result

    def stop(self):
        # Child watches the parent and a short heartbeat as a second cleanup path.
        if self.socket:
            try:
                self.send(stop=True)
            except OSError:
                pass
            self.socket.close()
            self.socket = None
        if self.process:
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=2)
            self.process = None
        if self.log:
            self.log.close()
            self.log = None
