"""Reserve plain F5/F6 for direct checkpoints in debug profiles only."""

def reserve_checkpoint_keys(text):
    replacements={
        'Shortcuts\\Main%20Window\\Stop%20Emulation\\KeySeq':'Ctrl+Shift+F5',
        'Shortcuts\\Main%20Window\\Restart%20Emulation\\KeySeq':'Ctrl+Shift+F6',
        'Shortcuts\\Main Window\\Stop Emulation\\KeySeq':'Ctrl+Shift+F5',
        'Shortcuts\\Main Window\\Restart Emulation\\KeySeq':'Ctrl+Shift+F6',
    }
    lines=text.splitlines();changed=set()
    for i,line in enumerate(lines):
        key,sep,value=line.partition('=')
        if sep and key in replacements and value.strip() in ('F5','F6'):
            lines[i]=key+'='+replacements[key];changed.add(key)
    for i,line in enumerate(lines):
        key,sep,value=line.partition('=')
        if sep and key.endswith('\\default') and key[:-8] in changed:
            lines[i]=key+'=false'
    return '\n'.join(lines)+'\n'
