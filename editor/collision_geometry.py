"""Read-only, bounded Phive tagfile decoding. No game assets are shipped here.

Layouts were investigated with oot26-tools (mrissaoussama), revision
5c8d03ecf674bf62c7e72954c885b6f177e71480. This is an independent reader.
"""
import math
import struct
import numpy as np

LIMIT = 4_000_000
EMPTY = np.empty((0, 3, 3), dtype=np.float32)


def checked(data, offset, size):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError('Collision data range is outside its container')
    return offset


def sections(data, start, end):
    while start < end:
        checked(data, start, 8)
        size = struct.unpack_from('>I', data, start)[0] & 0x3fffffff
        if size < 8 or start + size > end:
            raise ValueError('Invalid collision tag section')
        yield data[start+4:start+8], start+8, start+size
        start += size


def varint(data, pos, end):
    checked(data, pos, 1)
    byte = data[pos]
    n, mask = ((1, 127) if byte < 128 else (2, 63) if byte < 192 else
               (3, 31) if byte < 224 else (4, 7) if byte < 232 else (5, 7))
    if pos+n > end:
        raise ValueError('Truncated collision type integer')
    return ((byte & mask) << ((n-1)*8)) | int.from_bytes(data[pos+1:pos+n], 'big'), pos+n


class TagFile:
    def __init__(self, data, start, end):
        self.data = data
        table = {}
        for name, lo, hi in sections(data, start, end):
            table[name] = (lo, hi)
            if name in (b'TYPE', b'INDX'):
                table.update({k: (a, b) for k, a, b in sections(data, lo, hi)})
        self.begin, self.end = table[b'DATA']
        strings = data[slice(*table[b'TST1'])].split(b'\0')
        pos, stop = table[b'TNA1']
        count, pos = varint(data, pos, stop)
        if count > 100000:
            raise ValueError('Too many collision types')
        types = [None]
        for _ in range(1, count):
            index, pos = varint(data, pos, stop)
            params, pos = varint(data, pos, stop)
            if index >= len(strings) or params > 1000:
                raise ValueError('Invalid collision type parameters')
            for _ in range(params*2):
                _, pos = varint(data, pos, stop)
            types.append(strings[index].decode('ascii'))
        lo, hi = table[b'ITEM']
        if (hi-lo) % 12:
            raise ValueError('Invalid collision item table')
        self.items = {}
        self.root = None
        for i, p in enumerate(range(lo, hi, 12)):
            kind, offset, count = struct.unpack_from('<III', data, p)
            kind &= 0xffffff
            if kind >= len(types) or count > LIMIT:
                raise ValueError('Invalid collision item')
            if i == 1:
                self.root = types[kind]
            if count:
                self.items[offset] = (types[kind], count)
        self.cache = {}

    def at(self, off, size):
        if off < 0 or off+size > self.end-self.begin:
            raise ValueError('Collision shape extends outside DATA')
        return self.begin+off

    def unpack(self, fmt, off):
        return struct.unpack_from(fmt, self.data, self.at(off, struct.calcsize(fmt)))

    def array(self, off, count, dtype):
        dt = np.dtype(dtype)
        if count < 0 or count > LIMIT*12:
            raise ValueError('Collision array exceeds reader limit')
        return np.frombuffer(self.data, dt, count, self.at(off, count*dt.itemsize))

    def relative(self, off):
        delta, count = self.unpack('<iI', off)
        if count > LIMIT:
            raise ValueError('Collision relative array exceeds limit')
        return off+delta, count

    def mesh(self, off):
        first, count = self.relative(off+0x88)
        tagoff, ntag = self.relative(off+0x60)
        runs = self.array(tagoff, ntag*2, '<u4').reshape(-1, 2)
        if len(runs) and np.any(runs[1:, 0] < runs[:-1, 0]):
            raise ValueError('Unsorted collision shape tags')
        triangles, tags = [], []
        for i in range(count):
            section = first+i*64
            po, pn = self.relative(section+8)
            vo, _ = self.relative(section+16)
            if not pn:
                continue
            indices = self.array(po, pn*4, 'u1').reshape(-1, 4).astype(np.int32)
            nv = int(indices.max())+1
            vertices = self.array(vo, nv*3, '<u2').reshape(-1, 3).astype(np.float32)
            vertices += np.asarray(self.unpack('<3i', section+32), dtype=np.float32)
            vertices /= 512.
            keys = (i << 8) | np.arange(pn)
            values = (runs[np.maximum(0, np.searchsorted(runs[:, 0], keys, side='right')-1), 1]
                      if ntag else np.zeros(pn, dtype=np.int64))
            triangles.append(vertices[indices[:, :3]])
            tags.append(values)
            quad = indices[:, 2] != indices[:, 3]
            if np.any(quad):
                triangles.append(vertices[indices[quad][:, (0, 2, 3)]])
                tags.append(values[quad])
        return (np.concatenate(triangles), np.concatenate(tags)) if triangles else (EMPTY, np.zeros(0, np.int64))

    def shape(self, off=0, depth=0):
        if depth > 5:
            raise ValueError('Collision compound nesting limit reached')
        if off in self.cache:
            return self.cache[off]
        kind = self.items.get(off, (None,))[0]
        tags = None
        if kind == 'hknpMeshShape':
            result, tags = self.mesh(off)
        elif kind in ('hknpBoxShape', 'hknpConvexShape', 'hknpConvexPolytopeShape'):
            vo, vn = self.relative(off+0x38)
            fo, fn = self.relative(off+0x48)
            io, ni = self.relative(off+0x50)
            vertices = self.array(vo, vn*3, '<f4').reshape(-1, 3)
            indices = self.array(io, ni, 'u1')
            faces = []
            for i in range(fn):
                first, count = self.unpack('<HB', fo+4*i)
                if first+count > ni:
                    raise ValueError('Collision face indices exceed array')
                face = indices[first:first+count]
                if count and int(face.max()) >= vn:
                    raise ValueError('Collision face refers to missing vertex')
                for j in range(1, count-1):
                    faces.append(vertices[face[[0, j, j+1]]])
            result = np.asarray(faces, dtype=np.float32).reshape(-1, 3, 3)
        elif kind == 'hknpCapsuleShape':
            po, pn = self.relative(off+0x38)
            if pn < 2:
                raise ValueError('Capsule endpoints missing')
            result = capsule(self.array(po, 6, '<f4').reshape(2, 3), self.unpack('<f', off+0x68)[0])
        elif kind == 'hknpCompoundShape':
            groups = list(self.instances(off, depth+1))
            result = np.concatenate([g[1] for g in groups]) if groups else EMPTY
            tags = np.concatenate([g[2] for g in groups]) if groups else np.zeros(0, np.int64)
        else:
            # Unsupported shapes are reported by the scene reader, never replaced by an AABB.
            return EMPTY, np.zeros(0, np.int64)
        if tags is None:
            tags = np.zeros(len(result), np.int64)
        self.cache[off] = (result, tags)
        return result, tags

    def instances(self, off=0, depth=0):
        if depth > 5:
            raise ValueError('Collision compound nesting limit reached')
        found = None
        for field in range(0, min(256, self.end-self.begin-off-7), 4):
            delta, _ = self.unpack('<iI', off+field)
            target = off+field+delta
            item = self.items.get(target)
            if item and item[0] == 'hkFreeListArrayElement':
                found = (target, item[1])
                break
        if found is None:
            return
        first, count = found
        if depth == 0:
            self.instance_count = count
            self.instance_offset = first
        self.at(first, count*64)
        for index in range(count):
            p = first+index*64
            shape, _ = self.relative(p+48)
            if shape not in self.items:
                continue
            triangles, tags = self.shape(shape, depth+1)
            if not len(triangles):
                continue
            q = self.array(p, 4, '<f4')
            tr = self.array(p+16, 3, '<f4')
            scale = self.array(p+32, 3, '<f4')
            if not np.all(np.isfinite(scale)) or not np.any(scale):
                scale = np.ones(3)
            if not np.isfinite(q).all() or abs(float(q@q)-1) > .02:
                raise ValueError('Collision instance quaternion is invalid')
            yield index, (triangles*scale) @ quaternion(q).T + tr, tags


def tagfiles(data):
    pos = 0
    while True:
        match = data.find(b'TAG0', pos)
        if match < 0:
            return
        start = match-4
        checked(data, start, 8)
        size = struct.unpack_from('>I', data, start)[0] & 0x3fffffff
        checked(data, start, size)
        if size < 8:
            raise ValueError('Invalid TAG0 size')
        yield TagFile(data, start+8, start+size)
        pos = start+size


def quaternion(q):
    x, y, z, w = (float(v) for v in q)
    return np.array(((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
                     (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
                     (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y))), dtype=np.float32)


def box(center=(0, 0, 0), half=(.5, .5, .5)):
    v = np.array([(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], np.float32)
    v = v*np.asarray(half)+np.asarray(center)
    faces = ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))
    return np.asarray([v[[f[0], f[j], f[j+1]]] for f in faces for j in (1, 2)], np.float32)


def sphere(center=(0, 0, 0), radius=1., rings=8, sides=16):
    vertices = np.array([[(math.sin(math.pi*i/rings)*math.cos(2*math.pi*j/sides),
                           math.cos(math.pi*i/rings), math.sin(math.pi*i/rings)*math.sin(2*math.pi*j/sides))
                          for j in range(sides)] for i in range(rings+1)])*radius+center
    return np.asarray([vertices[[i, i+1, i+1], [j, j, (j+1)%sides]] if k == 0 else
                       vertices[[i, i+1, i], [j, (j+1)%sides, (j+1)%sides]]
                       for i in range(rings) for j in range(sides) for k in (0, 1)], np.float32)


def cylinder(endpoints, radius=1., sides=16):
    a, b = np.asarray(endpoints, dtype=np.float32)
    axis = b-a
    norm = np.linalg.norm(axis)
    if norm < 1e-7:
        return EMPTY
    axis /= norm
    u = np.cross(axis, (0, 1, 0) if abs(axis[1]) < .9 else (1, 0, 0)); u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    ring = np.asarray([radius*(u*math.cos(2*math.pi*j/sides)+v*math.sin(2*math.pi*j/sides)) for j in range(sides)])
    return np.asarray([tri for j in range(sides) for tri in (
        (a+ring[j], a+ring[(j+1)%sides], b+ring[(j+1)%sides]),
        (a+ring[j], b+ring[(j+1)%sides], b+ring[j]),
        (a, a+ring[j], a+ring[(j+1)%sides]), (b, b+ring[(j+1)%sides], b+ring[j]))], np.float32)


def capsule(endpoints, radius):
    a, b = np.asarray(endpoints, np.float32)
    return np.concatenate((cylinder((a, b), radius), sphere(a, radius), sphere(b, radius)))


def place(triangles, actor):
    x, y, z = map(float, actor.get('Rotate', (0, 0, 0)))
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    r = np.array(((cz, -sz, 0), (sz, cz, 0), (0, 0, 1))) @ np.array(((cy, 0, sy), (0, 1, 0), (-sy, 0, cy))) @ np.array(((1, 0, 0), (0, cx, -sx), (0, sx, cx)))
    return np.asarray((triangles*np.asarray(actor.get('Scale', (1, 1, 1)))) @ r.T + actor.get('Translate', (0, 0, 0)), np.float32)


def static_geometry(data, tiled=False, ignored_transforms=()):
    """Yield world-space triangles for terrain and baked objects."""
    checked(data, 8, 96)
    ignored = set(ignored_transforms)
    origin = np.zeros(3, np.float32)
    if tiled:
        marker = data.find(struct.pack('<4f', 1, 1, 1, 0))
        if marker < 0:
            raise ValueError('Tiled collision origin missing; refusing guessed alignment')
        origin = np.array(struct.unpack_from('<3f', data, checked(data, marker+24, 12)), np.float32)
        if not np.isfinite(origin).all() or np.max(np.abs(origin)) > 100000:
            raise ValueError('Invalid collision tile origin')
    for tag in tagfiles(data):
        if tag.root == 'hknpMeshShape':
            tr, ids = tag.shape()
            batches = [tr+origin]
        elif tag.root == 'hknpCompoundShape':
            batches = []
            for i, tr, ids in tag.instances():
                p = tag.instance_offset+i*64
                transform = tuple(round(float(v), 3) for v in (*tag.unpack('<3f', p+16), *tag.unpack('<3f', p+32)))
                if transform not in ignored:
                    batches.append(tr)
        else:
            continue
        for tr in batches:
            # Meshes contain sentinel/degenerate primitives outside the world range.
            # Drop those individual faces, preserving the remaining shape.
            valid = np.all(np.isfinite(tr) & (np.abs(tr) < 100000), axis=(1, 2))
            yield np.asarray(tr[valid], np.float32)
