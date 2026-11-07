"""Generate debug-only game overrides from the user's revision-checked NUP."""
import argparse,base64,hashlib,json,sys
from pathlib import Path
import zstandard
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'editor')]
from nup import Nup
from assets import Assets

def sha(data):return hashlib.sha256(data).hexdigest()
def build_mod(nup,output):
    spec=json.loads((ROOT/'mods/recipes.json').read_text())
    if nup.toc_hash!=spec['nup_toc_sha256']:raise ValueError('Unsupported NUP revision; no files written.')
    assets=Assets(nup);results={}
    manifest=json.loads((ROOT/'mods/manifest.json').read_text())
    if sha(nup.read('exefs/main'))!=manifest['original_main_sha256']:
        raise ValueError('Game executable revision is unsupported')
    for row in spec['files']:
        raw=nup.read(row['member'])
        if sha(raw)!=row['source_sha256']:raise ValueError('Original member hash mismatch: '+row['member'])
        before=assets.decode(raw) if row['decoded'] else raw
        if sha(before)!=row['decoded_source_sha256']:raise ValueError('Decoded source hash mismatch')
        after=bytearray()
        for operation in row['ops']:
            if 'copy' in operation:
                offset,size=operation['copy']
                if offset<0 or size<0 or offset+size>len(before):raise ValueError('Invalid recipe range')
                after.extend(before[offset:offset+size])
            else:after.extend(base64.b64decode(operation['data'],validate=True))
        if sha(after)!=row['decoded_result_sha256']:raise ValueError('Patched member hash mismatch')
        data=zstandard.ZstdCompressor(level=3).compress(after) if row['decoded'] else bytes(after)
        if sha(data)!=row['result_sha256']:raise ValueError('Encoded member hash mismatch')
        results[row['member']]=data
    for p in (ROOT/'mods/exefs').glob('*.ips'):results['exefs/'+p.name]=p.read_bytes()
    if {k:sha(v) for k,v in results.items()}!={k.replace('\\','/'):v for k,v in manifest['files'].items()}:
        raise ValueError('Debug module output does not match the accepted manifest')
    output=Path(output).resolve()
    for name,data in results.items():
        p=(output/name).resolve()
        if not p.is_relative_to(output):raise ValueError('Unsafe module path')
        p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return results

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nup',type=Path,required=True)
    parser.add_argument('--emulator',type=Path,required=True)
    parser.add_argument('--config',type=Path,help='Optional existing SDL2 INI; rendering settings are preserved')
    a=parser.parse_args()
    import backend
    if backend.emulator_running():raise ValueError('Close the emulator before generating a debug profile.')
    emulator=a.emulator.resolve(strict=True);nup=Nup(a.nup.resolve(strict=True))
    schema=json.loads((ROOT/'editor/live-schema.json').read_text())
    verification=nup.read(schema['source_member'])
    if sha(verification)!=schema['source_sha256']:raise ValueError('GameData revision is unsupported')
    output=ROOT/'editor/runtime/load/0400486024DEC000/Debug Teleport (test)'
    build_mod(nup,output)
    target=ROOT/'editor/runtime/verification'/schema['source_member']
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(verification)
    settings=dict(nup=str(a.nup.resolve()),nup_toc_sha256=nup.toc_hash,emulator=str(emulator),
        emulator_sha256=sha(emulator.read_bytes()),config=str(a.config.resolve(strict=True)) if a.config else None)
    (ROOT/'settings.json').write_text(json.dumps(settings,indent=2)+'\n')
    from prepare_data import prepare
    prepare()
    print('Debug-only profile generated. Configure keys in your emulator separately, then run Start Debug Game.cmd.')

if __name__=='__main__':main()
