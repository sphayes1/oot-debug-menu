"""External optimized profiles cannot leak into a mainline package."""
import base64,hashlib,json,tempfile,unittest,sys
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.apply_profile import apply_profile

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.spec=self.root/'profile.json';self.dest=self.root/'load'
        self.nup=Mock();self.nup.read.return_value=b'original'

    def write(self,value):self.spec.write_text(json.dumps(value))

    def test_mainline_rejects_performance_files_and_environment_before_writes(self):
        for extra in ({'files':[{}]},{'environment':{'EDEN_NX2_TEST':'1'}},{'configuration':'[Renderer]\nresolution_setup=2'}):
            self.write(dict(variant='mainline',**extra))
            with self.assertRaises(ValueError):apply_profile(self.nup,self.spec,self.dest)
            self.assertFalse(self.dest.exists());self.nup.read.assert_not_called()

    def test_optimized_recipe_reconstructs_only_verified_changes(self):
        result=b'orig-new'
        self.write(dict(variant='optimized',files=[dict(member='romfs/example',source_sha256=hashlib.sha256(b'original').hexdigest(),
            output='Optional profile/example',ops=[{'copy':[0,4]},{'data':base64.b64encode(b'-new').decode()}],result_sha256=hashlib.sha256(result).hexdigest())]))
        self.assertEqual(apply_profile(self.nup,self.spec,self.dest),1)
        self.assertEqual((self.dest/'Optional profile/example').read_bytes(),result)

    def test_wrong_source_or_result_hash_never_publishes(self):
        for source,result in (('bad',hashlib.sha256(b'original').hexdigest()),(hashlib.sha256(b'original').hexdigest(),'bad')):
            self.write(dict(variant='optimized',files=[dict(member='romfs/example',source_sha256=source,output='test',ops=[{'copy':[0,8]}],result_sha256=result)]))
            with self.assertRaises(ValueError):apply_profile(self.nup,self.spec,self.dest)
            self.assertFalse(self.dest.exists())

    def test_output_path_cannot_escape_selected_profile(self):
        self.write(dict(variant='optimized',files=[dict(output='../escape',data='eA==',result_sha256=hashlib.sha256(b'x').hexdigest())]))
        with self.assertRaises(ValueError):apply_profile(self.nup,self.spec,self.dest)
        self.assertFalse((self.root/'escape').exists())

if __name__=='__main__':unittest.main()
