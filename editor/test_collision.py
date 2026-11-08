"""Collision format bounds, projection alignment and read-only session guards."""
import json
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from collision import CollisionReader, projection_matrix
from collision_geometry import TagFile, box, place, sections, varint
from collision_overlay import viewport
from collision_scene import SceneSource

PROJECTION = [1.2062849, 0, 0, 0, 0, 2.1445067, 0, 0, 0, 0, -1.000008, -.2000008, 0, 0, -1, 0]


class CollisionTests(unittest.TestCase):
    def mesh(self):
        data = bytearray(1024)
        # One section: one quad, four quantized vertices and one material run.
        struct.pack_into('<iI', data, 0x88, 0x100-0x88, 1)
        struct.pack_into('<iI', data, 0x60, 0x250-0x60, 1)
        struct.pack_into('<iI', data, 0x108, 0x200-0x108, 1)
        struct.pack_into('<iI', data, 0x110, 0x220-0x110, 4)
        struct.pack_into('<3i', data, 0x120, 512, 1024, 1536)
        struct.pack_into('<4B', data, 0x200, 0, 1, 2, 3)
        struct.pack_into('<12H', data, 0x220, 0, 0, 0, 512, 0, 0, 512, 512, 0, 0, 512, 0)
        struct.pack_into('<II', data, 0x250, 0, 27)
        tag = TagFile.__new__(TagFile)
        tag.data, tag.begin, tag.end = data, 0, len(data)
        tag.items, tag.cache = {0: ('hknpMeshShape', 1)}, {}
        return tag

    def test_quantized_quad_and_shape_tag_decode(self):
        tr, tags = self.mesh().shape()
        self.assertEqual(tr.shape, (2, 3, 3))
        np.testing.assert_equal(tr[0], ((1, 2, 3), (2, 2, 3), (2, 3, 3)))
        np.testing.assert_equal(tr[1], ((1, 2, 3), (2, 3, 3), (1, 3, 3)))
        self.assertEqual(list(tags), [27, 27])

    def test_out_of_bounds_relative_geometry_is_refused(self):
        t = self.mesh()
        struct.pack_into('<iI', t.data, 0x110, 100000, 4)
        with self.assertRaisesRegex(ValueError, 'outside DATA'):
            t.shape()

    def test_nested_compound_does_not_replace_top_level_instance_count(self):
        t = TagFile.__new__(TagFile)
        t.data, t.begin, t.end = bytearray(2048), 0, 2048
        t.items = {0x100: ('hkFreeListArrayElement', 2), 0x400: ('hkFreeListArrayElement', 1),
                   0x500: ('hknpCompoundShape', 1)}
        struct.pack_into('<iI', t.data, 0, 0x100, 2)
        struct.pack_into('<iI', t.data, 0x300, 0x100, 1)
        for p in (0x130, 0x170):
            struct.pack_into('<iI', t.data, p, 0x500-p, 0)
        def nested(*_):
            list(t.instances(0x300, 1))
            return np.empty((0, 3, 3)), np.empty(0)
        t.shape = nested
        list(t.instances())
        self.assertEqual((t.instance_count, t.instance_offset), (2, 0x100))

    def test_truncated_and_nonadvancing_sections_are_refused(self):
        for data in (b'\0'*8, struct.pack('>I4s', 100, b'DATA')):
            with self.assertRaises(ValueError):
                list(sections(data, 0, len(data)))
        with self.assertRaises(ValueError):
            varint(b'\x81', 0, 1)

    def test_scene_transform_preserves_scale_rotation_translation(self):
        actor = dict(Scale=[2, 1, 1], Rotate=[0, np.pi/2, 0], Translate=[10, 20, 30])
        tr = place(np.asarray([[[1, 0, 0]]*3]), actor)
        np.testing.assert_allclose(tr[0, 0], (10, 20, 28), atol=1e-5)
        self.assertEqual(box().shape, (12, 3, 3))

    def test_projection_and_letterboxing(self):
        self.assertEqual(projection_matrix(PROJECTION), PROJECTION)
        self.assertEqual(viewport((10, 20, 1000, 1000), 16/9), (10, 239, 1000, 562))
        for p in ([0]*16, [float('nan')]*16, PROJECTION[:14]+[0, 0]):
            with self.assertRaises(ValueError):
                projection_matrix(p)

    def binding(self):
        base, manager, address = 0x10000000, 0x20000000, 0x20010000
        matrix = [1, 0, 0, -10, 0, 1, 0, -20, 0, 0, 1, -30]
        raw = bytearray(0xe0)
        struct.pack_into('<12f', raw, 0, *matrix)
        struct.pack_into('<16f', raw, 0xa0, *PROJECTION)
        obj = bytearray(264);obj[:8] = b'TYPEAREA'
        struct.pack_into('<QI', obj, 104, address+116, 64)
        obj[116:128] = b'Market_Adult'
        memory = {base+0x4c7dda0: struct.pack('<Q', base+0x4e371e8),
                  base+0x4e371e8: struct.pack('<Q', manager),
                  manager: struct.pack('<Q', base+0x4b73d20),
                  manager+0x3ab0: bytes(raw), address: bytes(obj)}
        client = SimpleNamespace(read=Mock(side_effect=lambda at, n: memory[at][:n]))
        binding = SimpleNamespace(validate=Mock(), session_id=(1, 'first'), session=Mock(return_value=(1, 'first')),
            bool_desc={'vtable': base+0x4c20658}, assignments=SimpleNamespace(heap=(manager, manager+0x20000)),
            object=Mock(return_value=(0, bytes(32))), client=client)
        reader = CollisionReader(binding)
        reader.fields = SimpleNamespace(object=Mock(return_value=(address, bytes(obj))))
        return reader

    def test_live_snapshot_is_read_only_and_detects_session_change(self):
        r = self.binding()
        self.assertEqual(r.read()['eye'], [10, 20, 30])
        self.assertEqual(r.read()['scene'], 'Market_Adult')
        r.binding.session.return_value = (2, 'new')
        with self.assertRaisesRegex(ValueError, 'session changed'):
            r.read()
        self.assertFalse(hasattr(r.binding.client, 'compare_write'))

    def test_foreign_camera_and_invalid_inline_area_pointer_are_refused(self):
        r = self.binding()
        r.binding.assignments.heap = (1, 2)
        with self.assertRaisesRegex(ValueError, 'manager changed'):
            r.read()
        r = self.binding()
        original = r.binding.client.read.side_effect
        def corrupt(at, n):
            raw = original(at, n)
            return raw[:104]+bytes(12)+raw[116:] if n == 180 else raw
        r.binding.client.read.side_effect = corrupt
        with self.assertRaisesRegex(ValueError, 'area object changed'):
            r.read()

    def test_loading_suppresses_collision(self):
        r = self.binding()
        r.binding.object.return_value = (0, bytes(22)+b'\1'+bytes(9))
        self.assertTrue(r.read()['waiting'])

    def test_tiled_selection_tracks_camera_without_loading_whole_field(self):
        s = SceneSource.__new__(SceneSource)
        s.tiles = {'Field': ([(f'{x},{z}', (x, z)) for x in range(16) for z in range(16)], (-2000, -2000))}
        key, members = s.selection('Field', (0, 50, 0), 100)
        self.assertEqual(len(members), 4)
        self.assertNotEqual(key, s.selection('Field', (1000, 50, 1000), 100)[0])
        self.assertEqual(key, s.selection('Field', (1, 60, 1), 100)[0])
        with self.assertRaises(ValueError):
            s.selection('../save', (0, 0, 0), 100)

    def test_collision_reads_do_not_stop_free_camera(self):
        from app import Editor
        e = Editor.__new__(Editor)
        e.camera_panel = SimpleNamespace(camera=SimpleNamespace(active=True), stop=Mock())
        e.future, e.pending = None, []
        e.worker = SimpleNamespace(submit=Mock(side_effect=lambda job: job()))
        read = Mock(return_value='snapshot')
        e.submit('Collision snapshot', read)
        read.assert_called_once()
        e.camera_panel.stop.assert_not_called()

    def test_continuous_collision_reads_do_not_starve_inventory_refresh(self):
        from app import Editor
        e = Editor.__new__(Editor)
        e.future = Mock()
        e.future.done.return_value = True
        e.future.result.return_value = dict(kind='collision', generation=1)
        e.collision_panel = SimpleNamespace(accept=Mock())
        e.operation, e.last_poll, e.pending, e.connected = 'Collision snapshot', 0., [], True
        e.submit, e.read_values = Mock(), Mock()
        e.pump()
        e.submit.assert_called_once_with('Refresh', e.read_values)

    def test_disabled_or_previous_generation_cannot_reopen_an_overlay(self):
        from collision_ui import CollisionPanel
        p = CollisionPanel.__new__(CollisionPanel)
        p.enabled, p.generation, p.snapshot = False, 3, None
        p.accept(dict(generation=3, snapshot={'scene': 'old'}))
        self.assertIsNone(p.snapshot)
        p.enabled = True
        p.accept(dict(generation=2, snapshot={'scene': 'old'}))
        self.assertIsNone(p.snapshot)


if __name__ == '__main__':
    unittest.main()
