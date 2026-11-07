"""Apply source-checked overrides supplied by an external emulator profile."""
import base64,hashlib,json
from pathlib import Path

def apply_profile(nup,spec_path,destination):
    spec=json.loads(Path(spec_path).read_text(encoding='utf-8'))
    if spec['variant']=='mainline' and (spec.get('files') or spec.get('environment') or spec.get('configuration')):
        raise ValueError('Mainline profile must not contain custom performance overrides')
    root=Path(destination).resolve();results=[]
    for row in spec.get('files',[]):
        if 'member' in row:
            before=nup.read(row['member'])
            if hashlib.sha256(before).hexdigest()!=row['source_sha256']:raise ValueError('Profile source member changed')
            output=bytearray()
            for op in row['ops']:
                if 'copy' in op:
                    offset,size=op['copy']
                    if offset<0 or size<0 or offset+size>len(before):raise ValueError('Invalid profile copy range')
                    output.extend(before[offset:offset+size])
                else:output.extend(base64.b64decode(op['data'],validate=True))
            data=bytes(output)
        else:data=base64.b64decode(row['data'],validate=True)
        if hashlib.sha256(data).hexdigest()!=row['result_sha256']:raise ValueError('Profile output hash mismatch')
        target=(root/row['output']).resolve()
        if not target.is_relative_to(root):raise ValueError('Profile escaped its mod directory')
        results.append((target,data))
    for target,data in results:
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    return len(results)
