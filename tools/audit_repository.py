"""Check tracked source boundaries before committing or publishing."""
import gzip,hashlib,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    paths=[Path(n) for n in names if n]
    blocked={'.keys','.nup','.nsp','.xci','.sav','.exe','.dll','.pdb','.png','.ainb','.zs','.sqlite3'}
    secret=re.compile(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----|github_pat_[A-Za-z0-9_]{40,}|gh[pousr]_[A-Za-z0-9]{25,}')
    size=0
    for relative in paths:
        assert relative.suffix.lower() not in blocked,str(relative)
        assert not {'runtime','backups','live-edits','tests-local','checkpoints','profiling','emulators'} & set(relative.parts),str(relative)
        assert relative.name not in ('settings.json','live-binding.json','session.json','hotkeys.json','locations.json'),str(relative)
        data=(ROOT/relative).read_bytes();size+=len(data)
        assert not secret.search(data),'Credential-like content in '+str(relative)
    receipt=json.loads((ROOT/'data/actor-catalog.json').read_text())
    assert hashlib.sha256(gzip.decompress((ROOT/'data/actor-catalog.sqlite3.gz').read_bytes())).hexdigest()==receipt['sha256']
    patch=(ROOT/'emulator-bridge/oot-debug-writes.patch').read_text(encoding='utf-8')
    changed=re.findall(r'^\+\+\+ b/(.+)$',patch,re.M)
    allowed=('src/core/debugger/','src/core/hle/kernel/k_light_lock.','src/hid_core/frontend/emulated_controller.')
    assert len(changed)==10 and all(p.startswith(allowed) for p in changed),changed
    additions='\n'.join(line[1:] for line in patch.splitlines() if line.startswith('+') and not line.startswith('+++'))
    assert 'Nx2Sampler' not in additions and 'RequestGpuRead' not in additions
    current=(ROOT/'emulator-bridge/mainline117-guarded-writer.patch').read_text(encoding='utf-8')
    current_paths=re.findall(r'^\+\+\+ b/(.+)$',current,re.M)
    assert len(current_paths)==5 and all(p.startswith(('src/core/debugger/','src/core/hle/kernel/k_light_lock.')) for p in current_paths)
    print(json.dumps(dict(tracked_files=len(paths),tracked_bytes=size,source_boundary_audit='passed',
        catalogue_hash='passed',debug_bridge_changed_files=len(changed)),indent=2))

if __name__=='__main__':main()
