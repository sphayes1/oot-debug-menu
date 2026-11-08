"""Camera transforms and guards against cross-session or conflicting requests."""
import math
import json
import struct
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from camera import Camera, FLAG, SENTINEL, fly, look_at, view_pose


class CameraTests(unittest.TestCase):
    def test_camera_mailboxes_are_scalar_unsaved_fields(self):
        schema = json.loads((Path(__file__).parent/'data/gamedata-schema.json').read_text())
        for key, kind in ((FLAG, 'String64'), ('527fa715', 'Vector3'), ('1662143e', 'Vector3')):
            rows = [row for row in schema if row['hash'] == key]
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]['type'], rows[0]['save_index'], rows[0]['array_size']), (kind, -1, 0))

    def test_view_pose_inverts_a_translated_camera(self):
        pose = view_pose([1, 0, 0, -10, 0, 1, 0, -20, 0, 0, 1, -30])
        self.assertEqual(pose['eye'], [10, 20, 30])
        self.assertAlmostEqual(abs(pose['yaw']), math.pi)
        self.assertAlmostEqual(look_at(**pose)[2], 20)

    def test_camera_rejects_loading_and_corrupt_matrices(self):
        for matrix in ([0]*12, [float('nan')]*12,
                       [1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0]):
            with self.assertRaises(ValueError):
                view_pose(matrix)

    def test_flight_is_relative_to_view_and_limits_pitch(self):
        pose = dict(eye=[0., 0., 0.], yaw=0., pitch=0.)
        self.assertEqual(fly(pose, forward=1, distance=10)['eye'], [0., 0., 10.])
        self.assertEqual(fly(pose, side=1, distance=10)['eye'], [-10., 0., 0.])
        diagonal = fly(pose, side=1, forward=1, distance=10)
        self.assertAlmostEqual(math.dist(diagonal['eye'], pose['eye']), 10, places=5)
        self.assertAlmostEqual(fly(pose, dy=1e6)['pitch'], -math.radians(89))
        with self.assertRaises(ValueError):
            look_at([0, 0, 0], 0, float('nan'))

    def make_camera(self):
        camera = Camera.__new__(Camera)
        camera.active = True
        camera.session_id = (1, 'first')
        camera.previous = ([1, 2, 3], [4, 5, 6])
        camera.area = 'HyruleField_Adult'
        camera.pose = dict(eye=[10, 20, 30], yaw=0, pitch=0)
        camera.binding = SimpleNamespace(session=Mock(return_value=camera.session_id), validate=Mock())
        camera.fields = SimpleNamespace(field=Mock(return_value=SENTINEL),
            capture=Mock(return_value={'banc': camera.area}))
        camera.scene = SimpleNamespace(validate=Mock())
        camera._vector = Mock()
        camera._flag = Mock()
        return camera

    def test_old_session_never_clears_a_new_games_mailbox(self):
        camera = self.make_camera()
        camera.binding.session.return_value = (2, 'new')
        camera.disable()
        camera.binding.validate.assert_not_called()
        camera._flag.assert_not_called()
        camera._vector.assert_not_called()
        self.assertFalse(camera.active)

    def test_disable_does_not_touch_a_foreign_song_or_entrance(self):
        camera = self.make_camera()
        camera.fields.field.return_value = 'ZeldasLullaby'
        camera.disable()
        camera._flag.assert_not_called()
        camera._vector.assert_not_called()

    def test_disable_clears_own_flag_before_restoring_payloads(self):
        camera = self.make_camera()
        calls = Mock()
        calls.attach_mock(camera._flag, 'flag')
        calls.attach_mock(camera._vector, 'vector')
        camera.disable()
        self.assertEqual(calls.mock_calls[0].args, (SENTINEL, ''))
        self.assertEqual(len(calls.mock_calls), 3)
        self.assertFalse(camera.active)

    def test_camera_yields_when_area_or_event_changes(self):
        for reason in ('area', 'event'):
            camera = self.make_camera()
            if reason == 'area':
                camera.fields.capture.return_value = {'banc': 'Market_Adult'}
            else:
                camera.scene.validate.side_effect = ValueError('Event started')
            with self.assertRaises(ValueError):
                camera.check()
            camera._flag.assert_called_once_with(SENTINEL, '')
            self.assertFalse(camera.active)

    def test_foreign_mailbox_stops_flight_without_clearing_it(self):
        camera = self.make_camera()
        camera.fields.field.return_value = 'MainEntrance'
        with self.assertRaises(ValueError):
            camera.check()
        self.assertFalse(camera.active)
        camera._flag.assert_not_called()

    def test_unacknowledged_cas_is_never_retried(self):
        camera = self.make_camera()
        camera.client = SimpleNamespace(compare_write=Mock(return_value={'swapped': True, 'readback_matches': False}))
        with self.assertRaises(ValueError):
            Camera._cas(camera, 0x100, 1, 2)
        camera.client.compare_write.assert_called_once()

    def test_flag_publishes_first_word_last_and_preserves_wrapper(self):
        camera = self.make_camera()
        del camera._flag
        raw = bytearray(264)
        struct.pack_into('<Q', raw, 104, 0x100+116)
        struct.pack_into('<I', raw, 112, 64)
        camera.fields.object = Mock(return_value=(0x100, raw))
        camera._cas = Mock()
        camera._flag('', SENTINEL)
        self.assertEqual(camera._cas.call_args_list[-1].args[0], 0x100+116)
        self.assertTrue(all(0x100+116 <= c.args[0] < 0x100+180 for c in camera._cas.call_args_list))
        raw[116:180] = SENTINEL.encode().ljust(64, b'\0')
        camera._cas.reset_mock()
        camera._flag(SENTINEL, '')
        self.assertEqual(camera._cas.call_args_list[0].args[0], 0x100+116)
        with self.assertRaises(ValueError):
            camera._flag('some other owner', '')

    def test_teleport_uses_observed_camera_not_a_stale_draft(self):
        camera = self.make_camera()
        camera.read = Mock(return_value={'eye': [10.01, 20, 30]})
        with patch('camera.PositionTransport') as transport:
            camera.teleport()
            transport.return_value.move.assert_called_once_with([10.01, 20, 30], expected_area=camera.area)
        camera.read.return_value = {'eye': [50, 20, 30]}
        with patch('camera.PositionTransport') as transport:
            with self.assertRaises(ValueError):
                camera.teleport()
            transport.assert_not_called()


if __name__ == '__main__':
    unittest.main()
