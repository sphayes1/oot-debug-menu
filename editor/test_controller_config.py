import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.controller_config import import_controls

class ControllerImportTests(unittest.TestCase):
    def test_import_preserves_renderer_and_private_storage(self):
        old='[Controls]\nold=1\n[Renderer]\nresolution_setup=2\n[Data%20Storage]\nnand_directory=private\n'
        new='[Controls]\nplayer_0_button_a=engine:sdl,guid:example\n[Renderer]\nresolution_setup=9\n'
        result=import_controls(old,new)
        self.assertIn('guid:example',result);self.assertIn('resolution_setup=2',result)
        self.assertIn('nand_directory=private',result);self.assertNotIn('resolution_setup=9',result)

    def test_missing_controls_is_actionable_error(self):
        with self.assertRaisesRegex(ValueError,'no controller settings'):import_controls('[Controls]\n','[Renderer]\nx=1')

    def test_first_section_can_be_added(self):
        result=import_controls('[Renderer]\nx=1\n','[Controls]\nname=Controller\n')
        self.assertEqual(result.count('[Controls]'),1);self.assertIn('[Renderer]\nx=1',result)

if __name__=='__main__':unittest.main()
