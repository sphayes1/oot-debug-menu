"""Read-only NUP v1 index and selective verified extraction."""
import argparse
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct

import zstandard as zstd

DEFAULT_SOURCE = Path.home() / 'Downloads/The Legend of Zelda Ocarina of TIme [04004860224DEC000].nup'
MAX_MEMBER = 256 * 1024 * 1024
MAX_OUTPUT = 1024 * 1024 * 1024


class Nup:
    def __init__(self, path=DEFAULT_SOURCE):
        self.path = Path(path)
        self.length = self.path.stat().st_size
        with self.path.open('rb') as f:
            h = f.read(128)
            if len(h) != 128 or h[:4] != b'NUP\x01':
                raise ValueError('Not NUP v1')
            hs, hv = struct.unpack_from('<HH', h, 4)
            off, size = struct.unpack_from('<QQ', h, 8)
            self.blob, expected, pc, flags = struct.unpack_from('<QQII', h, 56)
            if (hs < 128 or hv != 1 or off != hs or flags or pc < 1 or
                    expected != self.length or self.blob % 16 or
                    off + size > self.blob or self.blob > self.length or size > MAX_MEMBER):
                raise ValueError('Invalid superblock bounds/version')
            f.seek(off)
            self.t = f.read(size)
        self.toc_hash = hashlib.sha256(self.t).hexdigest()
        if bytes.fromhex(self.toc_hash) != h[24:56]:
            raise ValueError('TOC hash mismatch')
        if self.t[:4] != b'TOC\x01' or self.u32(4) != pc:
            raise ValueError('Invalid TOC')
        self.dc, self.fc, self.pool, pool_size, reserved = struct.unpack_from('<QQQQQ', self.t, 8)
        self.db = 48 + pc * 64
        self.fb = self.db + self.dc * 24
        self.cb = self.fb + self.fc * 80
        if (reserved or self.cb > self.pool or self.pool + pool_size > len(self.t)
                or any(self.t[self.pool + pool_size:])):
            raise ValueError('Invalid TOC array bounds')
        self.pool_size = pool_size
        self.packages = []
        for i in range(pc):
            p = 48 + i * 64
            tid, root, exefs, romfs, version, kind, pf = struct.unpack_from('<QIIIIBB', self.t, p)
            if root >= self.dc or kind >= 5:
                raise ValueError('Invalid package')
            self.packages.append(dict(title_id=f'{tid:016X}', root=root, exefs=exefs,
                                      romfs=romfs, version=version, kind=kind, flags=pf))
        self.files = {}
        self.visited = set()
        for pkg in self.packages:
            self.walk(pkg['root'], '')

    def u32(self, p):
        return struct.unpack_from('<I', self.t, p)[0]

    def name(self, p):
        off, size = struct.unpack_from('<II', self.t, p)
        if off + size > self.pool_size:
            raise ValueError('String outside pool')
        n = self.t[self.pool + off:self.pool + off + size].decode('utf-8')
        if n in ('.', '..') or any(c in n for c in ('/', '\\', ':', '\0')):
            raise ValueError('Unsafe node name')
        return n

    def walk(self, d, parent):
        if d in self.visited or d >= self.dc:
            raise ValueError('Repeated/invalid directory')
        self.visited.add(d)
        pos = self.db + d * 24
        n = self.name(pos)
        prefix = parent + n + '/' if n else parent
        first, count = struct.unpack_from('<II', self.t, pos + 8)
        if self.cb + (first + count) * 4 > self.pool:
            raise ValueError('Invalid children bounds')
        for k in range(first, first + count):
            node = self.u32(self.cb + k * 4)
            if node < self.dc:
                self.walk(node, prefix)
            else:
                idx = node - self.dc
                if idx >= self.fc:
                    raise ValueError('Invalid file node')
                fp = self.fb + idx * 80
                path = prefix + self.name(fp)
                size, off, stored = struct.unpack_from('<QQQ', self.t, fp + 8)
                codec = self.t[fp + 64]
                if codec not in (0, 1) or (codec == 0 and size != stored):
                    raise ValueError('Unsupported/invalid codec')
                if size and (off < self.blob or off % 16 or off + stored > self.length):
                    raise ValueError('Extent outside blob')
                if not size and (off or stored or codec):
                    raise ValueError('Invalid empty member')
                if path in self.files:
                    raise ValueError('Duplicate member path')
                self.files[path] = dict(path=path, size=size, offset=off, stored=stored,
                                        codec=codec, sha256=self.t[fp + 32:fp + 64].hex())

    def read(self, member):
        entry = self.files[member]
        if max(entry['size'], entry['stored']) > MAX_MEMBER:
            raise ValueError('Member exceeds 256 MiB selective-extraction limit')
        with self.path.open('rb') as f:
            f.seek(entry['offset'])
            raw = f.read(entry['stored'])
        if len(raw) != entry['stored']:
            raise ValueError('Truncated extent')
        if entry['codec'] == 1 and zstd.get_frame_parameters(raw).content_size != entry['size']:
            raise ValueError('Zstandard content size differs from member size')
        data = raw if entry['codec'] == 0 else zstd.ZstdDecompressor().decompress(raw, max_output_size=MAX_MEMBER)
        if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('Member size/hash mismatch')
        return data

    def extract(self, member, destination):
        root = Path(destination).resolve()
        rel = PurePosixPath(member)
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError('Unsafe member path')
        target = root.joinpath(*rel.parts).resolve()
        if not target.is_relative_to(root) or target == self.path.resolve():
            raise ValueError('Unsafe extraction destination')
        existing = sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) if root.exists() else 0
        if existing + self.files[member]['size'] > MAX_OUTPUT:
            raise ValueError('Extraction exceeds 1 GiB limit')
        data = self.read(member)
        if target.exists() and target.read_bytes() != data:
            raise ValueError('Refusing to overwrite different original')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    sub = p.add_subparsers(dest='command', required=True)
    listing = sub.add_parser('list')
    listing.add_argument('--match', default='.*')
    listing.add_argument('--csv', type=Path)
    extract = sub.add_parser('extract')
    extract.add_argument('member')
    extract.add_argument('--out', type=Path, default=Path(__file__).resolve().parents[1] / 'originals')
    sub.add_parser('info')
    a = p.parse_args()
    n = Nup(a.source)
    if a.command == 'info':
        print(json.dumps(dict(source=str(n.path), size=n.length, toc_sha256=n.toc_hash,
                              packages=n.packages, files=len(n.files), directories=n.dc), indent=2))
    elif a.command == 'extract':
        print(n.extract(a.member, a.out))
    else:
        rows = [v for k, v in sorted(n.files.items()) if re.search(a.match, k, re.I)]
        if a.csv:
            with a.csv.open('w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=['path', 'size', 'offset', 'stored', 'codec', 'sha256'])
                w.writeheader()
                w.writerows(rows)
            print(f'Wrote {len(rows)} records: {a.csv}')
        else:
            print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
