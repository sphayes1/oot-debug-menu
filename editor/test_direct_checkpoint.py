"""Native checkpoint routing and failed-request containment."""
import json,struct,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import direct_checkpoint as native
from hotkeys import HotkeysPanel


class DirectCheckpointTest(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)
        p=patch.object(native,'ROOT',self.root);p.start();self.addCleanup(p.stop)
        self.binding=SimpleNamespace(client=Mock(),validate=Mock(),session_id=(123,'test'),schema={'source_sha256':'revision'},last_edit=None)
        for name in ('TeleportTransport','LocationCapture'):
            p=patch.object(native,name);p.start();self.addCleanup(p.stop)
        self.cp=native.DirectCheckpoint(self.binding);self.cp.validate=Mock()
        self.cp.fields.capture.return_value={'banc':'test','position':[1,2,3]}
        slot=bytearray(40);struct.pack_into('<i',slot,28,2)
        self.binding.object=Mock(return_value=(0x1000,slot))
        file=self.root/'runtime/nand/slot_02/progress.sav';file.parent.mkdir(parents=True);file.write_bytes(b'native progress')
        self.cp.files=Mock(side_effect=[{}, {'slot_02/progress.sav':{'sha256':native.sha(file)}}])

    def test_save_publishes_native_request_and_requires_disk_change(self):
        self.cp.string=Mock();self.cp.request=Mock();self.cp.scene.boolean.return_value=False
        result=self.cp.run('save')
        self.assertEqual(result['state'],'saved')
        self.cp.request.assert_called_once_with(native.SAVE_REQUEST)
        self.assertEqual([c.args for c in self.cp.string.call_args_list],[('',native.SAVE),(native.SAVE,'')])
        self.assertEqual(json.loads(self.cp.path.read_text())['slot'],2)
        self.binding.client.call.assert_not_called()

    def test_native_ack_without_progress_write_is_not_reported_as_success(self):
        self.cp.string=Mock();self.cp.request=Mock();self.cp.scene.boolean.return_value=False
        self.cp.files.side_effect=[{},{}]
        with self.assertRaisesRegex(ValueError,'without a changed progress'):
            self.cp.run('save')
        self.assertFalse(self.cp.path.exists())
        self.cp.request.assert_called_once()

    def test_partial_preparation_is_rolled_back_before_request(self):
        self.cp.request=Mock()
        raw=bytearray(264);struct.pack_into('<Q',raw,104,0x1000+116);struct.pack_into('<I',raw,112,64)
        self.cp.fields.object.return_value=(0x1000,raw)
        self.cp.scene._cas.side_effect=[None,ValueError('stale'),None]
        with self.assertRaisesRegex(ValueError,'stale'):self.cp.run('save')
        self.cp.request.assert_not_called()
        writes=self.cp.scene._cas.call_args_list
        first,last=writes[0].args[0],writes[-1].args[0]
        self.assertEqual(last,dict(address=first['address'],expected=first['value'],value=first['expected']))
        audit=json.loads(next((self.root/'runtime/direct-checkpoint-audits').glob('*.json')).read_text())
        self.assertEqual(audit['state'],'cancelled-before-request')
        self.assertTrue(audit['preparation_rolled_back'])

    def test_missing_checkpoint_does_not_choose_an_autosave_or_send_inputs(self):
        self.cp.string=Mock();self.cp.request=Mock()
        with self.assertRaisesRegex(ValueError,'Create a checkpoint'):
            self.cp.run('load')
        self.cp.string.assert_not_called();self.cp.request.assert_not_called()
        self.binding.client.call.assert_not_called()

    def test_hotkeys_dispatch_native_checkpoint_without_menu_fallback(self):
        editor=SimpleNamespace(binding=self.binding,connect=Mock(return_value={'items':{}}))
        panel=HotkeysPanel.__new__(HotkeysPanel);panel.editor=editor
        with patch.object(native,'DirectCheckpoint') as factory,patch('save_actions.SaveActions') as legacy:
            factory.return_value.run.return_value={'state':'loaded','seconds':12}
            result=panel.perform('load')
        factory.return_value.run.assert_called_once_with('load')
        legacy.assert_not_called();self.assertEqual(result['kind'],'checkpoint')

    def test_archive_restore_refuses_stale_disk_and_preserves_immutable_copy(self):
        archive=self.root/'archive';file=self.root/'native'
        archive.write_bytes(b'checkpoint');file.write_bytes(b'new progress')
        with self.assertRaisesRegex(ValueError,'changed before restore'):
            native.restore_file(file,archive,native.sha(archive),'stale hash')
        self.assertEqual(file.read_bytes(),b'new progress')
        native.restore_file(file,archive,native.sha(archive),native.sha(file))
        self.assertEqual(file.read_bytes(),b'checkpoint')
        self.assertEqual(archive.read_bytes(),b'checkpoint')
        self.assertFalse(file.with_name(file.name+'.oot-checkpoint.tmp').exists())


if __name__=='__main__':unittest.main()
