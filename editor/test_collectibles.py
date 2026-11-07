"""Bean edits: exact whitelist, preserved metadata, partial/uncertain publication."""
import json,struct,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from collectibles import CATALOG,BEANS,BeanState,destination


class CatalogTest(unittest.TestCase):
    def test_unique_placements_and_complete_plant_whitelist(self):
        self.assertEqual(len({r['id'] for r in CATALOG['skulltulas']}),100)
        self.assertEqual(len(BEANS),11)
        self.assertEqual(len({r['plant_flag']['hash'] for r in BEANS.values()}),11)
        self.assertTrue(all(r['plant_flag']['parent_hash']=='820c6b5e' for r in BEANS.values()))
        self.assertEqual(sum(r['label'].startswith('Kokiri Forest') for r in BEANS.values()),2)

    def test_child_and_adult_map_variants_choose_matching_era(self):
        row=next(r for r in CATALOG['skulltulas'] if {p['age'] for p in r['variants']}=={'Child','Adult'} and any('_Child' in p['banc'] for p in r['variants']))
        self.assertIn('_Child',destination(row,'Child')['banc'])
        self.assertIn('_Adult',destination(row,'Adult')['banc'])
        child_only=next(r for r in CATALOG['skulltulas'] if {p['age'] for p in r['variants']}=={'Child'})
        self.assertEqual(destination(child_only,'Adult')['age'],'Child')
        for bean in BEANS.values():
            self.assertIn('_Child',destination(bean,'Child')['banc'])
            self.assertIn('_Adult',destination(bean,'Adult')['banc'])


class BeanTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch('collectibles.ROOT',Path(self.temp.name));p.start();self.addCleanup(p.stop)
        self.ids=list(BEANS);self.data={};self.calls=[];self.lose=False
        self.indices={r['plant_flag']['hash']:r['plant_flag']['index'] for r in BEANS.values()}
        self.addresses={r['plant_flag']['hash']:0x1000+i*24 for i,r in enumerate(BEANS.values())}
        for a in self.addresses.values():
            raw=bytearray(24);struct.pack_into('<I',raw,20,0xab12);self.data[a]=raw
        self.table=b''.join(struct.pack('<II',int(k,16),v) for k,v in self.indices.items())
        self.client=SimpleNamespace(read=self.read)
        self.binding=SimpleNamespace(client=self.client,validate=lambda:None,last_edit={'old':1},
            schema={'source_sha256':CATALOG['source_sha256']},indices={'Bool':self.indices},
            bool_desc={'address':0x100},read_chunks=lambda a,n:self.table,object=self.obj,session_id=('test',1))
        self.origin=dict(banc='HyruleCastle',age='Child',position=[1.,2.,3.],rotation=[0.,0.,0.],rotation_units='radians')
        self.scene=SimpleNamespace(validate=Mock(),fields=SimpleNamespace(capture=lambda:dict(self.origin)),
            _cas=self.cas,warp=Mock(return_value={'state':'arrived'}))
        p=patch('collectibles.TeleportTransport',return_value=self.scene);p.start();self.addCleanup(p.stop)
        self.beans=BeanState(self.binding)

    def obj(self,k,kind):a=self.addresses[k];return a,bytes(self.data[a])
    def read(self,a,n):
        if a==0x100:
            h=bytearray(40);struct.pack_into('<Q',h,24,0x200);struct.pack_into('<I',h,36,len(BEANS));return h
        raise ValueError('Unexpected read')
    def cas(self,row):
        self.calls.append(row)
        a=row['address']-20;old=struct.unpack_from('<I',self.data[a],20)[0]
        if old!=row['expected']:raise ValueError('Conflict')
        struct.pack_into('<I',self.data[a],20,row['value'])
        if self.lose:raise TimeoutError('Publication response lost')
    def audit(self):return json.loads(next(Path(self.temp.name).rglob('*.json')).read_text(encoding='utf-8'))

    def test_selected_patch_updates_only_its_two_values_preserving_metadata(self):
        result=self.beans.plant([self.ids[0]])
        self.assertEqual(result['state'],'applied');self.assertEqual(len(self.calls),1)
        self.assertEqual(self.calls[0]['value'],0x0101ab12)
        self.assertEqual(sum(self.beans.view().values()),1)
        self.scene.warp.assert_not_called();self.assertIsNone(self.binding.last_edit)

    def test_all_flags_written_before_single_current_area_refresh(self):
        self.origin['banc']=BEANS[self.ids[0]]['variants'][0]['banc']
        def warp(*args,**kw):
            self.assertEqual(len(self.calls),11)
            self.assertEqual(args[0],self.origin);self.assertTrue(kw['allow_any_era'])
            return {'state':'arrived'}
        self.scene.warp.side_effect=warp
        result=self.beans.plant(self.ids)
        self.assertEqual(sum(result['after'].values()),11)
        self.scene.warp.assert_called_once()

    def test_already_planted_skips_publication_and_reload(self):
        self.beans.plant([self.ids[0]]);self.calls.clear()
        result=self.beans.plant([self.ids[0]])
        self.assertEqual(result['writes'],[]);self.assertEqual(self.calls,[])

    def test_lost_response_never_replays_rolls_back_or_reloads(self):
        self.lose=True
        with self.assertRaises(TimeoutError):self.beans.plant(self.ids)
        self.assertEqual(len(self.calls),1);self.assertEqual(sum(self.beans.view().values()),1)
        self.scene.warp.assert_not_called()
        self.assertEqual(self.audit()['state'],'partial-or-uncertain-no-retry')

    def test_unknown_ids_busy_game_and_bad_lookup_refused_before_writes(self):
        for ids in ([],[self.ids[0],self.ids[0]],['unrelated flag'],[[]]):
            with self.assertRaises(ValueError):self.beans.plant(ids)
        self.scene.validate.side_effect=ValueError('Event active')
        with self.assertRaises(ValueError):self.beans.plant([self.ids[0]])
        self.scene.validate.side_effect=None;self.table=b'\0'*len(self.table)
        with self.assertRaises(ValueError):self.beans.plant([self.ids[0]])
        self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()
