"""Persistent, revision-tagged location bookmarks. No guest memory writes."""
import json
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def validate_pose(pose):
    if not isinstance(pose, dict):
        raise ValueError('Location must be an object')
    result = dict(pose)
    for field in ('position', 'rotation'):
        value = pose.get(field)
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ValueError(f'{field} needs three coordinates')
        if any(type(x) not in (int, float) or not math.isfinite(x) or abs(x) > 1_000_000 for x in value):
            raise ValueError('Location coordinates must be finite and within world bounds')
        result[field] = list(map(float, value))
    if not isinstance(pose.get('banc'), str) or not pose['banc'] or len(pose['banc']) > 128:
        raise ValueError('Location needs an area identifier')
    if pose.get('age') not in ('Child', 'Adult'):
        raise ValueError('Location needs the player age')
    return result


class LocationStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else ROOT / 'locations.json'

    def read(self):
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if data.get('version') != 1 or not isinstance(data.get('locations'), list):
            raise ValueError('Unsupported location library; original file was preserved')
        rows = data['locations']
        for row in rows:
            if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key]
                                              for key in ('id', 'name', 'game_revision')) or 'pose' not in row:
                raise ValueError('Invalid location library entry; original file was preserved')
        return [dict(row, pose=validate_pose(row['pose'])) for row in rows]

    def save(self, name, pose, revision):
        name = name.strip()
        if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
            raise ValueError('Give this location a name of 1–80 characters')
        if not revision or not isinstance(revision, str):
            raise ValueError('Game revision is required')
        row = {'id': uuid.uuid4().hex, 'name': name, 'pose': validate_pose(pose),
               'game_revision': revision, 'created_utc': datetime.now(timezone.utc).isoformat()}
        rows = self.read()
        rows.append(row)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('x', encoding='utf-8') as stream:
                json.dump({'version': 1, 'locations': rows}, stream, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return row


def presets():
    """Named entry points extracted from this dump; availability is validated by transport."""
    return json.loads((ROOT / 'teleport-presets.json').read_text(encoding='utf-8'))['areas']
