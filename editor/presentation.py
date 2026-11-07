"""SoH-style controls expressed as the remake's independent pouch quantities."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Slot:
    key: str
    label: str
    choices: tuple
    ammo: str = ''

def one(key,label,actor,ammo=''):
    return Slot(key,label,(actor,),ammo)

ADULT_TRADE=tuple('Item_'+name for name in ('PocketEgg','PocketCucco','CojiroCucco',
    'OddMushroom','OddPowder','PoacherSaw','BrokenSword','Prescription','EyeballFrog','EyeDrop','ClaimCheck'))
CHILD_TRADE=('Item_WeirdEgg','Item_AlarmCucco','Item_ZeldaLetter')

# Same six-by-four order as SoH, with independent remake masks kept separately.
INVENTORY=(
    one('stick','Deku Stick','Item_DekuStick','Item_DekuStick'),
    one('nut','Deku Nut','Item_DekuNut','Item_DekuNut'),
    one('bomb','Bomb','Item_Bomb','Item_Bomb'),
    one('bow','Fairy Bow','Weapon_Range_Bow','Item_Arrow_Normal'),
    one('fire','Fire Arrow','Item_Arrow_Fire'),
    one('din',"Din's Fire",'Item_DinFire'),
    one('slingshot','Fairy Slingshot','Weapon_Range_SlingShot','Item_DekuSeed'),
    Slot('ocarina','Ocarina',('Item_Ocarina_Fairy','Item_Ocarina_Time')),
    one('bombchu','Bombchu','Item_Bombchu','Item_Bombchu'),
    Slot('hookshot','Hookshot',('Item_Hookshot','Item_Longshot')),
    one('ice','Ice Arrow','Item_Arrow_Ice'),
    one('farore',"Farore's Wind",'Item_FaroreWind'),
    one('boomerang','Boomerang','Item_Boomerang'),
    one('lens','Lens of Truth','Armor_GlassTruth'),
    one('beans','Magic Beans','Item_MagicBean','Item_MagicBean'),
    one('hammer','Megaton Hammer','Item_Hammer'),
    one('light','Light Arrow','Item_Arrow_Light'),
    one('nayru',"Nayru's Love",'Item_NayruLove'),
    *(one('bottle'+s,'Bottle '+s,'Bottle'+s) for s in 'ABCD'),
    Slot('adult_trade','Adult Trade',ADULT_TRADE),
    Slot('child_trade','Child Trade',CHILD_TRADE),
)
EXTRA_INVENTORY=(one('bottleE','Bottle E','BottleE'),
    one('scrub_seed','Scrub Business Seeds','Item_ScrubBusinessSeed','Item_ScrubBusinessSeed'),
    one('amiibo','Amiibo','Pouch_Amiibo'))

UPGRADES=(
    Slot('bullet_bag','Bullet Bag',tuple('Item_BulletBag_'+n for n in ('Small','Medium','Large'))),
    Slot('quiver','Quiver',tuple('Item_Quiver_'+n for n in ('Small','Medium','Large'))),
    Slot('bomb_bag','Bomb Bag',tuple('Item_BombBag_'+n for n in ('Small','Medium','Large'))),
    Slot('scale','Scale',('Item_Scale_Silver','Item_Scale_Gold')),
    Slot('strength','Strength',('Armor_Child_Gauntlet_Goron','Armor_Adult_Gauntlet_Silver','Armor_Adult_Gauntlet_Gold')),
)
WALLET=Slot('wallet','Wallet',tuple('Item_Wallet_'+n for n in ('Small','Medium','Large')))
STICK_BAG=Slot('stick_bag','Deku Stick Capacity',tuple('Item_StickBag_'+n for n in ('Small','Medium','Large')))
NUT_BAG=Slot('nut_bag','Deku Nut Capacity',tuple('Item_NutBag_'+n for n in ('Small','Medium','Large')))
MAGIC=Slot('magic','Magic Meter',('Item_FairyBless_MP','Item_FairyBless_MPDouble'))
EQUIPMENT_ROWS=(
    ('Weapon_Sword_Kokiri','Weapon_Sword_Master','Weapon_Sword_Biggoron','Weapon_Sword_BrokenGiant'),
    ('Weapon_Shield_Deku','Weapon_Shield_Hylian','Weapon_Shield_Mirror'),
    ('Armor_Adult_Normal','Armor_Adult_Goron','Armor_Adult_Zora'),
    ('Item_NormalBoot','Armor_Adult_HeavyBoot','Armor_Adult_HoverBoot'),
)

def selected(slot,counts):
    return next((a for a in reversed(slot.choices) if counts.get(a,0)>0),None)

def selection_changes(slot,actor,counts):
    if actor is not None and actor not in slot.choices:raise ValueError('Item is not legal for this picker')
    changes={'counts':{a:max(1,counts.get(a,0)) if a==actor else 0 for a in slot.choices}}
    if slot.key in ('bullet_bag','quiver','bomb_bag','wallet','stick_bag','nut_bag'):
        from capacities import upgrade_changes
        changes.update(upgrade_changes(slot.key,actor))
    if slot.key in ('scale','strength','magic'):
        from enhancements import upgrade_changes
        changes.update(upgrade_changes(slot.key,actor))
    return changes

def inventory_action(give,counts,catalog):
    """Apply the Inventory card action without changing gear, upgrades or masks."""
    result={}
    contents={}
    for slot in INVENTORY+EXTRA_INVENTORY:
        if slot.choices[0].startswith('Bottle'):
            actor=slot.choices[0]
            result[actor]=int(give)
            if give:contents[actor]='Empty'
        else:
            result.update(selection_changes(slot,slot.choices[-1] if give else None,counts)['counts'])
        if slot.ammo:result[slot.ammo]=min(99,catalog[slot.ammo]['count_max']) if give else 0
    change={'counts':result}
    if contents:change['bottles']=contents
    return change

def assignment_choices(schema, age, items, bottles, actor_ages, *, restrict_valid=True, allow_any_age=False):
    """The age override broadens owned choices, preserving bottle/ownership rules."""
    visible=[]
    for symbol in schema['fields'][age]['values']:
        actors=schema['symbol_actors'].get(symbol,[])
        if symbol.startswith('Bottle'):
            valid=items.get(symbol,False) and bottles.get(symbol,{}).get('valid',False)
        else:
            valid=any(items.get(actor,False) and (allow_any_age or age in actor_ages.get(actor,set())) for actor in actors)
        if symbol=='Empty' or not restrict_valid or valid:
            visible.append(symbol)
    return visible


def sync_assignments(changes,view,symbol_actors):
    """Keep the remake's per-age quick-use selectors tied to replaced slots."""
    counts=dict(changes.get('counts',{}))
    for actor,owned in changes.get('items',{}).items():counts[actor]=1 if owned else 0
    after=dict(view['counts'],**counts)
    selections=dict(changes.get('assignments',{}))
    for age,entry in view.get('gear',{}).get('assignments',{}).items():
        symbol=entry['symbol']
        actors=[symbol] if symbol.startswith('Bottle') else symbol_actors.get(symbol,[])
        if symbol=='Empty' or age in selections or not any(a in counts for a in actors):continue
        if any(after.get(a,0)>0 for a in actors):continue
        replacement=None
        for slot in INVENTORY+EXTRA_INVENTORY:
            if set(slot.choices)&set(actors):replacement=selected(slot,after);break
        selections[age]=next((s for s,aa in symbol_actors.items() if replacement and replacement in aa),'Empty')
    result=dict(changes)
    if selections:result['assignments']=selections
    return result
