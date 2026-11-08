"""Direct native game save/load requests. No menu navigation or input RPCs."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,math,os,re,shutil,struct,time,uuid
from teleport import TeleportTransport,MOD
from location_capture import LocationCapture

ROOT=Path(__file__).resolve().parent
SAVE='__OOT_DIRECT_SAVE_V1__';LOAD='__OOT_DIRECT_LOAD_V1__';DONE='__OOT_DIRECT_LOAD_DONE_V1__'
PAYLOAD='0b570ab2';SAVE_REQUEST='da576eaa';LOAD_REQUEST='3fc35576';SLOT='2834256b'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def restore_file(file,stored,expected,observed):
    """Commit one verified native progress file, refusing concurrent disk changes."""
    if sha(stored)!=expected:raise ValueError('Checkpoint copy failed verification')
    temporary=file.with_name(file.name+'.oot-checkpoint.tmp')
    try:
        with temporary.open('wb') as stream:
            stream.write(stored.read_bytes());stream.flush();os.fsync(stream.fileno())
        if sha(temporary)!=expected or sha(file)!=observed:
            raise ValueError('Native save changed before restore commit')
        temporary.replace(file)
    finally:
        if temporary.exists():temporary.unlink()


class DirectCheckpoint:
    def __init__(self,binding):
        self.binding=binding;self.client=binding.client
        self.scene=TeleportTransport(binding);self.fields=LocationCapture(binding)
        self.path=ROOT/'runtime/direct-checkpoint.json'

    def cas(self,row):
        self.binding.validate()
        self.scene._cas(row)
        self.writes.append(row)

    def validate(self):
        self.scene.validate()
        if json.loads((MOD/'manifest.json').read_text()).get('direct_checkpoint_protocol')!=1:
            raise ValueError('Direct checkpoint module is not installed; restart with the updated debug game')
        if self.fields.field('String64',PAYLOAD):raise ValueError('Another native debug request is pending')

    def string(self,expected,value):
        address,raw=self.fields.object('String64',PAYLOAD)
        if (struct.unpack_from('<Q',raw,104)[0]!=address+116 or struct.unpack_from('<I',raw,112)[0]!=64
                or raw[116:180].split(b'\0')[0].decode('ascii')!=expected):
            raise ValueError('Native checkpoint mailbox changed')
        payload=value.encode('ascii').ljust(64,b'\0')
        for i in ([*range(4,64,4),0] if value else range(0,64,4)):
            before=struct.unpack_from('<I',raw,116+i)[0];after=struct.unpack_from('<I',payload,i)[0]
            if before!=after:self.cas(dict(address=address+116+i,expected=before,value=after))

    def request(self,key):
        address,raw=self.binding.object(key,'Bool')
        if raw[22]!=0:raise ValueError('A native request is already pending')
        before=struct.unpack_from('<I',raw,20)[0]
        self.cas(dict(address=address+20,expected=before,value=before|0x10000))

    def files(self):
        import backend
        return {str(p.relative_to(ROOT/'runtime/nand')):{'sha256':sha(p),'mtime_ns':p.stat().st_mtime_ns}
                for p in backend.save_files()}

    def run(self,action):
        if action not in ('save','load'):raise ValueError('Unknown checkpoint action')
        self.validate();started=time.monotonic();self.writes=[]
        audit={'action':action,'session':self.binding.session_id,'state':'preparing','automatic_retry':False,
               'utc':datetime.now(timezone.utc).isoformat(),'menu_inputs':0}
        folder=ROOT/'runtime/direct-checkpoint-audits';folder.mkdir(parents=True,exist_ok=True)
        path=folder/(uuid.uuid4().hex+'.json')
        published=False
        def record():path.write_text(json.dumps(audit,indent=2)+'\n')
        try:
            if action=='save':
                pose=self.fields.capture();before=self.files()
                audit.update(pose=pose,before=before)
                backup=ROOT/'runtime/direct-checkpoint-backups'/path.stem
                for rel in before:
                    source=ROOT/'runtime/nand'/rel;target=backup/rel
                    target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
                self.string('',SAVE);self.scene.validate();published=True
                self.request(SAVE_REQUEST);audit['state']='requested';record()
                deadline=time.monotonic()+20
                while self.scene.boolean(SAVE_REQUEST):
                    if time.monotonic()>deadline:raise TimeoutError('Native save did not acknowledge; no retry')
                    time.sleep(.015)
                # The flag is cleared only after the native save action finishes.
                self.string(SAVE,'')
                after=self.files();changed=[p for p in after if after[p]!=before.get(p)]
                progress=[p for p in changed if p.endswith('progress.sav')]
                if not progress:raise ValueError('Native save acknowledged without a changed progress file')
                _,slot_raw=self.binding.object(SLOT,'Int');slot=struct.unpack_from('<i',slot_raw,28)[0]
                archive=ROOT/'runtime/checkpoint-storage'/path.stem
                for rel in progress:
                    target=archive/rel;target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(ROOT/'runtime/nand'/rel,target)
                    if sha(target)!=after[rel]['sha256']:raise ValueError('Save changed while checkpoint was archived')
                checkpoint={'version':2,'archive':path.stem,'pose':pose,'slot':slot,'game_revision':self.binding.schema['source_sha256'],
                            'save_files':{p:after[p]['sha256'] for p in progress},'utc':audit['utc']}
                tmp=self.path.with_suffix('.json.tmp');tmp.write_text(json.dumps(checkpoint,indent=2)+'\n');tmp.replace(self.path)
                audit.update(state='saved',slot=slot,changed=changed,after=after)
            else:
                if not self.path.is_file():
                    raise ValueError('Create a checkpoint with Quick save (F5) before loading')
                checkpoint=json.loads(self.path.read_text())
                if checkpoint['version']!=2 or checkpoint['game_revision']!=self.binding.schema['source_sha256']:
                    raise ValueError('Checkpoint format or game revision changed; create a new checkpoint')
                if not re.fullmatch(r'[0-9a-f]{32}',checkpoint['archive']):raise ValueError('Invalid checkpoint archive')
                archive=ROOT/'runtime/checkpoint-storage'/checkpoint['archive']
                pending_files=[]
                for rel,expected in checkpoint['save_files'].items():
                    file=(ROOT/'runtime/nand'/rel).resolve();stored=(archive/rel).resolve()
                    if (not file.is_relative_to((ROOT/'runtime/nand').resolve()) or not stored.is_relative_to(archive.resolve())
                            or file.name!='progress.sav' or sha(stored)!=expected):
                        raise ValueError('Checkpoint archive failed verification; no files restored')
                    if not file.is_file():raise ValueError('Native checkpoint slot no longer exists')
                    if sha(file)!=expected:pending_files.append((file,stored,expected,sha(file)))
                from locations import validate_pose
                pose=validate_pose(checkpoint['pose']);audit['target']=checkpoint
                if type(checkpoint['slot']) is not int or not 0<=checkpoint['slot']<1000:
                    raise ValueError('Invalid native checkpoint slot')
                if not checkpoint['save_files'] or any(Path(rel).parent.name!=f"slot_{checkpoint['slot']:02d}" for rel in checkpoint['save_files']):
                    raise ValueError('Native slot does not match checkpoint files')
                # A normal menu load/autosave may rewrite the slot. Keep F5's
                # immutable progress, not whatever now occupies that slot.
                self.scene.validate()
                audit['restored_files']=[]
                for file,stored,expected,observed in pending_files:
                    backup=folder/(path.stem+'-'+file.parent.name+'.progress.bak')
                    shutil.copy2(file,backup)
                    if sha(backup)!=observed or sha(file)!=observed:raise ValueError('Native save changed before restore')
                    restore_file(file,stored,expected,observed)
                    audit['restored_files'].append(dict(path=str(file.relative_to(ROOT/'runtime/nand')),before=observed,after=expected,backup=str(backup.relative_to(ROOT))))
                self.scene.validate()
                def write(kind,key,payload):
                    address,raw=self.fields.object(kind,key);offset=116 if kind=='String64' else 36
                    if kind=='String64' and (struct.unpack_from('<Q',raw,104)[0]!=address+116 or struct.unpack_from('<I',raw,112)[0]!=64):
                        raise ValueError('Checkpoint destination string layout changed')
                    for i in range(0,len(payload),4):
                        a=struct.unpack_from('<I',raw,offset+i)[0];b=struct.unpack_from('<I',payload,i)[0]
                        if a!=b:self.cas(dict(address=address+offset+i,expected=a,value=b))
                write('Vector3','52046b85',struct.pack('<3f',*pose['position']))
                write('Vector3','1662143e',struct.pack('<3f',*pose['rotation']))
                address,raw=self.binding.object(SLOT,'Int')
                for off in (28,32):
                    a=struct.unpack_from('<I',raw,off)[0]
                    if a!=checkpoint['slot']:self.cas(dict(address=address+off,expected=a,value=checkpoint['slot']))
                self.string('',LOAD)
                write('String64','ee27bf71',pose['banc'].encode('ascii').ljust(64,b'\0'))
                published=True;self.request(LOAD_REQUEST);audit['state']='requested';record()
                deadline=time.monotonic()+180
                while self.fields.field('String64',PAYLOAD)!=DONE:
                    self.binding.validate()
                    if time.monotonic()>deadline:raise TimeoutError('Native load did not acknowledge; no retry')
                    time.sleep(.05)
                self.string(DONE,'')
                self.binding.connect()
                self.scene.validate();actual=self.fields.capture()
                if actual['banc']!=pose['banc'] or actual['age']!=pose['age'] or math.dist(actual['position'],pose['position'])>3:
                    raise ValueError('Load completed at an unexpected scene, age or position')
                audit.update(state='loaded',actual=actual)
            audit['seconds']=time.monotonic()-started
            return audit
        except Exception as exc:
            audit.update(state='uncertain-after-request' if published else 'cancelled-before-request',error=str(exc))
            if not published:
                try:
                    self.binding.validate()
                    for row in reversed(self.writes):
                        self.scene._cas(dict(address=row['address'],expected=row['value'],value=row['expected']))
                    for row in reversed(audit.get('restored_files',[])):
                        restore_file(ROOT/'runtime/nand'/row['path'],ROOT/row['backup'],row['before'],row['after'])
                    audit['preparation_rolled_back']=True
                except Exception as cleanup:
                    audit['cleanup_error']=str(cleanup)
            raise
        finally:
            audit['seconds']=time.monotonic()-started
            audit['writes']=self.writes
            self.binding.last_edit=None
            record()
