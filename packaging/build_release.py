"""Build either public portable variant from the same debug-client source."""
import argparse,gzip,hashlib,importlib.util,json,shutil,subprocess,sys,zipfile
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.prepare_data import prepare
from bundle_python import bundle

def sha(data):return hashlib.sha256(data).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant',choices=['mainline','optimized'],required=True)
    parser.add_argument('--emulator-dir',type=Path,required=True)
    parser.add_argument('--profile',type=Path,required=True,help='Reviewed external emulator profile JSON')
    parser.add_argument('--emulator-source',type=Path,required=True,help='Corresponding emulator source tree for license files')
    parser.add_argument('--output',type=Path,default=ROOT/'dist')
    args=parser.parse_args()
    if sys.version_info[:2]!=(3,10):raise ValueError('Release bundling requires the tested64-bit Python3.10 runtime')
    spec=json.loads(args.profile.read_text(encoding='utf-8'))
    if spec['variant']!=args.variant:raise ValueError('Emulator profile variant mismatch')
    if args.variant=='mainline' and (spec.get('files') or spec.get('environment') or spec.get('configuration')):raise ValueError('Mainline cannot include custom performance overrides')
    emulator=args.emulator_dir.resolve();exe=emulator/'eden-cli.exe'
    if sha(exe.read_bytes())!=spec['emulator_sha256']:raise ValueError('Emulator does not match reviewed profile')
    data=exe.read_bytes()
    if not all(word in data for word in (b'compare_write32',b'live_inventory_enabled',b'input_sequence')):
        raise ValueError('Emulator lacks required debug bridge capabilities')
    prepare()
    args.output.mkdir(parents=True,exist_ok=True)
    name='OOT-Debug-Menu-'+args.variant.title()+'-Win64'
    stage=args.output/(name+'-'+datetime.now().strftime('%Y%m%d-%H%M%S'));out=stage/name
    out.mkdir(parents=True,exist_ok=False)
    def copy(src,rel):
        p=out/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,p)
    def text(rel,value):
        p=out/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value,encoding='utf-8')
    modules='app assignments backend bottles capacities enhancements equipment_sync live location_capture locations native_ui native_requests notifications ocarinas player_life player_magic position position_ui presentation songs songs_ui teleport teleport_ui age_switch collectibles collectibles_ui hotkeys save_actions actor_catalog actor_catalog_ui'.split()
    for name_ in modules:copy(ROOT/'editor'/(name_+'.py'),'editor/'+name_+'.py')
    for name_ in ('catalog.json','live-schema.json','songs-schema.json','teleport-presets.json','collectibles.json','save-menu-patterns.json'):
        copy(ROOT/'editor'/name_,'editor/'+name_)
    for name_ in ('assignments-schema.json','bottle-schema.json','capacity-schema.json','enhancements-schema.json','pouch-ui-table.json'):
        copy(ROOT/'editor/research'/name_,'editor/research/'+name_)
    copy(ROOT/'editor/data/gamedata-schema.json','editor/data/gamedata-schema.json')
    copy(ROOT/'editor/actor-catalog.sqlite3','editor/actor-catalog.sqlite3')
    prepare(out/'editor/assets/icons')
    text('editor/locations.json','{"version":1,"locations":[]}\n')
    for name_ in ('nup.py','assets.py','setup_game.py','apply_profile.py','controller_config.py','__init__.py'):copy(ROOT/'tools'/name_,'tools/'+name_)
    for p in (ROOT/'mods').rglob('*'):
        if p.is_file():copy(p,Path('mods')/p.relative_to(ROOT/'mods'))
    for name_ in ('nand','sdmc','load','dump','tas','live-debug'):(out/'editor/runtime'/name_).mkdir(parents=True,exist_ok=True)
    for p in emulator.iterdir():
        if p.is_file() and (p.suffix=='.dll' or p.name=='eden-cli.exe'):copy(p,'emulator/'+p.name)
    (out/'emulator/user/keys').mkdir(parents=True)
    copy(ROOT/'packaging/portable.py','portable.py')
    text('emulator-profile.json',json.dumps(spec,indent=2)+'\n')
    receipt=json.loads((ROOT/'data/actor-catalog.json').read_text())
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    package=dict(version=1,variant=args.variant,debug_source_commit=commit,emulator_sha256=spec['emulator_sha256'],
        emulator_revision=spec['revision'],environment=spec.get('environment',{}),
        game_main_sha256=json.loads((ROOT/'mods/manifest.json').read_text())['original_main_sha256'],
        actor_catalog={k:receipt[k] for k in ('sha256','actors','placements','hand_selected','hand_selection_sha256')},
        game_and_keys_included=False,personal_save_included=False,extracted_game_art_included=False)
    text('portable-package.json',json.dumps(package,indent=2)+'\n')
    keyboard=(ROOT/'packaging/keyboard.ini').read_text(encoding='utf-8')+'\n'+spec.get('configuration','')
    for mode in ('keyboard','controller'):text('config/'+mode+'.ini',keyboard)
    site=Path(importlib.util.find_spec('numpy').origin).parent.parent
    bundle(out,Path(sys.base_prefix),site,emulator)
    copy(ROOT/'LICENSE','licenses/Debug-Menu-GPL-3.0.txt')
    for p in (args.emulator_source/'LICENSES').glob('*.txt'):copy(p,'licenses/emulator/'+p.name)
    copy(args.emulator_source/'LICENSE.txt','licenses/emulator-LICENSE.txt')
    for name_ in ('README.md','THIRD-PARTY-NOTICES.md'):copy(ROOT/name_,'docs/'+name_)
    for p in (ROOT/'docs').glob('*.md'):copy(p,'docs/'+p.name)
    text('README FIRST.txt',(ROOT/'packaging/README.txt').read_text(encoding='utf-8').replace('@VARIANT@',args.variant).replace('@REVISION@',spec['revision']))
    for name_,command in [('Setup.cmd','setup'),('Start Ocarina + Debug Menu.cmd','start'),('Start Keyboard + Debug Menu.cmd','start --keyboard'),('Open Debug Menu.cmd','editor'),('Check Setup.cmd','check'),('Import Controller Settings.cmd','controller')]:
        text(name_,'@echo off\ncd /d "%~dp0"\n"%~dp0python\\python.exe" "%~dp0portable.py" '+command+' %*\nif errorlevel 1 pause\n')
    copy(ROOT/'docs/GETTING-STARTED.md','START HERE.txt')
    for p in out.rglob('*'):
        if p.is_file():
            if p.name in ('prod.keys','title.keys','session.json','live-binding.json','settings.json'):raise ValueError('Runtime/secret file in package')
            if p.suffix.lower() in ('.sav','.nup','.nsp','.xci','.ainb','.zs','.pdb'):raise ValueError('Private or reconstructed game asset in package')
    rows=[dict(path=p.relative_to(out).as_posix(),size=p.stat().st_size,sha256=sha(p.read_bytes())) for p in sorted(out.rglob('*')) if p.is_file()]
    text('package-files.json',json.dumps(rows,indent=2)+'\n')
    archive=args.output/(name+'.zip');temp=archive.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(out.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(stage).as_posix())
    temp.replace(archive)
    report=dict(zip=str(archive),sha256=sha(archive.read_bytes()),bytes=archive.stat().st_size,variant=args.variant,
        debug_source_commit=commit,emulator_sha256=spec['emulator_sha256'],stage=str(out),files=len(rows)+1)
    archive.with_suffix('.receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
