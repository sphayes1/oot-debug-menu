"""Revision-pinned collectible locations and narrowly scoped bean planting."""
import json,struct,uuid
from pathlib import Path
from teleport import TeleportTransport

ROOT=Path(__file__).resolve().parent
CATALOG=json.loads((ROOT/'collectibles.json').read_text(encoding='utf-8'))
BEANS={row['id']:row for row in CATALOG['beans']}


def destination(row,age):
    variants=row['variants']
    matching=[p for p in variants if p['age']==age]
    # Prefer the area's matching-era asset when both contain this placement.
    matching.sort(key=lambda p:('_Alternative' in p['banc'],('_Adult' in p['banc'] and age=='Child') or ('_Child' in p['banc'] and age=='Adult')))
    selected=(matching or variants)[0]
    return {k:selected[k] for k in ('banc','age','position','rotation','rotation_units','entry')}


class BeanState:
    def __init__(self,binding):
        self.binding=binding
        self.client=binding.client

    def view(self):
        self.binding.validate()
        if self.binding.schema['source_sha256']!=CATALOG['source_sha256']:
            raise ValueError('Bean catalog belongs to another game revision')
        values={}
        for key,row in BEANS.items():
            flag=row['plant_flag']
            if self.binding.indices['Bool'].get(flag['hash'])!=flag['index']:
                raise ValueError('Bean flag schema changed; reconnect')
            _,raw=self.binding.object(flag['hash'],'Bool')
            if raw[22] not in (0,1) or raw[23] not in (0,1):
                raise ValueError('Bean state is updating; wait for gameplay')
            values[key]=bool(raw[22])
        return values

    def plant(self,ids):
        if (not isinstance(ids,(list,tuple)) or not ids or
                any(not isinstance(key,str) or key not in BEANS for key in ids) or len(set(ids))!=len(ids)):
            raise ValueError('Choose unique bean patches from this catalog')
        scene=TeleportTransport(self.binding)
        scene.validate()
        before=self.view();origin=scene.fields.capture()
        pending=[key for key in ids if not before[key]]
        refresh=any(any(p['banc']==origin['banc'] for p in BEANS[key]['variants']) for key in pending)
        if refresh:scene.validate(age_reload=True)
        # Verify all exact full-hash/index pairs against the live lookup table
        # before publishing even the first plant flag.
        h=self.client.read(self.binding.bool_desc['address'],40)
        table=self.binding.read_chunks(struct.unpack_from('<Q',h,24)[0],struct.unpack_from('<I',h,36)[0]*8)
        writes=[]
        for key in pending:
            flag=BEANS[key]['plant_flag']
            if struct.pack('<II',int(flag['hash'],16),flag['index']) not in table:
                raise ValueError('Runtime bean flag lookup differs from the catalog')
            address,raw=self.binding.object(flag['hash'],'Bool')
            if raw[22:24]!=b'\0\0':raise ValueError('Bean state changed during preparation; refresh')
            old=struct.unpack_from('<I',raw,20)[0]
            writes.append(dict(id=key,address=address+20,expected=old,value=(old&0xffff)|0x01010000))
        path=ROOT/'runtime/bean-audits'/(uuid.uuid4().hex+'.json');path.parent.mkdir(parents=True,exist_ok=True)
        audit=dict(session=self.binding.session_id,requested=list(ids),origin=origin,state='prepared',
                   before=before,writes=writes,completed=[],automatic_retry=False,refresh_area=refresh)
        def save():path.write_text(json.dumps(audit,indent=2)+'\n',encoding='utf-8')
        try:
            save()
            for row in writes:
                self.binding.validate()
                self.binding.last_edit=None
                # These eleven independent, monotonic plant flags are not rolled
                # back after the game may already have reacted. Partial results
                # remain in the audit; the user can inspect before another action.
                audit['state']='writing';save()
                scene._cas(row)
                audit['completed'].append(row['id']);save()
            if refresh and writes:
                audit['state']='refreshing-area';save()
                audit['reload']=scene.warp(origin,CATALOG['source_sha256'],allow_any_era=True)
            audit.update(state='applied',after=self.view())
            return audit
        except Exception as exc:
            audit.update(state='partial-or-uncertain-no-retry',error=str(exc))
            raise
        finally:save()
