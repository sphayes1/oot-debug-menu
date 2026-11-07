import unittest
from live import Bindings
import presentation as p

class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.items=Bindings().items
        self.counts={a:0 for a in self.items}
    def test_reference_grid_and_catalog_coverage(self):
        self.assertEqual(len(p.INVENTORY),24)
        for slot in p.INVENTORY+p.EXTRA_INVENTORY+p.UPGRADES+(p.WALLET,p.STICK_BAG,p.NUT_BAG):
            for actor in slot.choices:self.assertIn(actor,self.items)
    def test_picker_replaces_variant_and_preserves_unrelated(self):
        slot=next(s for s in p.INVENTORY if s.key=='hookshot')
        self.counts['Item_Hookshot']=1
        changes=p.selection_changes(slot,'Item_Longshot',self.counts)
        self.assertEqual(changes,{'counts':{'Item_Hookshot':0,'Item_Longshot':1}})
        with self.assertRaises(ValueError):p.selection_changes(slot,'Item_Bomb',self.counts)
    def test_give_all_and_reset_are_scoped_to_inventory(self):
        for give in (True,False):
            change=p.inventory_action(give,self.counts,self.items)
            self.assertNotIn('Weapon_Sword_Kokiri',change['counts'])
            self.assertNotIn('Armor_Child_Mask_Amiibo0',change['counts'])
            self.assertNotIn('Item_Wallet_Large',change['counts'])
            self.assertEqual(change['counts']['BottleE'],int(give))
            self.assertEqual(change['counts']['Item_Arrow_Normal'],99 if give else 0)
            self.assertEqual(change['counts']['Item_Hookshot'],0)
            self.assertEqual(change['counts']['Item_Longshot'],int(give))
    def test_selected_highest_stage_and_none(self):
        self.assertIsNone(p.selected(p.WALLET,self.counts))
        self.counts['Item_Wallet_Small']=1
        self.counts['Item_Wallet_Large']=1
        self.assertEqual(p.selected(p.WALLET,self.counts),'Item_Wallet_Large')

    def test_selected_button_tracks_hookshot_replacement(self):
        counts=dict(self.counts,Item_Hookshot=1)
        view={'counts':counts,'gear':{'assignments':{'Child':{'symbol':'Hookshot'}}}}
        symbols={'Hookshot':['Item_Hookshot'],'Longshot':['Item_Longshot']}
        slot=next(s for s in p.INVENTORY if s.key=='hookshot')
        changes=p.selection_changes(slot,'Item_Longshot',counts)
        self.assertEqual(p.sync_assignments(changes,view,symbols)['assignments'],{'Child':'Longshot'})
        self.assertEqual(p.sync_assignments({'counts':{'Item_Hookshot':0}},view,symbols)['assignments'],{'Child':'Empty'})
        self.assertNotIn('assignments',p.sync_assignments({'counts':{'Item_Bomb':1}},view,symbols))

    def test_any_age_picker_includes_opposite_age_owned_item_without_granting_unowned(self):
        schema={'fields':{'Child':{'values':['Empty','Hookshot','Boomerang','Bow','BottleA']}},
                'symbol_actors':{'Hookshot':['Item_Hookshot'],'Boomerang':['Item_Boomerang'],'Bow':['Weapon_Range_Bow']}}
        items={'Item_Hookshot':True,'Item_Boomerang':True,'Weapon_Range_Bow':False,'BottleA':True}
        ages={'Item_Hookshot':{'Adult'},'Item_Boomerang':{'Child'},'Weapon_Range_Bow':{'Adult'}}
        bottles={'BottleA':{'valid':False}}
        self.assertEqual(p.assignment_choices(schema,'Child',items,bottles,ages),['Empty','Boomerang'])
        self.assertEqual(p.assignment_choices(schema,'Child',items,bottles,ages,allow_any_age=True),['Empty','Hookshot','Boomerang'])
        bottles['BottleA']['valid']=True
        self.assertIn('BottleA',p.assignment_choices(schema,'Child',items,bottles,ages,allow_any_age=True))
        self.assertFalse(items['Weapon_Range_Bow'])

    def test_existing_unrestricted_picker_still_shows_all_legal_symbols(self):
        schema={'fields':{'Adult':{'values':['Empty','SlingShot']}},'symbol_actors':{'SlingShot':['Weapon_Range_SlingShot']}}
        self.assertEqual(p.assignment_choices(schema,'Adult',{}, {}, {},restrict_valid=False),['Empty','SlingShot'])

if __name__=='__main__':unittest.main()
