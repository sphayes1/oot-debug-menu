"""Local, revision-checked connection to Ocarina's emulator debug API."""
import json
import socket
import struct
import hashlib
import time
import threading
from datetime import datetime
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parent
TITLE='0400486024DEC000'


class Client:
    def __init__(self,port=6545):
        self.port=port
        self._connection=None
        self._pending=b''
        self._serial=0
        self._lock=threading.Lock()

    def _close(self):
        if self._connection is not None:
            self._connection.close()
        self._connection=None
        self._pending=b''

    def close(self):
        with self._lock:
            self._close()

    def call(self,method,params=None,timeout=8):
        # The server accepts multiple newline-delimited requests per connection.
        # Reuse one socket so continuous gameplay polling cannot exhaust Windows ports.
        with self._lock:
            self._serial+=1
            request=json.dumps({'id':self._serial,'method':method,'params':params or {}}).encode()+b'\n'
            try:
                if self._connection is None:
                    self._connection=socket.create_connection(('127.0.0.1',self.port),timeout=timeout)
                    self._connection.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
                self._connection.settimeout(timeout)
                self._connection.sendall(request)
                while b'\n' not in self._pending:
                    part=self._connection.recv(65536)
                    if not part:raise ConnectionError('The game debug connection closed; reconnect')
                    self._pending+=part
                    if len(self._pending)>8*1024*1024:raise ValueError('Debug response too large')
                line,self._pending=self._pending.split(b'\n',1)
                response=json.loads(line)
                if response.get('id')!=self._serial:raise ValueError('Unexpected debug response ID')
                if 'error' in response:raise ValueError(str(response['error']))
                return response['result']
            except Exception:
                # Never replay a request after an uncertain write or lost response.
                self._close()
                raise

    def status(self):
        # Capability/session checks must not wait for a half-second FPS sample.
        status=self.call('status', {'fps_window_ms': 0})
        if status.get('program_id')!=TITLE:
            raise ValueError('This connection is not the Ocarina of Time game')
        expected=str(ROOT/'runtime/live-debug').replace('\\','/').lower()
        if status.get('dump_dir','').replace('\\','/').lower()!=expected:
            raise ValueError('Connect to the isolated inventory-editor game profile')
        return status

    def read(self,address,size):
        response=self.call('read_memory',{'address':hex(address),'size':size})
        return bytes.fromhex(response['hex'])

    def u32(self,address):
        return struct.unpack('<I',self.read(address,4))[0]

    def search(self,pattern,**parameters):
        return self.call('search_memory',dict(pattern=pattern.hex(),**parameters))

    def compare_write(self,address,expected,value):
        return self.call('compare_write32',dict(address=hex(address),expected=expected,value=value))


class Bindings:
    """Resolve typed GameData banks afresh; addresses never carry across processes."""
    def __init__(self,client=None):
        self.client=client or Client()
        self.schema=json.loads((ROOT/'live-schema.json').read_text(encoding='utf-8'))
        self.catalog=json.loads((ROOT/'catalog.json').read_text(encoding='utf-8'))
        self.indices={kind:{row['hash']:i for i,row in enumerate(self.schema[kind])} for kind in ('Bool','Int')}
        self.items={row['id']:row for row in self.catalog['items']}
        self.stats={'rupees':'a77921d7','health':'31ab5580','max_health':'fbe01da1'}
        self.connected=False
        self.last_edit=None
        self.bottles=None
        self.capacities=None
        self.assignments=None
        self.enhancements=None

    def session(self):
        row=json.loads((ROOT/'runtime/session.json').read_text(encoding='utf-8'))
        return (row['pid'],row['started'])

    def read_chunks(self,address,size):
        return b''.join(self.client.read(address+i,min(65536,size-i)) for i in range(0,size,65536))

    @staticmethod
    def u64(data,offset=0):return struct.unpack_from('<Q',data,offset)[0]

    def descriptor(self,address,kind,heap):
        data=self.client.read(address,80)
        expected=len(self.schema[kind])
        count=struct.unpack_from('<I',data,8)[0]
        bank=self.u64(data,16)
        lookup=self.u64(data,24)
        capacity=struct.unpack_from('<I',data,36)[0]
        stride=24 if kind=='Bool' else 40
        if count!=expected or not count<=capacity<=count*4:
            raise ValueError('GameData type table does not match the inspected revision')
        if not heap[0]<=bank<bank+count*stride<=heap[1] or not heap[0]<=lookup<lookup+capacity*8<=heap[1]:
            raise ValueError('GameData table points outside mapped game heap')
        first=self.client.read(bank,stride)
        vtable=self.u64(first)
        if vtable%8 or not 0x10000<vtable<heap[0]:
            raise ValueError('Invalid GameData object type')
        needed=(list(self.stats.values())+[r['stock_hash'] for r in self.items.values()] if kind=='Int' else
                [row['history_hash'] for row in self.items.values() if 'history_hash' in row])
        table=self.read_chunks(lookup,capacity*8)
        for key in needed:
            index=self.indices[kind][key]
            if struct.pack('<II',int(key,16),index) not in table:
                raise ValueError('Runtime hash-to-index map differs from item catalog')
            obj=self.client.read(bank+index*stride,stride)
            if self.u64(obj)!=vtable:raise ValueError('Runtime GameData object type mismatch')
        return dict(address=address,bank=bank,vtable=vtable,stride=stride,count=count)

    def connect(self):
        self.client.close()
        status=self.client.status()
        if not status.get('live_inventory_enabled'):
            raise ValueError('Launch the inventory-enabled game build from this editor first.')
        original=ROOT/'runtime/verification'/self.schema['source_member']
        if hashlib.sha256(original.read_bytes()).hexdigest()!=self.schema['source_sha256']:
            raise ValueError('Game revision differs from the inspected inventory schema')
        session=self.session()
        pattern=struct.pack('<Q',len(self.schema['Bool']))
        cursor=None
        for _ in range(160):
            parameters=dict(max_hits=64,budget_ms=250)
            if cursor:parameters['start']=cursor
            result=self.client.search(pattern,**parameters)
            heap=(int(result['start'],16) if cursor is None else heap[0],int(result['end'],16))
            for hit in result['hits']:
                candidate=int(hit,16)-8
                if candidate%8:continue
                try:
                    bool_desc=self.descriptor(candidate,'Bool',heap)
                    int_desc=self.descriptor(candidate+0xc0,'Int',heap)
                except (ValueError,KeyError,struct.error):continue
                self.bool_desc,self.int_desc=bool_desc,int_desc
                self.bottles=None
                self.capacities=None
                self.assignments=None
                self.enhancements=None
                self.session_id=session
                self.connected=True
                view=self.view()
                if not 12<=view['max_health']<=160 or not 0<=view['health']<=view['max_health']:
                    self.connected=False
                    continue
                (ROOT/'live-binding.json').write_text(json.dumps(dict(session=session,boolean=bool_desc,integer=int_desc,
                    note='Discovered and checked against runtime hash/index maps; never reused across launches'),indent=2)+'\n')
                from bottles import BottleBindings
                self.bottles=BottleBindings(self)
                self.bottles.bind()
                from capacities import CapacityBindings
                self.capacities=CapacityBindings(self)
                self.capacities.bind()
                from assignments import AssignmentBindings
                self.assignments=AssignmentBindings(self)
                self.assignments.bind()
                from enhancements import EnhancementBindings
                self.enhancements=EnhancementBindings(self)
                self.enhancements.bind()
                return self.view()
            if result['complete']:break
            cursor=result['next']
        self.connected=False
        raise ValueError('Active inventory banks not found. Load a save and connect again.')

    def validate(self):
        if not self.connected:raise ValueError('Connect to the running game first')
        if self.session()!=self.session_id:
            self.connected=False
            raise ValueError('The game session changed. Connect again.')
        for desc in (self.bool_desc,self.int_desc):
            header=self.client.read(desc['address'],24)
            if self.u64(header,16)!=desc['bank'] or struct.unpack_from('<I',header,8)[0]!=desc['count']:
                self.connected=False
                raise ValueError('The game-state bank changed. Connect again.')

    def object(self,key,kind):
        desc=self.bool_desc if kind=='Bool' else self.int_desc
        address=desc['bank']+self.indices[kind][key]*desc['stride']
        data=self.client.read(address,desc['stride'])
        if self.u64(data)!=desc['vtable']:raise ValueError('Stale game-state object')
        return address,data

    def view(self):
        self.validate()
        # Read the contiguous typed bank once instead of one RPC per item.
        bank=self.read_chunks(self.int_desc['bank'],self.int_desc['count']*self.int_desc['stride'])
        def integer(key):
            offset=self.indices['Int'][key]*40
            if self.u64(bank,offset)!=self.int_desc['vtable']:raise ValueError('Stale game-state object')
            return struct.unpack_from('<i',bank,offset+28)[0]
        values={}
        for label,key in self.stats.items():
            values[label]=integer(key)
        values['items']={}
        values['counts']={}
        for actor,row in self.items.items():
            count=integer(row['stock_hash'])
            if not 0<=count<=9999:raise ValueError('Invalid pouch stock count')
            values['counts'][actor]=count
            values['items'][actor]=count>0
        if self.bottles and self.bottles.connected:
            values['bottles']=self.bottles.view()
        values['wallet_capacity']=self.wallet_capacity(values['counts'])
        if self.capacities and self.capacities.connected:
            values['capacities']=self.capacities.view()
            values['wallet_capacity']=values['capacities']['Rupee']
        if self.assignments and self.assignments.connected:
            values['gear']=self.assignments.view()
        if self.enhancements and self.enhancements.connected:
            values['enhancements']=self.enhancements.view()
        return values

    @staticmethod
    def wallet_capacity(counts):
        # Verified ExpansionMaxNumActor assets: small200, medium500, large1000.
        return 1000 if counts.get('Item_Wallet_Large',0)>0 else 500 if counts.get('Item_Wallet_Medium',0)>0 else 200

    def _writes(self,changes):
        current=self.view()
        if set(changes)-set(self.stats)-{'items','counts','bottles','capacities','assignments','allow_unowned_assignment','enhancements'}:raise ValueError('Unknown live inventory field')
        if {'health','max_health'}&set(changes):
            raise ValueError('Live health editing is not validated yet; the game derives capacity from additional state')
        stats={key:changes.get(key,current[key]) for key in self.stats}
        if any(type(value) is not int for value in stats.values()):raise ValueError('Counters require integers')
        if not 0<=stats['rupees']<=1000:raise ValueError('Rupees must be within 0–1000')
        if not 12<=stats['max_health']<=80 or stats['max_health']%4:raise ValueError('Maximum health must be 3–20 hearts')
        if not 0<=stats['health']<=stats['max_health']:raise ValueError('Health must be within maximum')
        items=changes.get('items',{})
        if not isinstance(items,dict) or set(items)-set(self.items) or any(type(v) is not bool for v in items.values()):
            raise ValueError('Unknown item or invalid ownership value')
        counts=changes.get('counts',{})
        if not isinstance(counts,dict) or set(counts)-set(self.items):raise ValueError('Unknown pouch count')
        counts=dict(counts)
        for actor,owned in items.items():counts[actor]=max(1,current['counts'][actor]) if owned else 0
        if any(type(v) is not int or not 0<=v<=self.items[a]['count_max'] for a,v in counts.items()):
            raise ValueError('Pouch count exceeds the item limit')
        capacity_changes=changes.get('capacities',{})
        if not isinstance(capacity_changes,dict):raise ValueError('Invalid capacity changes')
        wallet_max=capacity_changes.get('Rupee',current.get('wallet_capacity',self.wallet_capacity(dict(current['counts'],**counts))))
        if 'rupees' in changes and (type(wallet_max) is not int or stats['rupees']>wallet_max):
            raise ValueError('Rupees exceed the current wallet capacity')
        writes=[]
        order=['max_health','health','rupees'] if stats['max_health']>=current['max_health'] else ['health','max_health','rupees']
        for label in order:
            if label not in changes:continue
            address,data=self.object(self.stats[label],'Int')
            # +28 is live and +32 is the serialized copy. Normal Save was
            # verified to retain only the latter in the isolated slot02 test.
            for offset in (28,32):
                old=struct.unpack_from('<I',data,offset)[0]
                if old!=stats[label]:writes.append(dict(address=address+offset,expected=old,value=stats[label],field=label))
        for actor,count in counts.items():
            row=self.items[actor]
            address,data=self.object(row['stock_hash'],'Int')
            for offset in (28,32):
                before=struct.unpack_from('<I',data,offset)[0]
                if before!=count:writes.append(dict(address=address+offset,expected=before,value=count,field=row['label']+' StockNum'+(' save' if offset==32 else '')))
            for key,value in ([(row['history_hash'],True)] if count and 'history_hash' in row else []):
                address,data=self.object(key,'Bool')
                if data[22] not in (0,1) or data[23] not in (0,1):raise ValueError('Ownership bank is updating; retry')
                before=struct.unpack_from('<I',data,20)[0]
                after=(before&0xffff)|(int(value)<<16)|(int(value)<<24)
                if before!=after:writes.append(dict(address=address+20,expected=before,value=after,field=row['label']))
        if changes.get('bottles'):
            if not self.bottles:raise ValueError('Connect the bottle state first')
            for slot in changes['bottles']:
                if counts.get(slot,current['counts'].get(slot,0))<=0:
                    raise ValueError('Grant the bottle before changing its contents')
            writes.extend(self.bottles.write_plan(changes['bottles'],require_owned=False,make_valid=False))
        if self.bottles:
            validity={slot:count>0 for slot,count in counts.items() if slot.startswith('Bottle')}
            validity.update({slot:True for slot in changes.get('bottles',{})})
            writes.extend(self.bottles.validity_plan(validity))
        if capacity_changes:
            if not self.capacities:raise ValueError('Connect capacity state first')
            writes.extend(self.capacities.write_plan(capacity_changes))
        if changes.get('assignments'):
            if not self.assignments:raise ValueError('Connect selected-item state first')
            if not isinstance(changes['assignments'],dict):raise ValueError('Invalid selected-item changes')
            unrestricted=changes.get('allow_unowned_assignment',False)
            if type(unrestricted) is not bool:raise ValueError('Invalid assignment policy')
            desired=dict(current['counts'],**counts)
            for age,symbol in changes['assignments'].items():
                if symbol is not None and not isinstance(symbol,str):raise ValueError('Invalid selected-item symbol')
                if symbol in (None,'Empty') or unrestricted:continue
                if symbol.startswith('Bottle'):
                    owned=desired.get(symbol,0)>0 and (symbol in counts or current['bottles'].get(symbol,{}).get('valid',False))
                else:
                    actors=self.assignments.schema['symbol_actors'].get(symbol,[])
                    owned=any(desired.get(a,0)>0 for a in actors)
                if not owned:raise ValueError('Selected item must be owned')
            writes.extend(self.assignments.write_plan(changes['assignments'],require_owned=False))
        if changes.get('enhancements'):
            if not self.enhancements:raise ValueError('Connect enhancement state first')
            writes.extend(self.enhancements.write_plan(changes['enhancements']))
        from ocarinas import write_plan as ocarina_write_plan
        writes.extend(ocarina_write_plan(self, counts, current))
        return writes

    def apply(self,changes):
        self.client.status()
        self.validate()
        from ocarinas import ACTORS
        ocarina_changed=bool(set(ACTORS).intersection(set(changes.get('counts',{}))|set(changes.get('items',{}))))
        sync=None
        if ocarina_changed:
            from equipment_sync import EquipmentSync
            sync=EquipmentSync(self)
            sync.validate()  # Refuse menus, stale modules and pending requests before writes.
        writes=self._writes(changes)
        if not writes and sync is None:return self.view()
        completed=[]
        receipt=ROOT/'live-edits'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.json')
        receipt.parent.mkdir(exist_ok=True)
        audit=dict(session=self.session_id,changes=changes,writes=writes,completed=completed,state='planned',equipment_sync=sync is not None)
        receipt.write_text(json.dumps(audit,indent=2)+'\n')
        try:
            for row in writes:
                result=self.client.compare_write(row['address'],row['expected'],row['value'])
                if not result.get('swapped') or not result.get('readback_matches') or result.get('actual')!=row['value']:
                    raise ValueError('Game state changed during the edit; remaining writes cancelled')
                completed.append(row)
            if sync is not None:
                audit['native_equipment_sync']=sync.request()
            audit['state']='applied'
            self.last_edit=audit if writes else None
        except Exception:
            audit['state']='equipment-sync-uncertain-no-rollback' if sync is not None and sync.published else 'failed-or-partial'
            self.last_edit=None
            # Only reverse words that still equal this edit; never overwrite a concurrent change.
            for row in (reversed(completed) if sync is None or not sync.published else []):
                try:self.client.compare_write(row['address'],row['value'],row['expected'])
                except Exception:pass
            raise
        finally:receipt.write_text(json.dumps(audit,indent=2)+'\n')
        return self.view()

    def undo(self):
        self.validate()
        if not self.last_edit or tuple(self.last_edit['session'])!=self.session_id:
            raise ValueError('No live edit to undo in this game session')
        sync=None
        if self.last_edit.get('equipment_sync'):
            from equipment_sync import EquipmentSync
            sync=EquipmentSync(self)
            sync.validate()
        final_words={row['address']:row['value'] for row in self.last_edit['writes']}
        for address,value in final_words.items():
            if self.client.u32(address)!=value:
                raise ValueError('The game changed an edited value; undo is blocked to preserve gameplay changes')
        for row in reversed(self.last_edit['writes']):
            result=self.client.compare_write(row['address'],row['value'],row['expected'])
            if not result.get('swapped'):raise ValueError('Game state changed while undoing')
        self.last_edit=None
        if sync is not None:sync.request()
        return self.view()
