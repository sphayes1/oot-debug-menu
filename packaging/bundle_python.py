"""Bundle the tested Python runtime and declared dependencies without installers."""
from pathlib import Path
import csv,json,shutil,zipfile

def bundle(out,pyhome,site,emulator):
    def copy(src,rel):
        target=out/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,target)
    def text(rel,value):
        target=out/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(value,encoding='utf-8')
    py=out/'python';py.mkdir()
    for name in ('python.exe','pythonw.exe','python3.dll','python310.dll'):copy(pyhome/name,'python/'+name)
    for p in emulator.glob('*.dll'):copy(p,'python/'+p.name)
    for p in (pyhome/'DLLs').iterdir():
        if p.suffix.lower() in ('.pyd','.dll') and not p.name.startswith('_tkinter'):copy(p,'python/DLLs/'+p.name)
    skip={'site-packages','test','tests','idlelib','tkinter','turtledemo','ensurepip','venv','__pycache__','lib2to3','distutils'}
    with zipfile.ZipFile(py/'python310.zip','w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in (pyhome/'Lib').rglob('*.py'):
            rel=p.relative_to(pyhome/'Lib')
            if not set(rel.parts)&skip:z.write(p,rel.as_posix())
    text('python/python310._pth','python310.zip\nDLLs\nLib/site-packages\n..\n')
    for name in ('_imgui_bundle.cp310-win_amd64.pyd','opencv_world4100.dll','glfw3.dll','LICENSE'):
        copy(site/'imgui_bundle'/name,'python/Lib/site-packages/imgui_bundle/'+name)
    text('python/Lib/site-packages/imgui_bundle/__init__.py',
         'from pathlib import Path\nfrom ._imgui_bundle import imgui, hello_imgui, portable_file_dialogs\nhello_imgui.override_assets_folder(str(Path(__file__).parent/"assets"))\n')
    for p in (site/'imgui_bundle/assets').rglob('*'):
        if p.is_file():copy(p,Path('python/Lib/site-packages/imgui_bundle/assets')/p.relative_to(site/'imgui_bundle/assets'))
    for folder in ('numpy','numpy.libs','PIL','zstandard','oead'):
        for p in (site/folder).rglob('*'):
            if p.is_file() and not set(p.relative_to(site).parts)&{'tests','__pycache__','include','_pyinstaller','benchmarks'} and p.suffix not in ('.pyc','.pyi','.h','.lib','.pxd'):
                copy(p,Path('python/Lib/site-packages')/p.relative_to(site))
    for p in site.glob('oead*.pyd'):copy(p,'python/Lib/site-packages/'+p.name)
    # This wheel uses a privately named MSVC runtime DLL beside its extension.
    for record in site.glob('oead-*.dist-info/RECORD'):
        for row in csv.reader(record.read_text(encoding='utf-8').splitlines()):
            relative=Path(row[0]);p=(site/relative).resolve()
            if relative.suffix.lower()=='.dll' and p.is_relative_to(site.resolve()) and p.is_file():
                copy(p,Path('python/Lib/site-packages')/relative)
    for pattern in ('numpy-*.dist-info','pillow-*.dist-info','zstandard-*.dist-info','oead-*.dist-info'):
        for folder in site.glob(pattern):
            for p in folder.rglob('*'):
                if p.is_file() and ('license' in p.name.lower() or 'licenses' in p.parts):
                    copy(p,Path('licenses/dependencies')/folder.name/p.relative_to(folder))
    copy(pyhome/'LICENSE.txt','licenses/Python.txt')
    copy(site/'imgui_bundle/LICENSE','licenses/ImGui-Bundle.txt')
