"""The visible hand selection includes chest references and traceable matches."""
import json,unittest
from pathlib import Path
from actor_catalog import FILTERS

ROOT=Path(__file__).resolve().parent


class DynamicSelectionTest(unittest.TestCase):
    def test_chests_and_graves_are_included_without_scenery_or_reward_aliases(self):
        selection=json.loads((ROOT/'research/dynamic-selection/hand-selected.json').read_text(encoding='utf-8'))
        rows={r['actor']:r for r in selection['actors']}
        self.assertTrue(set(selection['reference_actors'])<=rows.keys())
        self.assertTrue(all(row['features']['dynamic_surface'] and row['reason'] for row in rows.values()))
        self.assertEqual(selection['groups']['Treasure chests'],13)
        self.assertIn('Obj_TBox_A_01_NoBake',rows)
        self.assertIn('Obj_HrlCity_Shop_TBox_A_01',rows)
        self.assertNotIn('Obj_Graveyard_Tombstone_A_01',rows)
        self.assertFalse(any(name.startswith(('TBox_Rupee_','Enemy_','Npc_')) for name in rows))

    def test_new_chest_like_surface_matches_have_actual_bone_tracking(self):
        selection=json.loads((ROOT/'research/dynamic-selection/hand-selected.json').read_text(encoding='utf-8'))
        rows={r['actor']:r for r in selection['actors']}
        for name in ('Obj_FireTemple_MoveFloor_A_02','Obj_ForestTemple_SwitchShutter_A_02',
                     'Obj_ShadowTemple_FallingFloor_A_01','Obj_WaterTemple_Fountain_A_01'):
            self.assertTrue(rows[name]['features']['bone_tracked_dynamic'])
            self.assertIn(name,selection['chest_like_bone_tracked_matches'])

    def test_menu_wording_is_neutral(self):
        self.assertEqual(FILTERS[1],'Hand selected dynamic actors')
        strings=' '.join(FILTERS).lower()
        self.assertNotIn('actor-jump',strings);self.assertNotIn('candidate',strings)
        ui=(ROOT/'actor_catalog_ui.py').read_text(encoding='utf-8')
        self.assertNotIn('Closest actor-jump candidate',ui)


if __name__=='__main__':unittest.main()
