"""Guarded inventory save editing for the inspected OOT 1.1.1 revision."""
from pathlib import Path
import argparse
import csv
import ctypes
from ctypes import wintypes
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import tempfile
import uuid
from datetime import datetime

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
CATALOG = json.loads((ROOT/'catalog.json').read_text(encoding='utf-8'))
ITEMS = {item['id']: item for item in CATALOG['items']}
STATS = {'rupees': 0xa77921d7, 'health': 0x31ab5580, 'max_health': 0xfbe01da1}
TITLE = '0400486024DEC000'
SCHEMA = json.loads((ROOT/'data/gamedata-schema.json').read_text(encoding='utf-8'))
TYPES = {int(row['hash'],16): row['type'] for row in SCHEMA if len(row['hash']) <= 8}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def emulator_running():
    if os.name != 'nt':
        return False
    class ProcessEntry(ctypes.Structure):
        _fields_=[('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),
                  ('th32ProcessID',wintypes.DWORD),('th32DefaultHeapID',ctypes.c_size_t),
                  ('th32ModuleID',wintypes.DWORD),('cntThreads',wintypes.DWORD),
                  ('th32ParentProcessID',wintypes.DWORD),('pcPriClassBase',wintypes.LONG),
                  ('dwFlags',wintypes.DWORD),('szExeFile',wintypes.WCHAR*260)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
    kernel.Process32FirstW.argtypes=[wintypes.HANDLE,ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes=[wintypes.HANDLE,ctypes.POINTER(ProcessEntry)]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateToolhelp32Snapshot(2,0)
    if handle==wintypes.HANDLE(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry=ProcessEntry();entry.dwSize=ctypes.sizeof(entry)
        valid=kernel.Process32FirstW(handle,ctypes.byref(entry))
        while valid:
            if entry.szExeFile.lower() in {'eden.exe','eden-cli.exe','eglantine.exe'}:return True
            valid=kernel.Process32NextW(handle,ctypes.byref(entry))
        return False
    finally:kernel.CloseHandle(handle)


def assert_closed():
    if emulator_running():
        raise ValueError('Close the emulator before applying or restoring inventory edits.')


def prepare_profile():
    runtime = ROOT/'runtime'
    runtime.mkdir(exist_ok=True)
    for name in ('nand','sdmc','load','dump','tas','live-debug'):
        (runtime/name).mkdir(exist_ok=True)
    return runtime


def save_files():
    return sorted(p for p in (ROOT/'runtime/nand/user/save').glob(f'*/*/{TITLE}/slot_*/progress.sav'))


class Save:
    def __init__(self, data):
        self.data = bytes(data)
        if len(data) < 0x100 or struct.unpack_from('<II',data) != (0x01020304,0x002d80eb):
            raise ValueError('Unsupported save format or game revision')
        self.table_end = struct.unpack_from('<I',data,8)[0]
        if not 0x28 < self.table_end <= len(data) or (self.table_end-0x28)%8:
            raise ValueError('Invalid save table bounds')
        self.entries = {}
        for offset in range(0x28,self.table_end,8):
            key,value = struct.unpack_from('<II',data,offset)
            if key not in TYPES:
                continue  # Footer/unknown entries are preserved, never edited.
            if key in self.entries:
                raise ValueError('Duplicate typed save key')
            self.entries[key] = offset+4
        if len(self.entries) < 11000:
            raise ValueError('Incomplete or incompatible game-state table')
        for item in ITEMS.values():
            if TYPES.get(int(item['stock_hash'],16)) != 'Int':
                raise ValueError('Inventory catalog type mismatch')

    def integer(self,key):
        if key not in self.entries:
            raise ValueError(f'Missing save field {key:08x}')
        return struct.unpack_from('<i',self.data,self.entries[key])[0]

    def view(self):
        values = {name:self.integer(key) for name,key in STATS.items()}
        values['items']={name:self.integer(int(item['stock_hash'],16))>0 for name,item in ITEMS.items()}
        values['sha256']=digest(self.data)
        return values

    def strings(self):
        for key,offset in self.entries.items():
            if TYPES.get(key) != 'String64':
                continue
            pointer=struct.unpack_from('<I',self.data,offset)[0]
            if pointer < self.table_end or pointer+64>len(self.data):
                raise ValueError('Invalid saved string pointer')
            raw=self.data[pointer:pointer+64].split(b'\0',1)[0]
            yield key,raw.decode('utf-8')

    def patched(self,changes):
        if not isinstance(changes,dict) or set(changes)-set(STATS)-{'items'}:
            raise ValueError('Unknown editor field')
        current=self.view()
        desired={key:changes.get(key,current[key]) for key in STATS}
        if any(type(value) is not int for value in desired.values()):
            raise ValueError('Counters require integer values')
        if not 0<=desired['rupees']<=200:
            raise ValueError('Rupees must be 0–200 for the supported small wallet')
        if not 12<=desired['max_health']<=80 or desired['max_health']%4:
            raise ValueError('Maximum health must be 3–20 whole hearts')
        if not 1<=desired['health']<=desired['max_health']:
            raise ValueError('Current health must be positive and within maximum health')
        requested=changes.get('items',{})
        if not isinstance(requested,dict) or set(requested)-set(ITEMS):
            raise ValueError('Unknown item')
        if any(type(value) is not bool for value in requested.values()):
            raise ValueError('Item ownership requires true or false')
        referenced={value for _,value in self.strings() if value}
        for actor,owned in requested.items():
            if not owned and current['items'][actor] and actor in referenced:
                raise ValueError(f'Unequip {ITEMS[actor]["label"]} in game before removing it.')
        writes={STATS[key]:value for key,value in desired.items()}
        writes.update({int(ITEMS[actor]['stock_hash'],16):int(value) for actor,value in requested.items()})
        # Acquiring an item records history; removing ownership does not erase history.
        writes.update({int(ITEMS[actor]['history_hash'],16):1 for actor,value in requested.items() if value and 'history_hash' in ITEMS[actor]})
        result=bytearray(self.data)
        changed=[]
        for key,value in writes.items():
            old=self.integer(key)
            if old != value:
                struct.pack_into('<i',result,self.entries[key],value)
                changed.append(dict(hash=f'{key:08x}',offset=self.entries[key],before=old,after=value))
        allowed={byte for row in changed for byte in range(row['offset'],row['offset']+4)}
        if any(a!=b and index not in allowed for index,(a,b) in enumerate(zip(self.data,result))):
            raise ValueError('Unexpected save change')
        check=Save(result)
        for key,value in writes.items():
            if check.integer(key)!=value:
                raise ValueError('Edited save failed readback')
        return bytes(result),changed


def assert_target(path):
    path=Path(path).resolve()
    allowed=(ROOT/'runtime/nand/user/save').resolve()
    if not path.is_relative_to(allowed) or path.name!='progress.sav' or path.parent.parent.name!=TITLE:
        raise ValueError('Editing is restricted to this editor’s isolated Ocarina save profile')
    return path


def atomic_write(path,data):
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.inventory-',delete=False) as temporary:
        temporary.write(data)
        temporary.flush()
        os.fsync(temporary.fileno())
        temp_path=Path(temporary.name)
    try:
        os.replace(temp_path,path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def backup(path,original,changes,operation):
    directory=ROOT/'backups'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    directory.mkdir(parents=True)
    (directory/'progress.sav').write_bytes(original)
    record=dict(target=str(path.relative_to(ROOT)),before_sha256=digest(original),changes=changes,operation=operation)
    (directory/'edit.json').write_text(json.dumps(record,indent=2)+'\n')
    return directory


def apply(path,changes,expected_hash,guard=assert_closed):
    guard()
    path=assert_target(path)
    original=path.read_bytes()
    if digest(original)!=expected_hash:
        raise ValueError('Save changed since it was loaded. Reload before applying edits.')
    result,writes=Save(original).patched(changes)
    if not writes:
        return None
    directory=backup(path,original,writes,'apply')
    guard()
    if digest(path.read_bytes())!=expected_hash:
        raise ValueError('Save changed during edit; original backup retained, nothing applied')
    atomic_write(path,result)
    record=json.loads((directory/'edit.json').read_text(encoding='utf-8'))
    record['after_sha256']=digest(result)
    (directory/'edit.json').write_text(json.dumps(record,indent=2)+'\n')
    return directory


def restore(directory,guard=assert_closed):
    guard()
    directory=Path(directory).resolve()
    if not directory.is_relative_to((ROOT/'backups').resolve()):
        raise ValueError('Unknown backup directory')
    record=json.loads((directory/'edit.json').read_text(encoding='utf-8'))
    path=assert_target(ROOT/record['target'])
    original=(directory/'progress.sav').read_bytes()
    if digest(original)!=record['before_sha256']:
        raise ValueError('Backup failed integrity validation')
    Save(original)
    current=path.read_bytes()
    if digest(current)!=record.get('after_sha256'):
        raise ValueError('Save changed after this edit; restore is blocked to preserve newer progress')
    backup(path,current,[],'before-restore')
    guard()
    if digest(path.read_bytes())!=record['after_sha256']:
        raise ValueError('Save changed while restoring')
    atomic_write(path,original)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['show','apply'])
    parser.add_argument('--slot',default='slot_00')
    parser.add_argument('--changes',type=Path)
    args=parser.parse_args()
    prepare_profile()
    paths=[path for path in save_files() if path.parent.name==args.slot]
    if len(paths)!=1:
        raise ValueError('Save slot missing or ambiguous')
    path=paths[0]
    save=Save(path.read_bytes())
    if args.action=='apply':
        if not args.changes:parser.error('--changes is required for apply')
        print(apply(path,json.loads(args.changes.read_text(encoding='utf-8')),save.view()['sha256']))
    print(json.dumps(Save(path.read_bytes()).view(),indent=2))
