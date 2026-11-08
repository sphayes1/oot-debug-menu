"""On-demand collision cache, built from the user's NUP without a RomFS export."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import numpy as np
import oead
import backend
from collision_geometry import EMPTY, box, capsule, cylinder, place, sphere, static_geometry, tagfiles

# Numeric IDs are part of the cache/overlay protocol. Keep stable.
KINDS = {'Terrain / baked solids': (0, (.58, .78, .87)),
         'Invisible walls': (1, (1., .24, .19)),
         'Climb / push walls': (2, (1., .62, .12)),
         'Void / reset zones': (3, (.77, .32, 1.)),
         'No-respawn zones': (4, (.1, .85, .69)),
         'Loading zones': (5, (.2, .5, 1.)),
         'Other actor walls': (6, (.95, .45, .72))}
CACHE_VERSION = 8


def plain(value):
    if isinstance(value, (dict, oead.byml.Hash)):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, oead.byml.Array)):
        return [plain(v) for v in value]
    if isinstance(value, (oead.F32, oead.F64)):
        return float(value)
    if isinstance(value, (oead.S32, oead.U32, oead.S64, oead.U64)):
        return int(value)
    return value


def byml(data):
    if len(data) < 16 or data[:2] != b'YB' or int.from_bytes(data[2:4], 'little') not in (3, 4, 7, 8):
        raise ValueError('Unsupported collision BYML version')
    data = bytearray(data); data[2:4] = b'\3\0'
    return plain(oead.byml.from_binary(data))


def nup_path():
    # Source checkout, portable release and original local installation.
    for config in (backend.ROOT.parent/'settings.json', backend.ROOT/'settings.json'):
        if config.exists():
            raw = json.loads(config.read_text(encoding='utf-8'))
            if raw.get('nup'):
                path = Path(raw['nup'])
                if not path.is_absolute():
                    path = config.parent/path
                if path.is_file():
                    return path
    from nup import DEFAULT_SOURCE
    if DEFAULT_SOURCE.is_file():
        return DEFAULT_SOURCE
    raise ValueError('Game NUP not found. Choose your NUP in the launcher, then reconnect.')


class SceneSource:
    def __init__(self, path=None):
        tools = backend.ROOT.parent/'tools'
        if not tools.is_dir():  # Original development installation.
            tools = backend.ROOT.parent/'projects/oot-debug-menu/tools'
        if str(tools) not in sys.path:
            sys.path.insert(0, str(tools))
        from nup import Nup
        from assets import Assets
        self.nup = Nup(path or nup_path())
        self.assets = Assets(self.nup)
        self.shapes = {}
        self.meshes = {}
        self.issues = []
        self.tiles = {}
        self.cache = backend.ROOT/'runtime/collision'/self.nup.toc_hash[:16]/str(CACHE_VERSION)
        self.cache.mkdir(parents=True, exist_ok=True)

    def read(self, path):
        return self.assets.decode(self.nup.read(path))

    def actor_shapes(self, name):
        if name in self.shapes:
            return self.shapes[name]
        member = 'romfs/Pack/Actor/'+name+'.pack.zs'
        result = []
        if member in self.nup.files:
            archive = oead.Sarc(self.read(member))
            files = {f.name: bytes(f.data) for f in archive.get_files()}
            def param(path, chain=()):
                key = path.removeprefix('Work/').replace('.gyml', '.bgyml')
                if key in chain or len(chain) > 32:
                    raise ValueError('Cyclic actor shape inheritance')
                if key not in files:
                    return {}
                d = byml(files[key])
                parent = param(d['$parent'], chain+(key,)) if d.get('$parent') else {}
                parent.update({k: v for k, v in d.items() if k != '$parent'})
                return parent
            actor = param('Work/Actor/'+name+'.engine__actor__ActorParam.gyml')
            physics = param(actor.get('Components', {}).get('PhysicsRef', ''))
            controllers = param(physics.get('ControllerSetPath', ''))
            result = [param(row['FilePath']) for row in controllers.get('ShapeNamePathAry', [])]
            if not result:
                result = [byml(raw) for key, raw in files.items() if 'ShapeParam' in key and key.endswith('.bgyml')]
        self.shapes[name] = result
        return result

    def shape_mesh(self, shape):
        result = []
        vector = lambda d, default=0.: [float((d or {}).get(k, default)) for k in 'XYZ']
        for row in shape.get('Box', []):
            center = np.array(vector(row.get('Center')))+vector(row.get('OffsetTranslation'))
            result.append(box(center, vector(row.get('HalfExtents'), .5)))
        for key in ('Cylinder', 'Capsule'):
            for row in shape.get(key, []):
                endpoints = np.array([vector(row.get('CenterA')), vector(row.get('CenterB'))])+vector(row.get('OffsetTranslation'))
                result.append((capsule if key == 'Capsule' else cylinder)(endpoints, float(row.get('Radius', 1))))
        for row in shape.get('Sphere', []):
            center = np.array(vector(row.get('Center')))+vector(row.get('OffsetTranslation'))
            result.append(sphere(center, float(row.get('Radius', 1))))
        for row in shape.get('PhshMesh', []):
            name = Path(row['PhshMeshPath']).name.replace('.phsh', '.Nin_Ounce_NVN2.bphsh.zs')
            member = 'romfs/Phive/Shape/Dcc/'+name
            if member not in self.meshes:
                groups = [t.shape()[0] for t in tagfiles(self.read(member))] if member in self.nup.files else []
                self.meshes[member] = np.concatenate(groups) if groups else EMPTY
            result.append(self.meshes[member])
        return np.concatenate(result) if result else EMPTY

    def selection(self, scene, center, radius):
        if not re.fullmatch(r'[A-Za-z0-9_]{1,100}', scene):
            raise ValueError('Invalid area name for collision cache')
        if scene not in self.tiles:
            pattern = re.compile(r'/'+re.escape(scene)+r'(?:_X(\d+)_Z(\d+))?\.Nin_Ounce_NVN2\.bphsc\.zs$')
            entries = []
            for path in self.nup.files:
                match = pattern.search(path) if '/StaticCompoundBody/' in path else None
                if match:
                    entries.append((path, (int(match[1]), int(match[2])) if match[1] else None))
            origin = None
            if entries and entries[0][1] is not None:
                raw = self.read(entries[0][0])
                marker = raw.find(struct.pack('<4f', 1, 1, 1, 0))
                if marker < 0:
                    raise ValueError('Collision tile origin unavailable')
                x, _, z = struct.unpack_from('<3f', raw, marker+24)
                origin = (x-250*entries[0][1][0], z-250*entries[0][1][1])
            self.tiles[scene] = entries, origin
        entries, origin = self.tiles[scene]
        if origin is None:
            return scene, [p for p, _ in entries]
        x, _, z = center
        radius = min(500., max(10., radius))
        selected = []
        for path, (tx, tz) in entries:
            ox, oz = origin[0]+tx*250, origin[1]+tz*250
            distance = max(ox-x, 0., x-ox-250)**2 + max(oz-z, 0., z-oz-250)**2
            if distance <= (radius+30)**2:  # Prefetch margin at tile boundaries.
                selected.append((path, tx, tz))
        suffix = hashlib.sha256(json.dumps([(x, z) for _, x, z in selected]).encode()).hexdigest()[:12]
        return scene+'__'+suffix, [p for p, _, _ in selected]

    def build(self, scene, progress=None, center=(0., 0., 0.), radius=100.):
        key, members = self.selection(scene, center, radius)
        dest = self.cache/(key+'.npz')
        if dest.is_file():
            return self.describe(dest)
        self.issues = []
        roots = [byml(self.read(p)) for p in self.nup.files if '/Banc/' in p and Path(p).name in
                 (scene+'_Static.bcett.byml.zs', scene+'_Dynamic.bcett.byml.zs')]
        ignored = {tuple(round(float(v), 3) for v in (*a.get('Translate', (0, 0, 0)), *a.get('Scale', (1, 1, 1))))
                   for root in roots for a in root.get('Actors', []) if any(word in a.get('Gyaml', '')
                   for word in ('AirWall', 'Airwall', 'Area', 'Anchor', 'Camera', 'Sensor'))}
        chunks, categories = [], []
        entries, origin = self.tiles[scene]
        selected_indices = [key for p, key in entries if p in members and key is not None]
        bounds = None
        if origin is not None and selected_indices:
            indices = np.asarray(selected_indices)
            bounds = (np.asarray(origin)+indices.min(axis=0)*250-30,
                      np.asarray(origin)+(indices.max(axis=0)+1)*250+30)
        def add(triangles, kind):
            if not len(triangles):
                return
            valid = np.all(np.isfinite(triangles) & (np.abs(triangles) < 100000), axis=(1, 2))
            if bounds is not None:
                horizontal = triangles[:, :, (0, 2)]
                valid &= np.all(horizontal.max(axis=1) >= bounds[0], axis=1) & np.all(horizontal.min(axis=1) <= bounds[1], axis=1)
            triangles = triangles[valid]
            if not len(triangles):
                return
            chunks.append(np.asarray(triangles, np.float32))
            categories.append(np.full(len(triangles), kind, np.uint8))
            if sum(len(c) for c in chunks) > 4_000_000:
                raise ValueError('Area exceeds collision display limit')
        for i, member in enumerate(members):
            if progress:
                progress(f'Loading collision tile {i+1}/{len(members)}')
            try:
                for tr in static_geometry(self.read(member), bool(re.search(r'_X\d+_Z\d+\.', member)), ignored):
                    # Global material/owner indices do not consistently follow TAG0
                    # array order. Keep baked surfaces neutral; only actor shapes
                    # identified by name below are classified as invisible walls.
                    add(tr, 0)
            except (ValueError, KeyError, IndexError, struct.error) as exc:
                self.issues.append(Path(member).name+': '+str(exc))
        for root in roots:
            actors = {int(a['Hash']): a for a in root.get('Actors', [])}
            for actor in actors.values():
                name = actor.get('Gyaml', '')
                if 'AirWall' not in name and 'Airwall' not in name:
                    continue
                kind = 2 if 'Climb' in name or 'Push' in name else 6 if any(s in name for s in ('Enemy', 'Horse', 'Animal', 'Cucco', 'Npc', 'Camera', 'Lure', 'Bomb', 'Hookshot', 'Sight', 'HitTarget', 'ObjectAndSmall')) else 1
                try:
                    for shape in self.actor_shapes(name):
                        add(place(self.shape_mesh(shape), actor), kind)
                except (ValueError, KeyError, IndexError) as exc:
                    self.issues.append(name+': '+str(exc))
            for group in root.get('AiGroups', []):
                logic = group.get('Logic', '')
                if 'FallDown_Item' in logic:
                    continue
                kind = (5 if 'FieldDungeonEntranceSet' in logic else 3 if any(s in logic for s in ('FallDown', 'Whirlpool')) else 4 if 'InvalidateRestartArea' in logic else None)
                if kind is None:
                    continue
                for ref in group.get('References', []):
                    actor = actors.get(int(ref.get('Reference', 0)))
                    if not actor or actor.get('Gyaml') != 'Area':
                        continue
                    shape = actor.get('Dynamic', {}).get('RigidBodyShapeType', 1)
                    local = sphere() if shape == 0 else cylinder(((0, 0, 0), (0, 1, 0))) if shape == 3 else box((0, .5, 0))
                    add(place(local, actor), kind)
        triangles = np.concatenate(chunks) if chunks else EMPTY
        kinds = np.concatenate(categories) if categories else np.empty(0, np.uint8)
        if not len(triangles):
            raise ValueError('No supported collision geometry found for '+scene)
        metadata = dict(scene=scene, key=key, tiles=len(members), source_toc=self.nup.toc_hash, version=CACHE_VERSION,
                        triangles=len(triangles), counts=dict(Counter(map(int, kinds))), issues=self.issues,
                        note='Authored static collision; moved actors and runtime-enabled state are not tracked.')
        # Atomic cache publication; only the generated local file is shared with the renderer.
        temp = dest.with_suffix('.tmp')
        with temp.open('wb') as file:
            np.savez_compressed(file, triangles=triangles, kinds=kinds, metadata=json.dumps(metadata))
        temp.replace(dest)
        return dict(path=str(dest.resolve()), **metadata)

    @staticmethod
    def describe(path):
        with np.load(path, allow_pickle=False) as data:
            metadata = json.loads(str(data['metadata']))
        return dict(path=str(path.resolve()), **metadata)
