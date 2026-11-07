"""Native song dispatch: whitelist, publication ordering and uncertain responses."""
import json,struct,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from songs import Songs,SONGS,REQUEST,string_plan


class SongTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=patch('songs.ROOT',Path(self.temp.name));self.root.start();self.addCleanup(self.root.stop)
        self.data=bytearray(0x1000);self.calls=[];self.presents=0;self.lose=False;self.fail_at=None
        self.address=0x100;self.flag=0x300;self.key=next(iter(SONGS))
        for offset in (24,104,184):struct.pack_into('<QI',self.data,self.address+offset,self.address+offset+12,64)
        struct.pack_into('<I',self.data,self.flag+20,0x7a12)
        self.indices={s['hash']:s['index'] for s in SONGS.values()}
        self.objects={s['hash']:0x500+i*24 for i,s in enumerate(SONGS.values())}
        self.objects[REQUEST]=self.flag
        def obj(key,kind):
            a=self.objects[key];return a,bytes(self.data[a:a+24])
        self.binding=SimpleNamespace(client=self,validate=lambda:None,session_id=('test',1),
            indices={'Bool':self.indices},object=obj,last_edit={'old':True})
        self.songs=Songs(self.binding);self.songs.validate=lambda:None
        self.songs.fields=SimpleNamespace(object=lambda *args:(self.address,self.read(self.address,264)))
        self.songs.transport=SimpleNamespace(_cas=self.cas,boolean=lambda key:bool(self.data[self.flag+22]))

    def read(self,a,n):return bytes(self.data[a:a+n])
    def status(self):self.presents+=1;return {'presents':self.presents}
    def compare_write(self,a,old,new):
        self.calls.append((a,old,new))
        if len(self.calls)==self.fail_at:return {'swapped':False}
        if struct.unpack_from('<I',self.data,a)[0]!=old:return {'swapped':False}
        struct.pack_into('<I',self.data,a,new)
        if a==self.flag+20:
            if self.lose:raise TimeoutError('Lost native publication response')
            self.data[self.flag+22]=0
            target=self.objects[SONGS[self.key]['hash']]
            self.data[target+22:target+24]=b'\1\1'
        return {'swapped':True,'readback_matches':True}
    def cas(self,row):
        r=self.compare_write(row['address'],row['expected'],row['value'])
        if not r.get('swapped'):raise ValueError('Conflict')
    def audit(self):return json.loads(next(Path(self.temp.name).rglob('*.json')).read_text(encoding='utf-8'))

    def test_native_grant_payload_precedes_single_flag_and_cleans_only_own_string(self):
        before=bytes(self.data[self.address:self.address+264])
        result=self.songs.learn([self.key]);self.assertEqual(result['songs'][0]['state'],'learned')
        flag=[c for c in self.calls if c[0]==self.flag+20]
        self.assertEqual(flag,[(self.flag+20,0x7a12,0x17a12)])
        flag_i=self.calls.index(flag[0]);prefix=self.address+116
        self.assertEqual(self.calls[flag_i-1][0],prefix)
        self.assertTrue(all(prefix<=a<prefix+64 for a,_,_ in self.calls if a!=self.flag+20))
        self.assertEqual(self.read(self.address,264),before)
        self.assertIsNone(self.binding.last_edit)

    def test_uncertain_publication_never_replays_or_clears_payload(self):
        self.lose=True
        with self.assertRaises(TimeoutError):self.songs.learn([self.key])
        self.assertEqual(sum(a==self.flag+20 for a,_,_ in self.calls),1)
        self.assertEqual(self.read(self.address+116,64).split(b'\0')[0],self.key.encode())
        self.assertEqual(self.calls[-1][0],self.flag+20)
        self.assertEqual(self.audit()['state'],'uncertain-no-retry')

    def test_preparation_conflict_rolls_back_without_native_action(self):
        self.fail_at=2
        with self.assertRaises(ValueError):self.songs.learn([self.key])
        self.assertFalse(any(a==self.flag+20 for a,_,_ in self.calls))
        self.assertEqual(self.read(self.address+116,64),bytes(64))

    def test_known_song_skips_native_action_and_unknown_or_custom_rejected(self):
        a=self.objects[SONGS[self.key]['hash']];self.data[a+22:a+24]=b'\1\1'
        self.assertEqual(self.songs.learn([self.key])['songs'][0]['state'],'already-learned')
        for ids in ([],['ScarecrowSong'],['arbitrary actor'],[self.key,self.key],False):
            with self.assertRaises(ValueError):self.songs.learn(ids)
        self.assertEqual(self.calls,[])

    def test_busy_payload_or_bad_wrapper_refused(self):
        raw=bytearray(self.read(self.address,264));raw[116]=65
        with self.assertRaises(ValueError):string_plan(self.address,raw,self.key)
        raw[116]=0;raw[112]=63
        with self.assertRaises(ValueError):string_plan(self.address,raw,self.key)

    def test_indices_and_non_boolean_song_state_refused(self):
        self.indices[SONGS[self.key]['hash']]=-1
        with self.assertRaises(ValueError):self.songs.view()
        self.indices[SONGS[self.key]['hash']]=SONGS[self.key]['index']
        self.data[self.objects[SONGS[self.key]['hash']]+22]=2
        with self.assertRaises(ValueError):self.songs.view()


if __name__=='__main__':unittest.main()
