"""Validate a public release ZIP from a new extraction; optional local NUP setup."""
import argparse,hashlib,json,subprocess,zipfile
from datetime import datetime
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path)
    parser.add_argument('--nup',type=Path)
    args=parser.parse_args()
    archive=args.archive.resolve()
    root=archive.parent/('verify-'+archive.stem+'-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    root.mkdir(exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name in z.namelist():assert (root/name).resolve().is_relative_to(root.resolve())
        prefix=z.namelist()[0].split('/')[0]+'/'
        rows=json.loads(z.read(prefix+'package-files.json'))
        assert len(rows)+1==len(z.namelist())
        for row in rows:
            data=z.read(prefix+row['path'])
            assert len(data)==row['size'] and hashlib.sha256(data).hexdigest()==row['sha256'],row['path']
            p=Path(row['path'])
            assert p.name not in ('prod.keys','title.keys','settings.json','session.json','live-binding.json')
            assert p.suffix.lower() not in ('.sav','.nup','.nsp','.xci','.ainb','.zs','.pdb')
        metadata=json.loads(z.read(prefix+'portable-package.json'))
        profile=json.loads(z.read(prefix+'emulator-profile.json'))
        if metadata['variant']=='mainline':assert not profile.get('files') and not profile.get('environment') and not profile.get('configuration')
        icons=json.loads(z.read(prefix+'editor/assets/icons/manifest.json'))
        assert all(r['kind']=='original-label' for r in icons['icons'])
        z.extractall(root)
    package=root/prefix.rstrip('/')
    python=package/'python/python.exe';script=package/'portable.py'
    def run(*extra):
        r=subprocess.run([str(python),str(script),*extra],cwd=package,capture_output=True,text=True,timeout=90)
        if r.returncode:raise RuntimeError(r.stderr or r.stdout)
        return r.stdout.strip()
    self_check=run('self-check')
    setup='not requested'
    if args.nup:
        keys=root/'nonsecret-placeholder-keys';keys.mkdir()
        for name in ('prod.keys','title.keys'):(keys/name).write_text('nonsecret validation placeholder\n')
        run('setup','--nup',str(args.nup.resolve()),'--keys-dir',str(keys))
        run('check');setup='passed with real local NUP and nonsecret placeholder keys; no game launched'
    report=dict(archive=archive.name,sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),bytes=archive.stat().st_size,
        variant=metadata['variant'],debug_source_commit=metadata['debug_source_commit'],emulator_sha256=metadata['emulator_sha256'],
        zip_crc='passed',manifest_hashes='all passed',embedded_runtime=self_check,nup_setup=setup,
        original_generated_badges=True,game_files_keys_personal_saves_in_archive=False,gameplay='not tested by this check')
    archive.with_suffix('.validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
