"""Fixed-song ownership and guarded, native learn requests. No story flags."""
import json
import struct
import time
import uuid
from pathlib import Path
from teleport import TeleportTransport, MOD
from location_capture import LocationCapture

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT/'songs-schema.json').read_text(encoding='utf-8'))
SONGS = {row['id']: row for row in SCHEMA['songs']}
REQUEST = 'da576eaa'  # Unsaved DebugParam.IsKeepFormalFlag, redirected in debug MainUpdate.
PAYLOAD = '0b570ab2'  # Unsaved Sequence_ReservedNextStartPosName; must be idle/empty.


def string_plan(address, raw, song_id):
    if song_id not in SONGS:
        raise ValueError('Unknown fixed song')
    if (len(raw) != 264 or struct.unpack_from('<Q',raw,104)[0] != address+116 or
            struct.unpack_from('<I',raw,112)[0] != 64):
        raise ValueError('Song request string layout changed')
    if raw[116:180].split(b'\0')[0]:
        raise ValueError('Another destination or song request is pending')
    payload=song_id.encode('ascii').ljust(64,b'\0')
    plan=[]
    for offset in (*range(4,64,4),0):  # Publish complete prefix after the tail.
        old=struct.unpack_from('<I',raw,116+offset)[0]
        new=struct.unpack_from('<I',payload,offset)[0]
        if old!=new:plan.append(dict(address=address+116+offset,expected=old,value=new))
    return plan, payload


class Songs:
    def __init__(self, binding):
        self.binding=binding
        self.client=binding.client
        self.transport=TeleportTransport(binding)
        self.fields=LocationCapture(binding)

    def view(self):
        self.binding.validate()
        values={}
        for key,row in SONGS.items():
            if self.binding.indices['Bool'].get(row['hash']) != row['index']:
                raise ValueError('Song schema differs from the connected game revision')
            _,raw=self.binding.object(row['hash'],'Bool')
            if raw[22] not in (0,1) or raw[23] not in (0,1):
                raise ValueError('Song state is updating; wait for gameplay')
            values[key]=bool(raw[22])
        return values

    def validate(self):
        self.transport.validate()
        if json.loads((MOD/'manifest.json').read_text(encoding='utf-8')).get('songs_protocol')!=1:
            raise ValueError('Relaunch the updated debug game before learning songs')
        b=self.binding
        header=self.client.read(b.bool_desc['address'],40)
        lookup=struct.unpack_from('<Q',header,24)[0]
        capacity=struct.unpack_from('<I',header,36)[0]
        table=b.read_chunks(lookup,capacity*8)
        for key in (REQUEST,*(r['hash'] for r in SONGS.values())):
            if struct.pack('<II',int(key,16),b.indices['Bool'][key]) not in table:
                raise ValueError('Song runtime hash/index mismatch')
        self.view()

    def learn(self, song_ids):
        if (not isinstance(song_ids,(list,tuple)) or not song_ids or
                any(not isinstance(k,str) or k not in SONGS for k in song_ids) or
                len(set(song_ids))!=len(song_ids)):
            raise ValueError('Choose unique fixed songs to learn')
        self.validate()
        results=[]
        for key in song_ids:
            if self.view()[key]:
                results.append(dict(song=key,state='already-learned'))
            else:
                results.append(self._learn_one(key))
        return dict(state='applied',songs=results)

    def _learn_one(self, key, timeout=8):
        self.validate()
        address,raw=self.fields.object('String64',PAYLOAD)
        writes,payload=string_plan(address,raw,key)
        flag,data=self.binding.object(REQUEST,'Bool')
        if data[22]!=0:raise ValueError('A song request is pending')
        old=struct.unpack_from('<I',data,20)[0]
        completed=[];published=False
        path=ROOT/'runtime/song-audits'/(uuid.uuid4().hex+'.json')
        path.parent.mkdir(parents=True,exist_ok=True)
        audit=dict(session=self.binding.session_id,song=key,state='prepared',writes=writes,
                   automatic_retry=False,flag_address=flag+20,flag_expected=old)
        def save():path.write_text(json.dumps(audit,indent=2)+'\n')
        try:
            save()
            for row in writes:
                self.transport._cas(row);completed.append(row)
            # Refuse scene/menu changes that happened while assembling the command.
            self.validate()
            if self.client.read(address+116,64)!=payload:
                raise ValueError('Song command changed during preparation')
            self.binding.last_edit=None
            published=True  # Lost publication response must never cause replay/rollback.
            self.transport._cas(dict(address=flag+20,expected=old,value=old|0x10000))
            audit['state']='requested';save()
            end=time.monotonic()+timeout
            while time.monotonic()<end:
                self.binding.validate()
                if not self.transport.boolean(REQUEST):
                    _,value=self.binding.object(SONGS[key]['hash'],'Bool')
                    if value[22:24]!=b'\x01\x01':
                        raise ValueError('Native song request finished without granting the song')
                    # Let MainUpdate observe the cleared flag before another request.
                    present=self.client.status()['presents']
                    while self.client.status()['presents']<present+2:
                        if time.monotonic()>=end:
                            raise TimeoutError('Song learned but native branch has not reset; inspect the game')
                        time.sleep(.015)
                    if self.client.read(address+116,64)!=payload:
                        raise ValueError('Native song succeeded but command changed; inspect the game')
                    # Clear only our acknowledged payload, preserving wrapper and saved buffer.
                    for i in range(0,64,4):
                        word=struct.unpack_from('<I',payload,i)[0]
                        if word:self.transport._cas(dict(address=address+116+i,expected=word,value=0))
                    audit['state']='learned'
                    return audit
                time.sleep(.025)
            raise TimeoutError('Song request did not finish. Inspect the game; no automatic retry.')
        except Exception as exc:
            audit.update(state='uncertain-no-retry' if published else 'cancelled-before-request',error=str(exc))
            if not published:
                for row in reversed(completed):
                    try:self.client.compare_write(row['address'],row['value'],row['expected'])
                    except Exception:pass
            raise
        finally:save()
