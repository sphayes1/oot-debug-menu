"""Debug-only emulator launcher. User-provided configuration controls rendering."""
from datetime import datetime
import hashlib,json,os,re,socket,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
EDITOR=ROOT/'editor';RUNTIME=EDITOR/'runtime'
TITLE='0400486024DEC000'
DEBUG_ENV=('EDEN_NX2_DEBUG_SERVER','EDEN_NX2_DEBUG_DIR','EDEN_NX2_LIVE_INVENTORY')

def configuration(text):
    """Rebase debug storage and reserve checkpoint keys; preserve rendering."""
    if '[Data%20Storage]' not in text:
        text+='\n[Data%20Storage]\n'
    lines=text.splitlines();result=[];in_storage=False;seen=set()
    folders=('nand','sdmc','load','dump','tas')
    values={name+'_directory':(RUNTIME/name).as_posix() for name in folders}
    def missing():
        for key,value in values.items():
            if key not in seen:result.extend([key+'\\default=false',key+'='+value])
    for line in lines:
        if line.startswith('['):
            if in_storage:missing()
            in_storage=line=='[Data%20Storage]'
        if in_storage:
            key=line.split('=',1)[0]
            if key in values:
                result.append(key+'='+values[key]);seen.add(key);continue
            if key.removesuffix('\\default') in values and key.endswith('\\default'):
                result.append(key+'=false');continue
        result.append(line)
    if in_storage:missing()
    from tools.debug_shortcuts import reserve_checkpoint_keys
    return reserve_checkpoint_keys('\n'.join(result)+'\n')

def launch_game():
    import backend
    if backend.emulator_running():raise ValueError('Close the existing emulator before launching another debug session.')
    path=ROOT/'settings.json'
    if not path.exists():raise ValueError('Run tools/setup_game.py with your NUP, emulator and input configuration first.')
    settings=json.loads(path.read_text());exe=Path(settings['emulator']);game=Path(settings['nup'])
    for p in (exe,game):
        if not p.is_file():raise ValueError('Configured file is missing: '+str(p))
    if hashlib.sha256(exe.read_bytes()).hexdigest()!=settings['emulator_sha256']:
        raise ValueError('Configured emulator changed; run setup again.')
    from tools.nup import Nup
    if Nup(game).toc_hash!=settings['nup_toc_sha256']:raise ValueError('Configured game changed; run setup again.')
    mod=RUNTIME/'load'/TITLE/'Debug Teleport (test)'
    manifest=json.loads((mod/'manifest.json').read_text())
    for name,expected in manifest['files'].items():
        p=(mod/name).resolve()
        if not p.is_relative_to(mod.resolve()) or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
            raise ValueError('Game-side debug handlers changed; run setup again.')
    with socket.socket() as s:
        if s.connect_ex(('127.0.0.1',6545))==0:raise ValueError('Debug port6545 is already in use.')
    backend.prepare_profile()
    source=Path(settings['config']).read_text(encoding='utf-8') if settings.get('config') else ''
    config=RUNTIME/'sdl2-config.ini';config.write_text(configuration(source),encoding='utf-8')
    env=dict(os.environ)
    env.update(EDEN_NX2_DEBUG_SERVER='127.0.0.1:6545',EDEN_NX2_DEBUG_DIR=str(RUNTIME/'live-debug'),EDEN_NX2_LIVE_INVENTORY='1')
    process=subprocess.Popen([str(exe),'-c',str(config),'-g',str(game)],cwd=exe.parent,env=env)
    (RUNTIME/'session.json').write_text(json.dumps(dict(pid=process.pid,started=datetime.now().astimezone().isoformat(),
        profile='Debug',executable=str(exe),executable_sha256=settings['emulator_sha256']),indent=2)+'\n')
    return process.pid
