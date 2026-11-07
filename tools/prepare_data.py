"""Expand indexed metadata and draw original identifier badges, not game art."""
from pathlib import Path
import gzip,hashlib,json,re
ROOT=Path(__file__).resolve().parents[1]

def prepare(icon_folder=None):
    editor=ROOT/'editor'
    receipt=json.loads((ROOT/'data/actor-catalog.json').read_text())
    db=editor/'actor-catalog.sqlite3'
    if not db.exists() or hashlib.sha256(db.read_bytes()).hexdigest()!=receipt['sha256']:
        data=gzip.decompress((ROOT/'data/actor-catalog.sqlite3.gz').read_bytes())
        if hashlib.sha256(data).hexdigest()!=receipt['sha256']:raise ValueError('Actor catalogue integrity check failed')
        temp=db.with_suffix('.tmp');temp.write_bytes(data);temp.replace(db)
    bookmarks=editor/'locations.json'
    if not bookmarks.exists():bookmarks.write_text('{"version":1,"locations":[]}\n')
    folder=Path(icon_folder) if icon_folder is not None else editor/'assets/icons'
    folder.mkdir(parents=True,exist_ok=True)
    if (folder/'manifest.json').exists():return
    from PIL import Image,ImageDraw
    ids=json.loads((ROOT/'data/icon-ids.json').read_text())
    rows=[]
    for index,name in enumerate(ids):
        p=folder/(name+'.png')
        image=Image.new('RGBA',(64,64),(38,43,53,255));draw=ImageDraw.Draw(image)
        draw.rounded_rectangle((1,1,62,62),radius=7,outline=(130,150,180,255),width=2)
        words=re.sub(r'(?<=[a-z])(?=[A-Z])',' ',name).replace('_',' ').split()
        words=[w for w in words if w not in ('Item','Weapon','Armor','g','Icon','Tex')]
        label='\n'.join(w[:9] for w in words[-3:])
        draw.multiline_text((5,12),label,fill='white',spacing=3)
        image.save(p);rows.append(dict(id=name,png=p.name,width=64,height=64,kind='original-label'))
    # A programmatically drawn music note replaces the extracted SoH texture.
    image=Image.new('RGBA',(24,36),(0,0,0,0));draw=ImageDraw.Draw(image)
    draw.ellipse((3,24,13,32),fill='white');draw.rectangle((11,5,14,28),fill='white')
    draw.polygon([(13,5),(22,10),(22,15),(13,11)],fill='white');image.save(folder/'soh-song-note.png')
    (folder/'manifest.json').write_text(json.dumps(dict(icons=rows),indent=2)+'\n')

if __name__=='__main__':prepare()
