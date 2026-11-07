import json
import math
from pathlib import Path
import tempfile
import unittest
from locations import LocationStore, validate_pose, presets

POSE = dict(banc='KokiriForest_Child', age='Child', position=[1, 2, 3], rotation=[0, 1, 0])


class LocationsTest(unittest.TestCase):
    def test_roundtrip_and_duplicate_names_keep_both(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocationStore(Path(directory) / 'locations.json')
            a = store.save('Home', POSE, 'revision1')
            b = store.save('Home', dict(POSE, position=[4, 5, 6]), 'revision1')
            self.assertNotEqual(a['id'], b['id'])
            self.assertEqual(len(store.read()), 2)
            self.assertEqual(store.read()[0]['pose']['position'], [1, 2, 3])

    def test_bad_coordinate_is_rejected_before_file_change(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocationStore(Path(directory) / 'locations.json')
            store.save('Home', POSE, 'revision1')
            before = store.path.read_bytes()
            for bad in (math.nan, math.inf, True, 1000001):
                with self.assertRaises(ValueError):
                    store.save('Bad', dict(POSE, position=[bad, 0, 0]), 'revision1')
            self.assertEqual(before, store.path.read_bytes())

    def test_corrupt_library_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'locations.json'
            path.write_text('{broken')
            with self.assertRaises(json.JSONDecodeError):
                LocationStore(path).save('Home', POSE, 'revision1')
            self.assertEqual(path.read_text(encoding='utf-8'), '{broken')

    def test_presets_have_finite_transforms(self):
        areas = presets()
        self.assertIn('HyruleField_Child', areas)
        self.assertIn('KakarikoVillage_Child', areas)
        for banc, entries in areas.items():
            for point in entries.values():
                validate_pose(dict(banc=banc, age='Adult' if '_Adult' in banc else 'Child',
                                   position=point['Trans'], rotation=point['Rot']))


if __name__ == '__main__':
    unittest.main()
