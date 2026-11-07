"""Native equipment synchronization must not replay or roll back after publication."""
import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from live import Bindings


class SyncFailureTest(unittest.TestCase):
    def run_failure(self,published):
        calls=[]
        sync=SimpleNamespace(published=False,validate=lambda:None)
        def request():sync.published=published;raise TimeoutError('Uncertain refresh')
        sync.request=request
        client=SimpleNamespace(status=lambda:{},compare_write=lambda a,o,n:
            (calls.append((a,o,n)) or {'swapped':True,'readback_matches':True,'actual':n}))
        fake=SimpleNamespace(client=client,validate=lambda:None,session_id=('test',1),last_edit=None,
            _writes=lambda changes:[dict(address=4,expected=0,value=1)],view=lambda:{})
        with tempfile.TemporaryDirectory() as d,patch('live.ROOT',Path(d)),patch('equipment_sync.EquipmentSync',return_value=sync):
            with self.assertRaises(TimeoutError):Bindings.apply(fake,{'counts':{'Item_Ocarina_Fairy':1}})
        return calls,fake.last_edit

    def test_no_rollback_after_native_publication(self):
        calls,undo=self.run_failure(True)
        self.assertEqual(calls,[(4,0,1)]);self.assertIsNone(undo)

    def test_conflict_before_native_publication_can_rollback(self):
        calls,undo=self.run_failure(False)
        self.assertEqual(calls,[(4,0,1),(4,1,0)]);self.assertIsNone(undo)

    def test_preflight_refusal_prevents_even_preparing_writes(self):
        def refuse():raise ValueError('Menu is open')
        fake=SimpleNamespace(client=SimpleNamespace(status=lambda:{}),validate=lambda:None,
            _writes=lambda c:self.fail('Must preflight before any write planning'))
        with patch('equipment_sync.EquipmentSync',return_value=SimpleNamespace(validate=refuse)):
            with self.assertRaises(ValueError):Bindings.apply(fake,{'items':{'Item_Ocarina_Time':True}})


if __name__=='__main__':unittest.main()
