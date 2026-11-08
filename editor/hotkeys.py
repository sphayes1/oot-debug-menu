"""Configurable, non-repeating Windows shortcuts scoped to the connected game.

A dedicated message thread registers only while that exact emulator PID has
foreground focus. It reports actions; all game IO stays on the editor worker.
"""
import ctypes,json,queue,threading,time
from ctypes import wintypes
from pathlib import Path

ROOT=Path(__file__).resolve().parent
KEYS=[f'F{i}' for i in range(1,25) if i!=12]  # F12 is reserved by Windows.
LEGACY_DEFAULT={'enabled':True,'save':{'key':'F5','ctrl':True,'alt':True,'shift':False},
                'load':{'key':'F9','ctrl':True,'alt':True,'shift':False}}
DEFAULT={'enabled':True,'save':{'key':'F5','ctrl':False,'alt':False,'shift':False},
         'load':{'key':'F6','ctrl':False,'alt':False,'shift':False}}


def shortcut(spec):
    return '+'.join([name for key,name in [('ctrl','Ctrl'),('alt','Alt'),('shift','Shift')] if spec[key]]+[spec['key']])


def validate_config(config):
    if not isinstance(config,dict) or set(config)!={'enabled','save','load'} or type(config['enabled']) is not bool:
        raise ValueError('Invalid shortcut configuration')
    for action in ('save','load'):
        spec=config[action]
        if (not isinstance(spec,dict) or set(spec)!={'key','ctrl','alt','shift'} or spec['key'] not in KEYS or
                any(type(spec[k]) is not bool for k in ('ctrl','alt','shift'))):
            raise ValueError('Choose a function key and modifiers for each shortcut')
    if config['save']==config['load']:raise ValueError('Save and load must use different shortcuts')
    return json.loads(json.dumps(config))


def check_emulator_collisions(config):
    path=ROOT/'runtime/sdl2-config.ini'
    if not path.exists():return
    used={line.split('=',1)[1].strip().lower() for line in path.read_text(encoding='utf-8').splitlines()
          if 'Shortcuts\\' in line and '\\KeySeq=' in line}
    for action in ('save','load'):
        if shortcut(config[action]).lower() in used:
            raise ValueError(shortcut(config[action])+' is already an emulator shortcut; choose another combination')


class Hotkeys:
    def __init__(self):
        self.error='';self.status='Game focus required';self.events=queue.Queue();self.stop_event=threading.Event()
        self.pid=None;self.active=False
        try:self.config=validate_config(json.loads((ROOT/'hotkeys.json').read_text(encoding='utf-8')))
        except FileNotFoundError:self.config=validate_config(DEFAULT)
        except (ValueError,TypeError) as exc:
            self.config=validate_config(DEFAULT);self.config['enabled']=False;self.error=str(exc)
        if self.config==LEGACY_DEFAULT:self.config=validate_config(DEFAULT)
        self.thread=threading.Thread(target=self._run,daemon=True,name='oot-save-hotkeys');self.thread.start()

    def apply(self,config):
        config=validate_config(config);check_emulator_collisions(config)
        temporary=ROOT/'hotkeys.json.tmp';temporary.write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
        temporary.replace(ROOT/'hotkeys.json');self.config=config;self.error=''

    def context(self,pid,active):self.pid=pid;self.active=bool(active)

    def take(self):
        result=[]
        while True:
            try:result.append(self.events.get_nowait())
            except queue.Empty:return result

    def close(self):self.stop_event.set();self.thread.join(timeout=2)

    def _run(self):
        registered={};signature=None
        try:
            u=ctypes.WinDLL('user32',use_last_error=True)
            u.GetForegroundWindow.restype=wintypes.HWND
            u.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
            u.RegisterHotKey.argtypes=[wintypes.HWND,ctypes.c_int,wintypes.UINT,wintypes.UINT]
            u.UnregisterHotKey.argtypes=[wintypes.HWND,ctypes.c_int]
            u.PeekMessageW.argtypes=[ctypes.POINTER(wintypes.MSG),wintypes.HWND,wintypes.UINT,wintypes.UINT,wintypes.UINT]
            last_event=0.
            while not self.stop_event.wait(.025):
                config=self.config;foreground=wintypes.DWORD()
                u.GetWindowThreadProcessId(u.GetForegroundWindow(),ctypes.byref(foreground))
                active=self.active and config['enabled'] and foreground.value==self.pid
                wanted=json.dumps(config,sort_keys=True) if active else None
                if wanted!=signature:
                    for key in registered:u.UnregisterHotKey(None,key)
                    registered={};signature=wanted
                    if active:
                        check_emulator_collisions(config)
                        for key,action in ((0x6f01,'save'),(0x6f02,'load')):
                            spec=config[action];mods=0x4000|(2*spec['ctrl'])|spec['alt']|(4*spec['shift'])
                            vk=0x70+int(spec['key'][1:])-1
                            if u.RegisterHotKey(None,key,mods,vk):registered[key]=action
                            else:self.error=shortcut(spec)+' is unavailable (Windows error '+str(ctypes.get_last_error())+')'
                    self.status='Active in game' if len(registered)==2 else 'Game focus required'
                message=wintypes.MSG()
                while u.PeekMessageW(ctypes.byref(message),None,0x312,0x312,1):
                    now=time.monotonic()
                    if active and message.wParam in registered and now-last_event>1:
                        self.events.put((registered[message.wParam],self.pid,now));last_event=now
        except Exception as exc:self.error=str(exc)
        finally:
            if registered:
                for key in registered:u.UnregisterHotKey(None,key)


class HotkeysPanel:
    def __init__(self,editor):
        self.editor=editor;self.hotkeys=Hotkeys();self.draft=validate_config(self.hotkeys.config)
        self.feedback=''

    def pump(self):
        e=self.editor;session=e.binding.session_id if e.connected else None
        idle=(e.future is None or e.operation in ('Refresh','Camera flight','Collision snapshot')) and not e.pending
        self.hotkeys.context(session[0] if session else None,e.connected and idle)
        for action,pid,stamp in self.hotkeys.take():
            if not session or session[0]!=pid or not idle or time.monotonic()-stamp>2:continue
            self.queue(action);idle=False

    def queue(self,action):
        e=self.editor;e.native_undo_blocked=True
        e.submit('Quick save' if action=='save' else 'Load checkpoint',lambda:self.perform(action))

    def perform(self,action):
        from direct_checkpoint import DirectCheckpoint
        self.editor.native_undo_blocked=True
        receipt=DirectCheckpoint(self.editor.binding).run(action)
        return dict(kind='checkpoint',action=action,receipt=receipt,values=self.editor.connect())

    def draw(self):
        from imgui_bundle import imgui
        if imgui.button('Hotkeys...'):imgui.open_popup('save-hotkeys')
        if imgui.begin_popup('save-hotkeys'):
            imgui.text('Save / load shortcuts')
            _,self.draft['enabled']=imgui.checkbox('Enable while game has focus',self.draft['enabled'])
            for action,label in [('save','Quick save'),('load','Load checkpoint')]:
                imgui.push_id(action);imgui.text(label)
                spec=self.draft[action]
                _,index=imgui.combo('Key',KEYS.index(spec['key']),KEYS);spec['key']=KEYS[index]
                for i,(key,text) in enumerate([('ctrl','Ctrl'),('alt','Alt'),('shift','Shift')]):
                    if i:imgui.same_line()
                    _,spec[key]=imgui.checkbox(text,spec[key])
                imgui.pop_id()
            if imgui.button('Apply shortcuts'):
                try:self.hotkeys.apply(self.draft);self.feedback='Shortcuts saved.'
                except ValueError as exc:self.feedback=str(exc)
            if self.feedback:imgui.text_wrapped(self.feedback)
            if self.hotkeys.error:imgui.text_wrapped(self.hotkeys.error)
            imgui.text_wrapped('Direct game checkpoints: no menus, button automation or confirmations. Save writes normal progress; load restores your last quick-save slot and reloads the area. This is not a full emulator save state. Close game menus before use. First press Save to create a checkpoint.')
            imgui.text('Current: '+shortcut(self.hotkeys.config['save'])+' / '+shortcut(self.hotkeys.config['load']))
            busy=not self.editor.connected or bool(self.editor.pending) or (self.editor.future is not None and self.editor.operation!='Refresh')
            imgui.begin_disabled(busy)
            if imgui.button('Quick save now'):self.queue('save')
            imgui.same_line()
            if imgui.button('Load checkpoint now'):self.queue('load')
            imgui.end_disabled();imgui.end_popup()
