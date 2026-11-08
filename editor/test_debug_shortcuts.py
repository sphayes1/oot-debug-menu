"""F5/F6 must not terminate the game when used as checkpoint shortcuts."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.debug_shortcuts import reserve_checkpoint_keys


class DebugShortcutsTest(unittest.TestCase):
    def test_reserves_stop_restart_and_preserves_custom_bindings_and_renderer(self):
        text='[UI]\n'
        for name,key in [('Stop%20Emulation','F5'),('Restart%20Emulation','F6')]:
            prefix='Shortcuts\\Main%20Window\\'+name+'\\KeySeq'
            text+=prefix+'\\default=true\n'+prefix+'='+key+'\n'
        text+='Shortcuts\\Main Window\\Other\\KeySeq=Ctrl+F5\n[Renderer]\nresolution_setup=1\n'
        result=reserve_checkpoint_keys(text)
        self.assertIn('KeySeq=Ctrl+Shift+F5',result)
        self.assertIn('KeySeq=Ctrl+Shift+F6',result)
        self.assertNotIn('default=true',result)
        self.assertTrue(result.endswith('KeySeq=Ctrl+F5\n[Renderer]\nresolution_setup=1\n'))
        self.assertEqual(result,reserve_checkpoint_keys(result))


if __name__=='__main__':unittest.main()
