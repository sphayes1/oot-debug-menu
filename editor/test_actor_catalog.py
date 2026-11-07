"""Catalogue query boundaries, exact instances, era guards and warp dispatch."""
import json,sqlite3,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from actor_catalog import ActorCatalog,restrictions,destination,PAGE_SIZE,area_age
from research.build_actor_catalog import SCHEMA


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'catalog.sqlite3';db=sqlite3.connect(self.path)
        db.executescript(SCHEMA)
        db.executemany('INSERT INTO meta VALUES(?,?)',[('version','1'),('game_revision','revision')])
        names=('Obj_Box','Obj_Box_100%','Obj_BeanLeaf','Obj_NoPosition','Obj_Conflict')
        for name in names:
            db.execute('INSERT INTO actors VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (name,name,name.lower(),1,'logic','GameActor','dynamic-contact-match',int(name=='Obj_Box'),0,1,'[]','pack','sha'))
        rows=[(1,'Obj_Box','18446744073709551615','HyruleField_Child','Child','',True),
              (2,'Obj_Box','18446744073709551615','HyruleField_Adult','Adult','',True),
              (3,'Obj_NoPosition','3','KokiriForest_Child','Child','',False),
              (4,'Obj_Conflict','4','HyruleField_Adult','Adult','Child',True)]
        rows += [(10+i,'Obj_Box_100%',str(i),'HyruleCastle','','Child',True) for i in range(PAGE_SIZE+2)]
        for key,actor,actor_hash,area,map_age,spawn_age,has in rows:
            db.execute('INSERT INTO placements VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (key,actor,actor_hash,area,1. if has else None,2. if has else None,3. if has else None,.25,
                 int(has),1,map_age,spawn_age,'{}','{}','source'+str(key),'sha'))
        db.executemany('INSERT INTO areas VALUES(?)',[(a,) for a in sorted({r[3] for r in rows})])
        db.execute('UPDATE actors SET placement_count=(SELECT count(*) FROM placements WHERE placements.actor=actors.id)')
        db.commit();db.close();self.catalog=ActorCatalog(self.path)

    def test_search_escapes_sql_wildcards_and_keeps_unplaced_definitions(self):
        self.assertEqual([r['id'] for r in self.catalog.actors('100%')],['Obj_Box_100%'])
        self.assertEqual(self.catalog.actors("' OR 1=1 --"),[])
        self.assertEqual(len(self.catalog.actors(placed_only=False)),5)
        self.assertIn('Obj_BeanLeaf',[r['id'] for r in self.catalog.actors(age='Adult',placed_only=False)])
        self.assertNotIn('Obj_BeanLeaf',[r['id'] for r in self.catalog.actors()])
        self.assertEqual(self.catalog.actors(candidate=1)[0]['id'],'Obj_Box')

    def test_era_and_area_filters_include_neutral_maps_with_correct_presence(self):
        self.assertEqual(area_age('HyruleCastle'),'Child')
        self.assertEqual(area_age('DinolfosStage'),'Adult')
        self.assertEqual(area_age('ForestTemple'),'')
        child=self.catalog.placements('Obj_Box',age='Child')['rows']
        adult=self.catalog.placements('Obj_Box',age='Adult')['rows']
        self.assertEqual([r['id'] for r in child],[1]);self.assertEqual([r['id'] for r in adult],[2])
        self.assertEqual(self.catalog.placements('Obj_Box_100%',age='Adult')['count'],0)
        self.assertEqual(self.catalog.placements('Obj_Box_100%',area='HyruleCastle',age='Child')['count'],27)
        self.assertEqual(self.catalog.placements('Obj_Conflict',age='Child')['count'],0)
        self.assertEqual(self.catalog.placements('Obj_Conflict',age='Adult')['count'],0)

    def test_pages_preserve_exact_instances_and_clamp_after_filter_changes(self):
        page=self.catalog.placements('Obj_Box_100%',page=1)
        self.assertEqual(page['count'],27);self.assertEqual(len(page['rows']),2)
        self.assertEqual(self.catalog.placements('Obj_Box',page=99)['page'],0)
        a,b=self.catalog.placement(1),self.catalog.placement(2)
        self.assertEqual(a['actor_hash'],b['actor_hash']);self.assertNotEqual(a['id'],b['id'])
        with self.assertRaises(ValueError):self.catalog.placement('1')
        with self.assertRaises(ValueError):self.catalog.placement(999)

    def test_pose_uses_exact_anchor_plus_height_and_era_override_preserves_age(self):
        row=self.catalog.placement(2)
        with self.assertRaisesRegex(ValueError,'Adult'):destination(row,'Child')
        pose=destination(row,'Child',3.,True)
        self.assertEqual(pose['position'],[1.,5.,3.]);self.assertEqual(pose['rotation'],[0.,.25,0.])
        self.assertEqual(pose['age'],'Child');self.assertEqual(pose['actor_id'],'18446744073709551615')
        for height in (float('nan'),float('inf'),-1,101,True):
            with self.assertRaises(ValueError):destination(row,'Adult',height)
        with self.assertRaisesRegex(ValueError,'explicit'):destination(self.catalog.placement(3),'Child')
        row['known_area']=0
        self.assertIn('not supported',restrictions(row,'Adult',True))

    def test_teleport_rechecks_live_age_and_revision_before_native_dispatch(self):
        binding=SimpleNamespace(validate=Mock(),schema={'source_sha256':'revision'},last_edit={'old':1},
            assignments=SimpleNamespace(view=lambda:{'active_age':'Adult'}))
        with patch('teleport.TeleportTransport') as cls:
            self.catalog.teleport(binding,2,2.,False)
            args,kw=cls.return_value.warp.call_args
            self.assertEqual(args[0]['position'],[1.,4.,3.]);self.assertEqual(args[1],'revision')
            self.assertFalse(kw['allow_any_era']);self.assertIsNone(binding.last_edit)
            cls.reset_mock();binding.schema['source_sha256']='wrong'
            with self.assertRaisesRegex(ValueError,'revision'):self.catalog.teleport(binding,2)
            cls.assert_not_called()
        binding.schema['source_sha256']='revision'
        with patch('teleport.TeleportTransport') as cls:
            with self.assertRaisesRegex(ValueError,'Child'):self.catalog.teleport(binding,1)
            cls.assert_not_called()


if __name__=='__main__':unittest.main()
