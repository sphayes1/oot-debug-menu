"""Observed-state native Save/Load menu shortcuts through the game debug API.

Never restores process memory or writes save files. A failed/uncertain input is
not replayed; unfamiliar menu states leave control to the player.
"""
import base64,io,json,time,uuid,hashlib
from pathlib import Path
import numpy as np
from PIL import Image
from teleport import TeleportTransport

ROOT=Path(__file__).resolve().parent


class MenuReader:
    def __init__(self):
        spec=json.loads((ROOT/'save-menu-patterns.json').read_text(encoding='utf-8'))
        self.patterns={k:(v['rect'],np.asarray(Image.open(io.BytesIO(base64.b64decode(v['png']))),dtype=float))
                       for k,v in spec['patterns'].items()}

    def decode(self,png):
        return np.asarray(Image.open(io.BytesIO(png)).convert('RGB').resize((1280,720)),dtype=np.uint8)

    def matches(self,image,key):
        rect,template=self.patterns[key];x0,y0,x1,y1=rect
        gray=np.asarray(Image.fromarray(image).convert('L'),dtype=float)
        # Small integer shifts tolerate menu settling without searching gameplay.
        t=template-template.mean();den=float(np.linalg.norm(t))
        best=-1.
        for dy in (-1,0,1):
            for dx in (-1,0,1):
                crop=gray[y0+dy:y1+dy,x0+dx:x1+dx];v=crop-crop.mean()
                norm=float(np.linalg.norm(v))*den
                if norm:best=max(best,float(np.sum(v*t))/norm)
        return best>.90

    @staticmethod
    def selected(image,kind):
        rects={'save':(105,216,285,228),'load':(105,279,285,291),
               'confirm':(552,425,728,438),'first_save':(330,102,940,115)}
        x0,y0,x1,y1=rects[kind]
        white=np.min(image[y0:y1,x0:x1],axis=2)>210
        return bool(np.max(np.mean(white,axis=1))>.75)

    def system(self,image):return self.matches(image,'system') and self.matches(image,'system_save')
    def confirm(self,image,action):
        return (self.matches(image,action+'_title') and self.matches(image,'cancel') and
                self.matches(image,'confirm_'+action))


class SaveActions:
    def __init__(self,binding):
        self.binding=binding;self.client=binding.client;self.reader=MenuReader()
        self.scene=TeleportTransport(binding);self.trace=[]

    def frame(self):
        self.binding.validate()
        self.png=base64.b64decode(self.client.call('screenshot')['png_base64'])
        return self.reader.decode(self.png)

    def tap(self,key,settle=30):
        self.binding.validate()
        self.trace.append({'button':key,'settle_frames':settle})
        self.client.call('input_sequence',{'steps':[{'buttons':[key],'frames':3},{'frames':settle}],
                         'timeout_s':15},timeout=20)

    def wait(self,predicate,timeout=6):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            image=self.frame()
            if predicate(image):return image
            time.sleep(.2)
        raise ValueError('Save shortcut stopped at an unrecognized menu. Continue manually; no input was retried.')

    def disk_state(self):
        import backend
        return {str(p.relative_to(ROOT/'runtime/nand')):dict(mtime_ns=p.stat().st_mtime_ns,
                    sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in backend.save_files()}

    def run(self,action):
        if action not in ('save','load'):raise ValueError('Unknown save action')
        self.scene.validate()  # No menu, event, load, paused emulator or pending debug request.
        self.binding.last_edit=None
        audit={'action':action,'session':self.binding.session_id,'state':'started','trace':self.trace,
               'before':self.disk_state(),'automatic_retry':False}
        path=ROOT/'runtime/save-action-audits'/(uuid.uuid4().hex+'.json');path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(audit,indent=2)+'\n')
        try:
            self.tap('Plus',40)
            for i in range(4):
                image=self.frame()
                if self.reader.system(image):break
                if i==3:raise ValueError('English System tab was not found; continue manually')
                self.tap('R',25)
            # Find Save by its visible highlight. Cursor history is not assumed.
            for i in range(6):
                image=self.frame()
                if not self.reader.system(image):raise ValueError('System menu changed; continue manually')
                if self.reader.selected(image,'save'):break
                if i==5:raise ValueError('Save button was not selected; continue manually')
                self.tap('Up',12)
            if action=='load':
                self.tap('Down',12);image=self.frame()
                if not self.reader.system(image) or not self.reader.selected(image,'load'):
                    raise ValueError('Load button was not selected; continue manually')
            self.tap('A',35)
            if action=='load':
                # Native list is sorted newest first, including autosaves. Do not
                # confirm a remembered/other row unless its first outline is seen.
                image=self.wait(lambda im:self.reader.matches(im,'load_title') and not self.reader.confirm(im,'load'))
                for i in range(7):
                    if self.reader.selected(image,'first_save'):break
                    if i==6:raise ValueError('Newest save was not selected; continue manually')
                    self.tap('Up',15)
                    image=self.wait(lambda im:self.reader.matches(im,'load_title') and not self.reader.confirm(im,'load'))
                self.tap('A',30)
            image=self.wait(lambda im:self.reader.confirm(im,action))
            if not self.reader.selected(image,'confirm'):
                self.tap('Up',12)
                image=self.wait(lambda im:self.reader.confirm(im,action) and self.reader.selected(im,'confirm'))
            # The only destructive confirm is issued after seeing the correct
            # Save/Load caption and highlighted affirmative button.
            audit['state']='confirming';path.write_text(json.dumps(audit,indent=2)+'\n')
            self.tap('A',45)
            if action=='save':
                self.wait(self.reader.system,timeout=20)
                after=self.disk_state()
                if after==audit['before']:raise ValueError('No completed save-file update was observed; inspect the game')
                audit['after']=after
                self.tap('Plus',30)
            end=time.monotonic()+180;stable_since=None
            while True:
                self.binding.validate()
                # Save loading recreates bindings. Typed GameData remains guarded
                # by the session; reconnect active player objects in the caller.
                try:
                    self.scene.validate()
                    # Native flags can briefly clear before ChangeBanc begins.
                    # Require a visible scene and three continuous idle seconds,
                    # rather than treating the pre-transition gap as completion.
                    image=self.frame()
                    if float(np.mean(image[:600]))<5:raise ValueError('Loading fade')
                    if stable_since is None:stable_since=time.monotonic()
                    if time.monotonic()-stable_since>=3:break
                except ValueError:
                    stable_since=None
                if time.monotonic()>=end:raise TimeoutError('Game did not return to idle gameplay; no retry')
                time.sleep(.5)
            audit['actual']=self.scene.fields.capture();audit['state']='completed'
            return audit
        except Exception as exc:
            audit.update(state='stopped-no-retry',error=str(exc))
            if hasattr(self,'png'):path.with_suffix('.png').write_bytes(self.png)
            raise
        finally:path.write_text(json.dumps(audit,indent=2)+'\n')
