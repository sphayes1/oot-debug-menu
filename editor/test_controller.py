"""Controller defaults, customization, analog flight and guarded action dispatch."""
import math
import json
from pathlib import Path
import tempfile
import queue
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from controller import ACTIONS, BUTTONS, DEFAULT, chord, controller_flight, mask, radial, validate_config
from controller import Controller,next_event
from controller_ui import ControllerPanel
from camera_ui import CameraPanel


class ControllerTests(unittest.TestCase):
    def config(self):return validate_config(DEFAULT)

    def test_default_chords_match_requested_switch_mapping(self):
        c=self.config()['bindings']
        self.assertEqual(c['enter'],['L','Minus'])
        self.assertEqual(c['exit'],['B']);self.assertEqual(c['teleport'],['A'])
        self.assertEqual(c['save'],['L','R','ZL','ZR','Left'])
        self.assertEqual(c['load'],['L','R','ZL','ZR','Right'])
        self.assertEqual(mask(c['save']),(15<<6)|(1<<12))

    def test_custom_bindings_and_defaults_are_independent(self):
        c=self.config();c['bindings']['enter']=['StickL','StickR']
        self.assertEqual(validate_config(c)['bindings']['enter'],['StickL','StickR'])
        self.assertEqual(DEFAULT['bindings']['enter'],['L','Minus'])

    def test_duplicate_subset_and_empty_chords_are_rejected(self):
        for combo in ([],['B'],['B','Minus'],['A','A'],['Unknown']):
            c=self.config();c['bindings']['enter']=combo
            with self.assertRaises(ValueError):validate_config(c)

    def test_axis_options_are_guarded(self):
        for field,value in [('deadzone',float('nan')),('look_speed',float('inf')),
                            ('move_stick','right'),('up','B'),('down','ZR')]:
            c=self.config();c[field]=value
            with self.assertRaises(ValueError):validate_config(c)

    def test_radial_deadzone_removes_drift_and_limits_diagonal(self):
        self.assertEqual(radial(.1,.1,.18),(0.,0.))
        self.assertAlmostEqual(math.hypot(*radial(1.,1.,.18)),1.)

    def test_controller_sticks_move_look_and_height_without_keyboard_focus(self):
        pose=dict(eye=[0.,0.,0.],yaw=0.,pitch=0.)
        c=self.config();sample=dict(axes=[0,32767,32767,32767],buttons=mask(['ZR']))
        target=controller_flight(pose,sample,c,10.,.05)
        self.assertGreater(target['eye'][1],0)
        self.assertGreater(target['eye'][2],0)
        self.assertLess(target['yaw'],0);self.assertGreater(target['pitch'],0)
        sample=dict(axes=[0]*4,buttons=0)
        self.assertIsNone(controller_flight(pose,sample,c,10.,.05))

    def test_camera_teleport_restores_view_only_after_success(self):
        panel=CameraPanel.__new__(CameraPanel)
        panel.camera=SimpleNamespace(teleport=Mock(return_value={'state':'applied'}),disable=Mock())
        panel.editor=SimpleNamespace(binding=SimpleNamespace(last_edit='edit'))
        panel.desired='old';panel.dirty=True
        calls=Mock();calls.attach_mock(panel.camera.teleport,'teleport');calls.attach_mock(panel.camera.disable,'disable')
        result=panel.teleport()
        self.assertEqual([c[0] for c in calls.mock_calls],['teleport','disable'])
        self.assertIsNone(result['pose']);self.assertFalse(panel.dirty)
        panel.camera.disable.reset_mock();panel.camera.teleport.side_effect=ValueError('not applied')
        with self.assertRaises(ValueError):panel.teleport()
        panel.camera.disable.assert_not_called()

    def panel(self):
        p=ControllerPanel.__new__(ControllerPanel)
        cam=SimpleNamespace(active=False)
        p.controller=SimpleNamespace(complete=Mock())
        p.editor=SimpleNamespace(camera_panel=SimpleNamespace(camera=cam,set_enabled=Mock(),stop=Mock(),teleport=Mock()),
                                 hotkeys_panel=SimpleNamespace(perform=Mock()))
        return p

    def test_controller_save_uses_existing_confirmation_skipping_action(self):
        p=self.panel();p.editor.camera_panel.camera.active=True
        p.editor.camera_panel.stop.side_effect=lambda:setattr(p.editor.camera_panel.camera,'active',False)
        p.job('save',5)
        p.editor.camera_panel.stop.assert_called_once()
        p.editor.hotkeys_panel.perform.assert_called_once_with('save')
        p.controller.complete.assert_called_once_with(5,False)

    def test_failure_still_completes_capture_request(self):
        p=self.panel();p.editor.camera_panel.set_enabled.side_effect=ValueError('loading')
        with self.assertRaises(ValueError):p.job('enter',2)
        p.controller.complete.assert_called_once_with(2,False)

    def test_controller_settings_persist_and_invalid_edit_does_not_overwrite(self):
        c=Controller.__new__(Controller)
        with tempfile.TemporaryDirectory() as folder, patch('controller.ROOT',Path(folder)):
            spec=self.config();spec['bindings']['enter']=['StickL','StickR']
            c.apply(spec)
            path=Path(folder)/'controller-hotkeys.json'
            self.assertEqual(json.loads(path.read_text())['bindings']['enter'],['StickL','StickR'])
            before=path.read_bytes();spec['bindings']['save']=spec['bindings']['load']
            with self.assertRaises(ValueError):c.apply(spec)
            self.assertEqual(path.read_bytes(),before)

    def test_recording_survives_popup_losing_focus_to_game(self):
        panel=ControllerPanel.__new__(ControllerPanel)
        panel.listening='enter';panel.controller=SimpleNamespace(recording=True)
        with patch('controller_ui.imgui.button',return_value=False), patch('controller_ui.imgui.begin_popup',return_value=False):
            panel.draw()
        self.assertEqual(panel.listening,'enter')
        self.assertTrue(panel.controller.recording)

    def test_finishing_up_binding_saves_and_activates_it_without_second_apply(self):
        panel=ControllerPanel.__new__(ControllerPanel)
        panel.controller=Controller.__new__(Controller)
        panel.controller.config=self.config()
        panel.draft=self.config();panel.draft['bindings']['enter']=['Up']
        panel.editing='enter';panel.feedback=''
        with tempfile.TemporaryDirectory() as folder, patch('controller.ROOT',Path(folder)):
            panel.finish_editing()
            saved=json.loads((Path(folder)/'controller-hotkeys.json').read_text())
        self.assertEqual(saved['bindings']['enter'],['Up'])
        self.assertEqual(panel.controller.config['bindings']['enter'],['Up'])
        self.assertIsNone(panel.editing)
        self.assertEqual(panel.draft,panel.controller.config)

    def test_failed_binding_save_keeps_editor_open_and_old_binding_active(self):
        for error in (ValueError('Overlapping shortcut'),OSError('Disk write failed')):
            panel=ControllerPanel.__new__(ControllerPanel)
            old=self.config()
            panel.controller=SimpleNamespace(config=old,apply=Mock(side_effect=error))
            panel.draft=self.config();panel.draft['bindings']['enter']=['Up']
            panel.editing='enter';panel.feedback=''
            panel.finish_editing()
            self.assertEqual(panel.editing,'enter')
            self.assertEqual(panel.controller.config,old)
            self.assertIn('not saved',panel.feedback)

    def test_late_completion_from_old_emulator_cannot_acknowledge_new_action(self):
        c=Controller.__new__(Controller);c.completions=queue.Queue();c.context_value=((2,'new'),True,False)
        c.complete(1,False,(1,'old'))
        c.complete(2,False,(2,'new'))
        self.assertEqual(c.take_completion((2,'new')),(2,False,(2,'new')))
        self.assertIsNone(c.take_completion((2,'new')))

    def test_held_chord_does_not_repeat_and_renewed_lease_can_deliver_first_action(self):
        self.assertEqual(next_event(dict(sequence=1,action=0),0),(1,'enter'))
        self.assertEqual(next_event(dict(sequence=1,action=0),1),(1,None))
        seen,action=next_event(dict(sequence=0,action=-1),1)
        self.assertEqual((seen,action),(0,None))
        self.assertEqual(next_event(dict(sequence=1,action=1),seen),(1,'exit'))


if __name__=='__main__':unittest.main()
