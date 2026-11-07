"""Guarded one-shot request for the original native equipment refresh action."""
import json
import struct
import time
import uuid
from teleport import TeleportTransport, ROOT, MOD

REQUEST = '2884dfbb'  # DebugParam.IsOverturnTerrainSetupAndLoadBanc in this debug module.


class EquipmentSync:
    def __init__(self, binding):
        self.binding = binding
        self.client = binding.client
        self.scene = TeleportTransport(binding)
        self.published = False

    def validate(self):
        self.scene.validate()
        if json.loads((MOD/'manifest.json').read_text(encoding='utf-8')).get('equipment_sync_protocol') != 1:
            raise ValueError('Launch the updated debug game before changing ocarinas')
        b=self.binding
        header=self.client.read(b.bool_desc['address'],40)
        lookup=struct.unpack_from('<Q',header,24)[0]
        capacity=struct.unpack_from('<I',header,36)[0]
        table=b.read_chunks(lookup,capacity*8)
        if struct.pack('<II',int(REQUEST,16),b.indices['Bool'][REQUEST]) not in table:
            raise ValueError('Equipment request hash/index differs from this revision')
        if self.scene.boolean(REQUEST):
            raise ValueError('An equipment refresh is pending; wait before editing again')

    def request(self, timeout=8):
        self.validate()
        address,raw=self.binding.object(REQUEST,'Bool')
        if raw[22]!=0:
            raise ValueError('Another equipment refresh started')
        old=struct.unpack_from('<I',raw,20)[0]
        path=ROOT/'runtime/equipment-sync-audits'/(uuid.uuid4().hex+'.json')
        path.parent.mkdir(parents=True,exist_ok=True)
        audit=dict(session=self.binding.session_id,state='prepared',address=address+20,
                   expected=old,value=old|0x10000,automatic_retry=False)
        def save():path.write_text(json.dumps(audit,indent=2)+'\n')
        try:
            save()
            self.published=True  # A lost CAS response must never cause rollback/replay.
            self.scene._cas(dict(address=address+20,expected=old,value=old|0x10000))
            audit['state']='requested';save()
            end=time.monotonic()+timeout
            while time.monotonic()<end:
                self.binding.validate()
                if not self.scene.boolean(REQUEST):
                    present=self.client.status()['presents']
                    while time.monotonic()<end:
                        if self.client.status()['presents']>=present+2:
                            audit['state']='acknowledged'
                            return audit
                        time.sleep(.015)
                    break
                time.sleep(.025)
            raise TimeoutError('Equipment refresh did not finish. Inspect the game; no automatic retry.')
        except Exception as exc:
            audit.update(state='uncertain-no-retry' if self.published else 'refused',error=str(exc))
            raise
        finally:save()
