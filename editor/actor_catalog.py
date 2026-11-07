"""Read-only indexed actor definitions/placements and guarded placement warps."""
import json,math,re,sqlite3
from contextlib import closing
from pathlib import Path
from locations import presets,validate_pose

ROOT=Path(__file__).resolve().parent
DATABASE=ROOT/'actor-catalog.sqlite3'
PAGE_SIZE=25
FILTERS=('All actors','Hand selected dynamic actors','Dynamic/contact matches','Dynamic / kinematic bodies','Reference dynamic actors')
FAMILIES=('All names','Obj_ props','Enemy_ actors','Npc_ actors','Land_ scenery','Item_ actors','Other names')


def label(name):
    result=re.sub(r'(?<=[a-z])(?=[A-Z])',' ',name).replace('_',' ')
    return result.replace('Hounted','Haunted').replace('TBox','Treasure Chest').replace('T Box','Treasure Chest').replace('Amos','Armos')


def area_age(banc):
    # Native GameBanc parameters force these two unsuffixed areas as well.
    # HyruleCastle uses the default true IsChildWhenChangeBanc; DinolfosStage
    # explicitly sets it false. Other unsuffixed dungeons preserve Link's age.
    forced={'HyruleCastle':'Child','DinolfosStage':'Adult'}
    return forced.get(banc,'Child' if '_Child' in banc else 'Adult' if '_Adult' in banc else '')


def presence_age(presence):
    if presence.get('FlagName')=='Sequence_IsChildhood':
        return 'Adult' if presence.get('IsNegation',False) else 'Child'
    return ''


def restrictions(row,age,allow_any_era=False):
    if not row['has_position']:return 'No explicit coordinates in the placement file.'
    if not row['known_area']:return 'This area is not supported by the scene loader.'
    if age not in ('Child','Adult'):return 'Connect to gameplay before teleporting.'
    if not allow_any_era:
        if row['map_age'] and row['map_age']!=age:return 'Requires '+row['map_age']+' Link or Allow any era.'
        if row['spawn_age'] and row['spawn_age']!=age:return 'Actor requires '+row['spawn_age']+' Link or Allow any era.'
    return ''


def destination(row,age,height=2.,allow_any_era=False):
    if type(allow_any_era) is not bool:raise ValueError('Invalid era override')
    error=restrictions(row,age,allow_any_era)
    if error:raise ValueError(error)
    if type(height) not in (int,float) or not math.isfinite(height) or not 0<=height<=100:
        raise ValueError('Arrival height must be between 0 and 100')
    return validate_pose(dict(banc=row['banc'],age=age,position=[row['x'],row['y']+height,row['z']],
        rotation=[0.,row['yaw'],0.],rotation_units='radians',entry='',catalog_placement=row['id'],
        actor_type=row['actor'],actor_id=row['actor_hash'],placement_source=row['source']))


def escaped(value):return value.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')


class ActorCatalog:
    def __init__(self,path=DATABASE):
        self.path=Path(path).resolve()
        with closing(self.connect()) as db:
            self.meta=dict(db.execute('SELECT key,value FROM meta'))
            if self.meta.get('version')!='1':raise ValueError('Unsupported actor catalog version')
            self.areas=[r[0] for r in db.execute('SELECT banc FROM areas ORDER BY banc')]

    def connect(self):
        db=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)
        db.row_factory=sqlite3.Row
        return db

    @staticmethod
    def scope(area='',age=''):
        if age not in ('','Child','Adult'):raise ValueError('Invalid catalog age filter')
        parts=[];params=[]
        if area:parts.append('p.banc=?');params.append(area)
        if age:
            parts+=['(p.map_age="" OR p.map_age=?)','(p.spawn_age="" OR p.spawn_age=?)'];params += [age,age]
        return (' AND '.join(parts) or '1'),params

    def actors(self,search='',area='',age='',candidate=0,family=0,placed_only=True):
        if type(candidate) is not int or not 0<=candidate<len(FILTERS):raise ValueError('Invalid candidate filter')
        if type(family) is not int or not 0<=family<len(FAMILIES):raise ValueError('Invalid name family')
        scope,params=self.scope(area,age)
        clauses=[]
        if placed_only or area:clauses.append('s.matches>0')
        elif age:clauses.append('(a.placement_count=0 OR s.matches>0)')
        choices={1:'a.closest=1',2:'a.tier="dynamic-contact-match"',3:'a.tier!=""',4:'a.reported=1'}
        if candidate:clauses.append(choices[candidate])
        if family:clauses.append('a.family=?');params.append(family)
        for token in search.lower().split():
            clauses.append("a.search LIKE ? ESCAPE '\\'");params.append('%'+escaped(token)+'%')
        where=' AND '.join(clauses) or '1'
        order=('CASE WHEN a.id="Obj_TBox_A_01" THEN 0 WHEN a.logic LIKE "%TreasureBox.aidefn" THEN 1 '
               'WHEN a.id LIKE "Obj_Tombstone_%" THEN 2 WHEN a.id="Obj_Plant_MagicBeanLeaf_A_01" THEN 3 ELSE 4 END,a.id') if candidate==1 else 'a.id'
        sql=('WITH s AS (SELECT p.actor,count(*) AS matches,sum(p.has_position) AS coordinates '
             'FROM placements p WHERE '+scope+' GROUP BY p.actor) '
             'SELECT a.*,coalesce(s.matches,0) AS matches,coalesce(s.coordinates,0) AS coordinates '
             'FROM actors a LEFT JOIN s ON s.actor=a.id WHERE '+where+' ORDER BY '+order)
        with closing(self.connect()) as db:return [dict(r) for r in db.execute(sql,params)]

    def placements(self,actor,area='',age='',page=0):
        if type(page) is not int or page<0:raise ValueError('Invalid page')
        scope,params=self.scope(area,age);scope+=' AND p.actor=?';params.append(actor)
        with closing(self.connect()) as db:
            count=db.execute('SELECT count(*) FROM placements p WHERE '+scope,params).fetchone()[0]
            page=min(page,max(0,(count-1)//PAGE_SIZE))
            rows=[dict(r) for r in db.execute('SELECT p.* FROM placements p WHERE '+scope+
                ' ORDER BY p.banc,p.actor_hash,p.source LIMIT ? OFFSET ?',params+[PAGE_SIZE,page*PAGE_SIZE])]
        return dict(count=count,page=page,rows=rows)

    def placement(self,key):
        if type(key) is not int:raise ValueError('Choose a catalog placement')
        with closing(self.connect()) as db:row=db.execute('SELECT * FROM placements WHERE id=?',(key,)).fetchone()
        if row is None:raise ValueError('Unknown catalog placement')
        return dict(row)

    def teleport(self,binding,key,height=2.,allow_any_era=False):
        from teleport import TeleportTransport
        binding.validate()
        with closing(self.connect()) as db:revision=db.execute('SELECT value FROM meta WHERE key="game_revision"').fetchone()[0]
        if revision!=binding.schema['source_sha256']:raise ValueError('Actor catalog belongs to another game revision')
        row=self.placement(key)
        age=binding.assignments.view()['active_age']
        pose=destination(row,age,height,allow_any_era)
        # Only the existing native transport publishes guest writes. Fresh age,
        # revision, idle state and module/session guards are checked at execution.
        binding.last_edit=None
        return TeleportTransport(binding).warp(pose,revision,allow_any_era=allow_any_era)
