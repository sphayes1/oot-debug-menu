"""Active Player MP binding; one current-value CAS, no capacity or queue writes."""
import json
import struct
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class PlayerMagicBindings:
    def __init__(self, player_life, audit_dir=None):
        self.life = player_life
        self.bindings = player_life.bindings
        self.client = self.bindings.client
        self.audit_dir = Path(audit_dir) if audit_dir else ROOT/'runtime/player-magic-audits'
        self.connected = False

    @staticmethod
    def u64(data, offset=0):
        return struct.unpack_from('<Q', data, offset)[0]

    def _candidate(self, idle=False):
        life = self.life._guard()
        owner, context = life['owner'], life['context']
        if not self.life.in_heap(context, 0x360):
            raise ValueError('Player magic context is outside the game heap')
        component = self.u64(self.client.read(context+0x358, 8))
        if component % 8 or not self.life.in_heap(component, 0x1c78):
            raise ValueError('Player magic component is outside the game heap')
        header = self.client.read(component, 0x20)
        if (self.u64(header) != self.life.module_base+0x4b4dfc0 or
                self.u64(header, 0x18) != owner):
            raise ValueError('Player magic component type/owner mismatch')
        owned = self.client.read(component+0x1b78, 0x68)
        if (self.u64(owned) != self.life.module_base+0x4b633f0 or
                struct.unpack_from('<II', owned, 0x38) != (0x76b18200,0x12d63a97)):
            raise ValueError('Player-owned MP type or hashes mismatch')
        if self.bindings.enhancements is None:
            raise ValueError('Connect enhancement GameData before player magic')
        maximum = self.bindings.enhancements.view()['MPMax']
        current = struct.unpack_from('<I', owned, 0x44)[0]
        pending = struct.unpack_from('<i', owned, 0x18)[0]
        flags = struct.unpack_from('<I', owned, 0x10)[0]
        if type(maximum) is not int or maximum not in (0,24,48) or not 0 <= current <= maximum:
            raise ValueError('Player magic current/capacity is outside the reviewed range')
        if idle and (pending != 0 or flags & 3):
            raise ValueError('Player magic has a pending change or disabled value; no write sent')
        return dict(component=component, owner=owner, context=context,
                    address=component+0x1bbc, current=current, maximum=maximum,
                    pending_delta=pending, flags=flags)

    def bind(self):
        self.connected = False
        self.life._capability()
        candidate = self._candidate()
        self.session_id = tuple(self.bindings.session_id)
        self.module_base = self.life.module_base
        self.bound = candidate
        self.connected = True
        return self.read()

    def _guard(self, capability=False, idle=False):
        if capability:
            self.life._capability()
        if (not self.connected or tuple(self.bindings.session_id) != self.session_id or
                self.life.module_base != self.module_base):
            raise ValueError('Player magic session changed; connect again')
        candidate = self._candidate(idle=idle)
        if any(candidate[key] != self.bound[key] for key in ('component','owner','context','address')):
            raise ValueError('Player magic owner changed; connect again')
        return candidate

    def read(self):
        value = self._guard()
        return dict(current=value['current'], maximum=value['maximum'], session=self.session_id,
                    current_edit_supported=True, capacity_edit_supported=False)

    def _save(self, path, receipt):
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(receipt,indent=2)+'\n')
        temporary.replace(path)

    def write_current(self, expected, value):
        if any(type(n) is not int or not 0 <= n <= 48 for n in (expected,value)):
            raise ValueError('Current magic must be an integer in 0..48')
        before = self._guard(capability=True, idle=True)
        if value > before['maximum']:
            raise ValueError('Current magic cannot exceed its capacity')
        path = self.audit_dir/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-')+uuid.uuid4().hex+'.json')
        receipt = dict(session=self.session_id, field='MP', transport='active_player_single_cas',
            address=before['address'], expected=expected, value=value, before=before,
            state='prepared', audit_path=str(path), automatic_retry=False, automatic_rollback=False,
            hud_effect_verified=False, save_file_effect_verified=False)
        self._save(path,receipt)
        receipt['state']='cas_in_flight'
        self._save(path,receipt)
        try:
            final=self._guard(idle=True)
            if value > final['maximum']:
                raise ValueError('Magic capacity changed before the edit')
        except Exception as error:
            receipt.update(state='refused_before_cas',error=str(error))
            self._save(path,receipt)
            raise
        try:
            result=self.client.compare_write(final['address'],expected,value)
        except Exception as error:
            receipt.update(state='uncertain_no_retry',error=str(error))
            self._save(path,receipt)
            raise RuntimeError(f'Magic edit outcome uncertain; do not retry. Audit: {path}') from error
        receipt['response']=result
        if not isinstance(result,dict) or type(result.get('swapped')) is not bool:
            receipt['state']='uncertain_no_retry'
            self._save(path,receipt)
            raise RuntimeError(f'Magic response unrecognized; do not retry. Audit: {path}')
        receipt['state']=('applied' if result.get('actual')==value and result.get('readback_matches') is True
                          else 'applied_concurrent_change') if result['swapped'] else 'expected_mismatch_no_change'
        try:receipt['after']=self.read()
        except Exception as error:receipt['observation_error']=str(error)
        self._save(path,receipt)
        return receipt
