"""Save/load shortcuts must observe the correct menu before confirming."""
import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import numpy as np
from save_actions import SaveActions,MenuReader
from hotkeys import validate_config,DEFAULT,check_emulator_collisions

ROOT=Path(__file__).resolve().parent


class MenuReaderTest(unittest.TestCase):
    @unittest.skipUnless((ROOT/'research/hotkey-system-rpc.png').exists(), 'Optional local screenshot fixture')
    def test_observed_native_screens_and_unknown_screen(self):
        r=MenuReader()
        images={k:r.decode((ROOT/'research'/('hotkey-'+k+'-rpc.png')).read_bytes())
                for k in ('system','saveconfirm','loadconfirm','loadlist')}
        self.assertTrue(r.system(images['system']))
        self.assertTrue(r.selected(images['system'],'save'))
        self.assertFalse(r.selected(images['system'],'load'))
        self.assertTrue(r.confirm(images['saveconfirm'],'save'))
        self.assertFalse(r.confirm(images['saveconfirm'],'load'))
        self.assertTrue(r.confirm(images['loadconfirm'],'load'))
        self.assertTrue(r.selected(images['loadlist'],'first_save'))
        blank=np.zeros((720,1280,3),dtype=np.uint8)
        self.assertFalse(r.system(blank));self.assertFalse(r.confirm(blank,'save'))
        for key in ('save','load','confirm','first_save'):self.assertFalse(r.selected(blank,key))

    def test_configuration_rejects_duplicates_reserved_key_and_native_stop_shortcut(self):
        config=validate_config(DEFAULT);config['load']=dict(config['save'])
        with self.assertRaises(ValueError):validate_config(config)
        config=validate_config(DEFAULT);config['save']['key']='F12'
        with self.assertRaises(ValueError):validate_config(config)
        config=validate_config(DEFAULT);config['save'].update(ctrl=False,alt=False)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'runtime').mkdir()
            (root/'runtime/sdl2-config.ini').write_text('[UI]\nShortcuts\\Main Window\\Stop Emulation\\KeySeq=F5\n')
            with patch('hotkeys.ROOT',root),self.assertRaisesRegex(ValueError,'already an emulator shortcut'):
                check_emulator_collisions(config)


class ActionsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch('save_actions.ROOT',Path(self.temp.name));p.start();self.addCleanup(p.stop)
        self.binding=SimpleNamespace(client=Mock(),validate=Mock(),last_edit={'old':1},session_id=(123,'start'))
        self.scene=SimpleNamespace(validate=Mock(),fields=SimpleNamespace(capture=lambda:{'banc':'test'}))
        p=patch('save_actions.TeleportTransport',return_value=self.scene);p.start();self.addCleanup(p.stop)
        # Avoid assets in the temporary audit directory; reader behavior is tested above.
        p=patch('save_actions.MenuReader');self.reader=p.start().return_value;self.addCleanup(p.stop)
        self.action=SaveActions(self.binding);self.action.disk_state=Mock(side_effect=[{'slot':1},{'slot':2}])
        self.action.frame=Mock(return_value='system')
        self.reader.system.return_value=True;self.reader.selected.return_value=True
        self.action.wait=Mock(return_value='observed')
        p=patch('save_actions.np.mean',return_value=100);p.start();self.addCleanup(p.stop)
        p=patch('save_actions.time.monotonic',side_effect=iter(range(10000)));p.start();self.addCleanup(p.stop)
        p=patch('save_actions.time.sleep');p.start();self.addCleanup(p.stop)

    def test_save_confirms_once_then_requires_disk_write_and_exits_menu(self):
        self.action.tap=Mock()
        result=self.action.run('save')
        self.assertEqual(result['state'],'completed')
        self.assertEqual([c.args[0] for c in self.action.tap.call_args_list],['Plus','A','A','Plus'])
        self.assertIsNone(self.binding.last_edit)

    def test_load_requires_newest_row_and_confirmation_before_final_input(self):
        events=[]
        self.action.tap=lambda key,*args:events.append(key)
        def wait(predicate,**kw):events.append('observe');return 'screen'
        self.action.wait=wait
        result=self.action.run('load')
        self.assertEqual(result['state'],'completed')
        self.assertEqual(events,['Plus','Down','A','observe','A','observe','A'])

    def test_busy_or_unrecognized_menu_never_confirms(self):
        self.action.tap=Mock();self.scene.validate.side_effect=ValueError('busy')
        with self.assertRaises(ValueError):self.action.run('save')
        self.action.tap.assert_not_called();self.scene.validate.side_effect=None
        self.reader.system.return_value=False
        with self.assertRaisesRegex(ValueError,'System tab'):self.action.run('save')
        self.assertNotIn('A',[c.args[0] for c in self.action.tap.call_args_list])

    def test_lost_input_response_is_not_replayed(self):
        self.binding.client.call.side_effect=TimeoutError('unknown input outcome')
        with self.assertRaises(TimeoutError):self.action.run('save')
        self.assertEqual(self.binding.client.call.call_count,1)
        audit=json.loads(next(Path(self.temp.name).rglob('*.json')).read_text(encoding='utf-8'))
        self.assertEqual(audit['state'],'stopped-no-retry')

    def test_unchanged_disk_is_not_reported_as_success(self):
        self.action.tap=Mock();self.action.disk_state=Mock(return_value={'slot':1})
        with self.assertRaisesRegex(ValueError,'No completed save-file update'):self.action.run('save')

    def test_load_waits_through_black_fade_before_reporting_completion(self):
        self.action.tap=Mock()
        with patch('save_actions.np.mean',side_effect=[0,100,100,100,100,100]) as brightness:
            self.assertEqual(self.action.run('load')['state'],'completed')
            self.assertGreaterEqual(brightness.call_count,3)


if __name__=='__main__':unittest.main()
