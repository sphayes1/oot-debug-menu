"""Import an existing controller section without replacing rendering/storage settings."""
import re

def import_controls(existing,source):
    pattern=r'(?ms)^\[Controls\]\s*\r?\n.*?(?=^\[|\Z)'
    section=re.search(pattern,source)
    if section is None:raise ValueError('This file has no controller settings. Choose the qt-config.ini or sdl2-config.ini from an emulator where your controller already works.')
    controls=section.group().rstrip()+'\n\n'
    if re.search(pattern,existing):return re.sub(pattern,lambda _:controls,existing,count=1)
    return controls+existing
