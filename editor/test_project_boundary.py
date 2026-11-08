"""The public client must not activate performance mods or change rendering."""
import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('standalone_launcher',ROOT/'launcher.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)

class SeparationTest(unittest.TestCase):
    def test_storage_rebase_preserves_renderer_and_input_settings(self):
        source='[Renderer]\nresolution_setup=2\nuse_vsync=false\n[Controls]\nplayer_0_type=0\n[Data%20Storage]\nnand_directory=old\nnand_directory\\default=true\n[Audio]\noutput_device=auto\n'
        result=launcher.configuration(source)
        for line in ('resolution_setup=2','use_vsync=false','player_0_type=0','output_device=auto'):
            self.assertIn(line,result)
        self.assertNotIn('nand_directory=old',result)
        self.assertIn('nand_directory\\default=false',result)
        self.assertIn('load_directory='+str(launcher.RUNTIME/'load').replace('\\','/'),result)

    def test_missing_storage_section_is_added_without_other_settings(self):
        text=launcher.configuration('[Renderer]\nresolution_setup=1\n')
        self.assertEqual(text.count('[Data%20Storage]'),1)
        self.assertEqual(text.count('load_directory='),1)
        self.assertIn('resolution_setup=1',text)

    def test_only_debug_environment_switches_are_owned(self):
        self.assertEqual(set(launcher.DEBUG_ENV),{'EDEN_NX2_DEBUG_SERVER','EDEN_NX2_DEBUG_DIR','EDEN_NX2_LIVE_INVENTORY'})

    def test_game_mod_manifest_has_only_debug_files(self):
        manifest=json.loads((ROOT/'mods/manifest.json').read_text(encoding='utf-8'))
        paths={p.replace('\\','/') for p in manifest['files']}
        self.assertEqual(len(paths),6)
        self.assertEqual(sum(p.startswith('exefs/') for p in paths),1)
        self.assertIn('romfs/Sequence/MainUpdate.module.ainb',paths)
        self.assertIn('romfs/Sequence/ChangeBancOnMain.module.ainb',paths)
        self.assertIn('romfs/Pack/Actor/EventCamera.pack.zs',paths)
        self.assertFalse(any('PlayerCamera' in p for p in paths))
        self.assertEqual(manifest['camera_protocol'],1)
        self.assertEqual(manifest['direct_checkpoint_protocol'],1)
        self.assertIn('romfs/Sequence/_LocalModule_bde133631675.module.ainb',paths)
        self.assertFalse(any('Shadow' in p or 'FPS' in p or 'Controller' in p for p in paths))

if __name__=='__main__':unittest.main()
