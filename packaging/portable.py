"""Portable Windows adapter for the accepted OOT emulator and live debug menu."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime

ROOT=Path(__file__).resolve().parent
EDITOR=ROOT/'editor'
sys.path[:0]=[str(EDITOR),str(ROOT/'tools')]
RUNTIME=EDITOR/'runtime'
SETTINGS=ROOT/'settings.json'


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def write_json(path,value):
    Path(path).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def profile():
    for name in ('nand','sdmc','load','dump','tas','live-debug'):
        (RUNTIME/name).mkdir(parents=True,exist_ok=True)
    return RUNTIME


def choose(title,pattern,default=''):
    from imgui_bundle import portable_file_dialogs as pfd
    paths=pfd.open_file(title,default,[pattern,pattern,'All files','*']).result()
    if not paths:raise ValueError('Setup cancelled; existing settings were kept.')
    return Path(paths[0]).resolve()


def resolve_game(value):
    p=Path(value)
    return (ROOT/p).resolve() if not p.is_absolute() else p.resolve()


def setup(nup_path=None,keys_dir=None):
    import backend
    if backend.emulator_running():
        raise ValueError('Close the emulator before running Setup.')
    from nup import Nup
    path=Path(nup_path).resolve() if nup_path else choose('Select your Ocarina .nup','*.nup',str(Path.home()/'Downloads'))
    print('Checking game revision...',flush=True)
    n=Nup(path)
    manifest=read_json(ROOT/'portable-package.json')
    schema=read_json(EDITOR/'live-schema.json')
    if not any(p['title_id']=='0400486024DEC000' for p in n.packages):
        raise ValueError('This is not the supported Ocarina container.')
    if n.files.get('exefs/main',{}).get('sha256')!=manifest['game_main_sha256']:
        raise ValueError('Game revision differs from this debug menu. Keep the existing setup.')
    # Verify actual ExeFS bytes as well as the TOC before accepting the revision.
    if hashlib.sha256(n.read('exefs/main')).hexdigest()!=manifest['game_main_sha256']:
        raise ValueError('Game executable failed verification.')
    member=schema['source_member'];data=n.read(member)
    if hashlib.sha256(data).hexdigest()!=schema['source_sha256']:
        raise ValueError('GameData schema differs from this debug menu.')
    selected={}
    keyroot=ROOT/'emulator/user/keys'
    for name in ('prod.keys','title.keys'):
        locations=([Path(keys_dir)/name] if keys_dir else [])+[keyroot/name,ROOT/name,path.parent/name,Path.home()/'Downloads'/name]
        source=next((p for p in locations if p.is_file() and p.stat().st_size),None)
        if source is None:source=choose('Select your '+name,'*.keys',str(path.parent))
        if source.name.lower()!=name or not source.is_file() or not source.stat().st_size:
            raise ValueError('Select the nonempty '+name+' file.')
        selected[name]=source
    from tools.setup_game import build_mod
    build_mod(n,RUNTIME/'load/0400486024DEC000/Debug Teleport (test)')
    # Optional performance overrides belong to the explicitly selected emulator
    # profile, not to the shared debug menu or the mainline profile.
    from tools.apply_profile import apply_profile
    apply_profile(n,ROOT/'emulator-profile.json',RUNTIME/'load/0400486024DEC000')
    target=EDITOR/'runtime/verification'/member
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(data)
    keyroot.mkdir(parents=True,exist_ok=True)
    for name,source in selected.items():
        if source.resolve()!=(keyroot/name).resolve():shutil.copy2(source,keyroot/name)
    try:game=str(path.relative_to(ROOT))
    except ValueError:game=str(path)
    current=read_json(SETTINGS) if SETTINGS.exists() else {}
    write_json(SETTINGS,dict(current,nup=game,toc_sha256=n.toc_hash))
    profile()
    print('Setup complete. Run Start Ocarina + Debug Menu.cmd. Keep your .nup at its selected location.')


def validate():
    from nup import Nup
    if not SETTINGS.exists() or not read_json(SETTINGS).get('nup'):raise ValueError('Run Setup.cmd once to select your .nup and keys.')
    settings=read_json(SETTINGS);game=resolve_game(settings['nup'])
    if not game.is_file():raise ValueError('The selected .nup moved. Run Setup.cmd again.')
    m=read_json(ROOT/'portable-package.json')
    if digest(ROOT/'emulator/eden-cli.exe')!=m['emulator_sha256']:
        raise ValueError('Emulator executable changed; extract a fresh package.')
    n=Nup(game)
    if n.toc_hash!=settings['toc_sha256'] or n.files.get('exefs/main',{}).get('sha256')!=m['game_main_sha256']:
        raise ValueError('Selected .nup changed; run Setup.cmd again.')
    schema=read_json(EDITOR/'live-schema.json')
    original=EDITOR/'runtime/verification'/schema['source_member']
    if not original.is_file() or digest(original)!=schema['source_sha256']:
        raise ValueError('Revision-verification asset is missing or changed; run Setup.cmd again.')
    for name in ('prod.keys','title.keys'):
        if not (ROOT/'emulator/user/keys'/name).is_file():raise ValueError('Missing '+name+'; run Setup.cmd.')
    mod=RUNTIME/'load/0400486024DEC000/Debug Teleport (test)'
    for name,expected in read_json(mod/'manifest.json')['files'].items():
        p=(mod/name).resolve()
        if not p.is_relative_to(mod.resolve()) or digest(p)!=expected:
            raise ValueError('Debug module changed; extract a fresh package.')
    profile_spec=read_json(ROOT/'emulator-profile.json')
    for row in profile_spec.get('files',[]):
        p=(RUNTIME/'load/0400486024DEC000'/row['output']).resolve()
        if not p.is_relative_to((RUNTIME/'load/0400486024DEC000').resolve()) or digest(p)!=row['result_sha256']:
            raise ValueError('Emulator-profile override changed; run Setup again.')
    return settings,game,m


def config_text(mode,settings):
    text=(ROOT/'config'/(mode+'.ini')).read_text(encoding='utf-8')
    text=text.replace('@RUNTIME@',RUNTIME.as_posix())
    guid=settings.get('controller_guid')
    if guid:
        if not re.fullmatch(r'[0-9a-fA-F]{32}',guid):raise ValueError('Controller GUID needs32 hexadecimal digits.')
        text=re.sub(r'guid:[0-9a-fA-F]{32}','guid:'+guid.lower(),text)
    from tools.debug_shortcuts import reserve_checkpoint_keys
    return reserve_checkpoint_keys(text)


def import_controller():
    import backend
    if backend.emulator_running():raise ValueError('Close the game before importing controller settings.')
    from tools.controller_config import import_controls
    default=str(Path(os.environ.get('APPDATA',str(Path.home()))))
    source=choose('Select settings from the emulator where your controller works','*.ini',default)
    target=ROOT/'config/controller.ini'
    text=import_controls(target.read_text(encoding='utf-8'),source.read_text(encoding='utf-8-sig'))
    target.write_text(text,encoding='utf-8')
    settings=read_json(SETTINGS) if SETTINGS.exists() else {}
    settings['input_mode']='controller';settings.pop('controller_guid',None)
    write_json(SETTINGS,settings)
    print('Controller settings imported. Run Start Ocarina + Debug Menu.cmd.')


def launch_game(mode=None):
    import backend
    settings,game,m=validate()
    if backend.emulator_running():raise ValueError('An emulator is already running. Close it before launching another session.')
    # Do not collide with another debug service, including a second portable copy.
    with socket.socket() as s:
        if s.connect_ex(('127.0.0.1',6545))==0:raise ValueError('Debug port6545 is already in use.')
    profile()
    mode=mode or settings.get('input_mode','controller')
    if mode not in ('controller','keyboard'):raise ValueError('Unknown input mode.')
    config=RUNTIME/'sdl2-config.ini';config.write_text(config_text(mode,settings),encoding='utf-8')
    env={k:v for k,v in os.environ.items() if not k.startswith('EDEN_NX2_') and k!='EDEN_NUP_CACHE_MIB' and k!='EDEN_TIMING_COARSE'}
    for key,value in m['environment'].items():
        if value is not None:env[key]=str(value)
    env.update(EDEN_NX2_DEBUG_SERVER='127.0.0.1:6545',EDEN_NX2_DEBUG_DIR=str(RUNTIME/'live-debug'),EDEN_NX2_LIVE_INVENTORY='1')
    exe=ROOT/'emulator/eden-cli.exe'
    process=subprocess.Popen([str(exe),'-c',str(config),'-g',str(game)],cwd=exe.parent,env=env)
    write_json(RUNTIME/'session.json',dict(pid=process.pid,started=datetime.now().astimezone().isoformat(),
        profile='Inventory',checkpoint='oot-portable-v1',executable=str(exe),executable_sha256=m['emulator_sha256']))
    print('Ocarina started. Load a save, then Connect / Refresh in the debug menu.')


def editor():
    profile()
    os.chdir(EDITOR)
    import backend,app
    backend.prepare_profile=profile
    # The original editor's launch button uses the same portable launcher.
    app.Editor.launch=lambda self:launch_game()
    app.main()


def self_check():
    # No game launch, file picker, keys or graphics-setting mutation.
    import ctypes,concurrent.futures,zipfile,zstandard,oead
    import tools.setup_game,tools.apply_profile
    import backend,app,assignments,bottles,capacities,enhancements,songs,teleport
    import collision,collision_scene,collision_geometry,collision_overlay,glfw,OpenGL.GL
    from imgui_bundle import imgui,hello_imgui,portable_file_dialogs
    instance=app.Editor();instance.controller_panel.close();instance.hotkeys_panel.hotkeys.close();instance.worker.shutdown()
    assert len(songs.SONGS)==12
    assert not instance.teleport_panel.allow_any_era
    from actor_catalog import ActorCatalog,FILTERS
    catalog=ActorCatalog()
    manifest=read_json(ROOT/'portable-package.json')['actor_catalog']
    assert digest(catalog.path)==manifest['sha256']
    selected=catalog.actors(candidate=1,placed_only=False)
    assert len(selected)==manifest['hand_selected']==51
    assert selected[0]['id']=='Obj_TBox_A_01'
    assert len(catalog.actors(placed_only=False))==manifest['actors']
    assert FILTERS[1]=='Hand selected dynamic actors'
    assert all(str(ROOT) in p or 'python310.zip' in p for p in sys.path if p)
    print('Portable Python, ImGui, native dependencies, editor schemas,12 songs and actor catalogue (51 hand selected): OK')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['setup','start','game','editor','check','self-check','controller'])
    p.add_argument('--nup');p.add_argument('--keys-dir');p.add_argument('--keyboard',action='store_true')
    a=p.parse_args()
    if a.command=='self-check':self_check();return
    if a.command=='controller':import_controller();return
    if a.command=='setup':setup(a.nup,a.keys_dir);return
    if a.command=='check':validate();print('Game, keys, emulator and debug module verified.');return
    if a.command=='editor':editor();return
    if not SETTINGS.exists() or not read_json(SETTINGS).get('nup'):setup(a.nup,a.keys_dir)
    mode='keyboard' if a.keyboard else None
    if mode:
        settings=read_json(SETTINGS);settings['input_mode']=mode;write_json(SETTINGS,settings)
    launch_game(mode)
    if a.command=='start':
        subprocess.Popen([str(ROOT/'python/pythonw.exe'),str(Path(__file__).resolve()),'editor'],
            cwd=EDITOR,creationflags=subprocess.CREATE_NO_WINDOW)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Error:',exc,file=sys.stderr)
        if sys.executable.lower().endswith('pythonw.exe'):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,str(exc),'Ocarina portable launcher',0x10)
        raise SystemExit(1)
