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
    screenshot_manifest=ROOT/'docs/screenshots/manifest.json'
    screenshots=json.loads(screenshot_manifest.read_text()) if screenshot_manifest.exists() else {'screenshots':[]}
    screenshot_hashes={row['file']:row['sha256'] for row in screenshots['screenshots']}
    for relative in paths:
        is_screenshot=relative.parent==Path('docs/screenshots') and relative.name in screenshot_hashes
        assert relative.suffix.lower() not in blocked or is_screenshot,str(relative)
        assert not {'runtime','backups','live-edits','tests-local','checkpoints','profiling','emulators'} & set(relative.parts),str(relative)
        assert relative.name not in ('settings.json','live-binding.json','session.json','hotkeys.json','controller-hotkeys.json','locations.json'),str(relative)
        data=(ROOT/relative).read_bytes();size+=len(data)
        if is_screenshot:
            assert data.startswith(b'\x89PNG\r\n\x1a\n') and len(data)<1_000_000,str(relative)
            assert hashlib.sha256(data).hexdigest()==screenshot_hashes[relative.name],str(relative)
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
    compatibility_path='src/video_core/engines/kepler_compute.cpp'
    assert len(current_paths)==6 and all(p==compatibility_path or p.startswith(('src/core/debugger/','src/core/hle/kernel/k_light_lock.')) for p in current_paths)
    compatibility=current.split('--- a/'+compatibility_path+'\n',1)[1]
    removed=[line[1:] for line in compatibility.splitlines() if line.startswith('-') and not line.startswith('---')]
    added=[line[1:] for line in compatibility.splitlines() if line.startswith('+') and not line.startswith('+++')]
    assert len(removed)==7 and added==[re.sub(r'\bstate\b','bypass_state',line) for line in removed]
    controller=json.loads((ROOT/'emulator-bridge/controller-provenance.json').read_text())
    controller_paths={'src/core/debugger/nx2_debug_tools.cpp','src/core/debugger/nx2_debug_server.cpp',
                      'src/hid_core/frontend/emulated_controller.cpp','src/hid_core/frontend/debug_controller.h'}
    for variant in ('optimized','mainline'):
        text=(ROOT/('emulator-bridge/controller-'+variant+'.patch')).read_text(encoding='utf-8')
        assert hashlib.sha256(text.encode()).hexdigest()==controller[variant]['patch_sha256']
        assert set(re.findall(r'^\+\+\+ b/(.+)$',text,re.M))==controller_paths
        assert {row['path'] for row in controller[variant]['files']}==controller_paths
        added='\n'.join(line[1:] for line in text.splitlines() if line.startswith('+') and not line.startswith('+++'))
        assert 'Nx2Sampler' not in added and 'RequestGpuRead' not in added
    print(json.dumps(dict(tracked_files=len(paths),tracked_bytes=size,source_boundary_audit='passed',
        catalogue_hash='passed',debug_bridge_changed_files=len(changed),controller_addons='four debug/HID files each; hashes passed'),indent=2))

if __name__=='__main__':main()
