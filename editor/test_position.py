"""Native position requests: validate, publish last and never replay uncertainty."""
import json
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from position import PositionTransport, REQUEST, coordinates
from teleport import TeleportTransport


class PositionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root/'manifest.json').write_text('{"position_protocol":1}')
        for key in ('ROOT', 'MOD'):
            p=patch('position.'+key,root); p.start(); self.addCleanup(p.stop)
        self.raw=bytearray(64)
        self.flag=bytearray(24)
        struct.pack_into('<I',self.flag,20,0x01001234)
        self.calls=[]; self.fail=None; self.lost=False; self.applied=False; self.tick=0
        self.origin=dict(banc='KokiriForest_Child',age='Child',position=[20.,100.,40.],rotation=[0.,0.,0.])
        def cas(address,expected,value):
            self.calls.append((address,expected,value))
            if address==self.fail:return {'swapped':False}
            data,offset=(self.flag,20) if address==0x214 else (self.raw,address-0x100)
            if struct.unpack_from('<I',data,offset)[0]!=expected:return {'swapped':False}
            struct.pack_into('<I',data,offset,value)
            if address==0x214:
                self.applied=True
                if self.lost:raise TimeoutError('Response lost')
                self.flag[22]=0  # Native action acknowledged.
            return {'swapped':True,'readback_matches':True}
        def status():
            self.tick+=2
            return {'presents':self.tick}
        self.client=SimpleNamespace(compare_write=cas,status=status)
        self.binding=SimpleNamespace(client=self.client,session_id=('session',1),
            object=lambda key,kind:(0x200,bytes(self.flag)))
        self.transport=PositionTransport.__new__(PositionTransport)
        self.transport.binding=self.binding;self.transport.client=self.client
        fields=SimpleNamespace(capture=lambda:dict(self.origin),
            object=lambda kind,key:(0x100,bytes(self.raw)),field=lambda kind,key:self.origin['banc'])
        scene=SimpleNamespace(validate=lambda:None,fields=fields,
            boolean=lambda key:bool(self.flag[22]),_cas=None,client=self.client)
        scene._cas=lambda row:TeleportTransport._cas(scene,row)
        self.transport.scene=scene

    def test_coordinate_validation_rejects_nan_inf_bool_and_out_of_bounds(self):
        for value in ([0,0], [float('nan'),0,0], [float('inf'),0,0], [True,0,0], [1000001,0,0]):
            with self.assertRaises(ValueError):coordinates(value)

    def test_move_publishes_once_after_all_three_words_and_preserves_metadata(self):
        r=self.transport.move([1,2,3])
        self.assertEqual(r['state'],'applied')
        self.assertEqual([x[0] for x in self.calls],[0x124,0x128,0x12c,0x214])
        self.assertEqual(self.flag[20:22],bytes.fromhex('3412'))
        self.assertEqual(self.flag[23],1)  # Unsaved request never overwrites save-facing byte.

    def test_nudge_uses_fresh_position_not_a_stale_ui_draft(self):
        self.transport.move(axis=0,delta=10)
        self.assertEqual(struct.unpack_from('<3f',self.raw,36),(30.,100.,40.))

    def test_all_eighteen_axis_step_combinations(self):
        for axis in range(3):
            for step in (-100,-10,-1,1,10,100):
                with self.subTest(axis=axis,step=step):
                    self.transport.move(axis=axis,delta=step)
                    expected=list(self.origin['position']); expected[axis]+=step
                    self.assertEqual(list(struct.unpack_from('<3f',self.raw,36)),expected)

    def test_invalid_axis_step_and_pending_request_do_not_write(self):
        for kwargs in (dict(axis=3,delta=1),dict(axis=0,delta=2),dict(axis=True,delta=1)):
            with self.assertRaises(ValueError):self.transport.move(**kwargs)
        self.flag[22]=1
        with self.assertRaises(ValueError):self.transport.move([1,2,3])
        self.assertEqual(self.calls,[])

    def test_coordinates_from_a_different_area_are_refused(self):
        with self.assertRaisesRegex(ValueError,'Area changed'):
            self.transport.move([1,2,3],expected_area='Market_Adult')
        self.assertEqual(self.calls,[])

    def test_preparation_conflict_rolls_back_without_publication(self):
        self.fail=0x128
        with self.assertRaises(ValueError):self.transport.move([1,2,3])
        self.assertFalse(self.applied)
        self.assertEqual(struct.unpack_from('<3f',self.raw,36),(0.,0.,0.))

    def test_lost_publication_never_replays_or_rolls_back(self):
        self.lost=True
        with self.assertRaises(TimeoutError):self.transport.move([1,2,3])
        self.assertEqual(sum(a==0x214 for a,_,_ in self.calls),1)
        self.assertEqual(struct.unpack_from('<3f',self.raw,36),(1.,2.,3.))
        audit=json.loads(next(Path(self.tmp.name).glob('runtime/position-audits/*.json')).read_text(encoding='utf-8'))
        self.assertEqual(audit['state'],'uncertain-after-request')


if __name__=='__main__':unittest.main()
