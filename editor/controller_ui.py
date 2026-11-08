"""Customizable controller actions, recording and focus-independent camera flight."""
import time
from imgui_bundle import imgui
from controller import ACTIONS, BUTTONS, DEFAULT, FRIENDLY, LABELS, Controller, chord, controller_flight, validate_config


class ControllerPanel:
    def __init__(self, editor):
        self.editor = editor
        self.controller = Controller()
        self.draft = validate_config(self.controller.config)
        self.editing = None
        self.listening = None
        self.recorded = set()
        self.record_started = 0.
        self.feedback = ''
        self.last_frame = time.monotonic()

    def job(self, action, sequence, session=None):
        e = self.editor
        try:
            if action == 'enter':
                return e.camera_panel.set_enabled(True)
            if action == 'exit':
                return e.camera_panel.set_enabled(False)
            if action == 'teleport':
                return e.camera_panel.teleport()
            if e.camera_panel.camera.active:
                e.camera_panel.stop()
            return e.hotkeys_panel.perform(action)
        finally:
            if session is None:
                self.controller.complete(sequence, e.camera_panel.camera.active)
            else:
                self.controller.complete(sequence, e.camera_panel.camera.active, session)

    def pump(self):
        e = self.editor
        now = time.monotonic()
        dt = min(.08, now-self.last_frame)
        self.last_frame = now
        session = e.binding.session_id if e.connected else None
        idle = not e.pending and (e.future is None or e.operation in ('Refresh', 'Camera flight', 'Collision snapshot'))
        self.controller.context(session, idle and not self.listening, e.camera_panel.camera.active)
        if hasattr(e, 'runner_params'):
            e.runner_params.fps_idling.fps_idle = 60 if e.camera_panel.camera.active or e.collision_panel.enabled else 20
        for action, sequence, event_session, stamp in self.controller.take():
            if not session or tuple(session) != event_session or now-stamp > 2 or self.listening:
                self.controller.complete(sequence, e.camera_panel.camera.active, event_session)
                continue
            e.submit('Camera controller '+action, lambda action=action, sequence=sequence, event_session=event_session: self.job(action, sequence, event_session))
        sample = self.controller.sample
        if self.listening:
            if sample and now-sample['at'] < .25:
                held = {b for i, b in enumerate(BUTTONS) if sample['buttons'] & (1 << i)}
                self.recorded.update(held)
                if not held and self.recorded:
                    self.draft['bindings'][self.listening] = [b for b in BUTTONS if b in self.recorded]
                    self.feedback = 'Recorded '+chord(self.draft['bindings'][self.listening])+'. Apply to save.'
                    self.cancel_recording()
            if now-self.record_started > 20:
                self.feedback = 'Recording timed out. Try again or select the buttons below.'
                self.cancel_recording()
        camera = e.camera_panel
        if (session and sample and sample.get('active') and tuple(sample['session']) == tuple(session)
                and now-sample['at'] < .25 and sample.get('action', -1) == -1
                and camera.camera.active and not self.listening):
            pose = camera.desired or camera.camera.pose
            if pose:
                target = controller_flight(pose, sample, self.controller.config, camera.speed, dt)
                if target:
                    camera.desired = target
                    camera.dirty = True
        # Flight also runs when another tab is selected / the game has focus.
        camera.flush()

    def cancel_recording(self):
        self.listening = None
        self.controller.recording = False
        self.recorded.clear()

    def draw(self):
        if imgui.button('Controller...'):
            imgui.open_popup('controller-shortcuts')
        if imgui.begin_popup('controller-shortcuts'):
            imgui.text('Controller camera and save shortcuts')
            _, self.draft['enabled'] = imgui.checkbox('Enable controller shortcuts', self.draft['enabled'])
            imgui.text_wrapped('Button names follow the emulator mapping: L = LB, R = RB, ZL = LT, ZR = RT. A/B follow the game labels. Shortcuts need game focus; camera input is consumed before it reaches Link.')
            for action in ACTIONS:
                imgui.push_id(action)
                imgui.text(LABELS[action]+': '+chord(self.draft['bindings'][action]))
                imgui.same_line()
                if imgui.small_button('Edit'):
                    self.cancel_recording();self.editing = action
                imgui.pop_id()
            if self.editing:
                imgui.separator_text('Edit '+LABELS[self.editing])
                if not self.listening:
                    imgui.begin_disabled(not self.editor.connected or not self.controller.config['enabled'])
                    if imgui.button('Record controller combination'):
                        self.listening = self.editing;self.record_started = time.monotonic()
                        self.recorded.clear();self.controller.recording = True
                    imgui.end_disabled()
                else:
                    imgui.text_wrapped('Click the game window, press the buttons together, then release them. Return here to Apply. Gameplay input is blocked while recording.')
                    if imgui.button('Cancel recording'):
                        self.cancel_recording()
                selected = self.draft['bindings'][self.editing]
                imgui.begin_disabled(bool(self.listening))
                for i, button in enumerate(BUTTONS):
                    if i % 4:
                        imgui.same_line()
                    changed, checked = imgui.checkbox(FRIENDLY.get(button, button), button in selected)
                    if changed:
                        if checked:selected.append(button)
                        else:selected.remove(button)
                if imgui.button('Done editing'):
                    self.editing = None
                imgui.end_disabled()
            imgui.separator_text('Camera flight')
            _, index = imgui.combo('Move stick', ('left', 'right').index(self.draft['move_stick']), ['Left stick', 'Right stick'])
            self.draft['move_stick'] = ('left', 'right')[index]
            self.draft['look_stick'] = ('right', 'left')[index]
            imgui.text('Look: '+self.draft['look_stick']+' stick')
            names = [FRIENDLY.get(b, b) for b in BUTTONS]
            for key, label in (('up', 'Fly up'), ('down', 'Fly down')):
                _, index = imgui.combo(label, BUTTONS.index(self.draft[key]), names)
                self.draft[key] = BUTTONS[index]
            _, self.draft['deadzone'] = imgui.slider_float('Stick deadzone', self.draft['deadzone'], .05, .5, '%.2f')
            _, self.draft['look_speed'] = imgui.slider_float('Look speed (degrees/sec)', self.draft['look_speed'], 20., 360., '%.0f')
            _, self.draft['invert_y'] = imgui.checkbox('Invert vertical look', self.draft['invert_y'])
            imgui.text_wrapped('Flight speed uses the Camera tab slider. A / Teleport returns to normal view after moving Link. Save/load handles confirmations automatically; release the chord while it runs.')
            imgui.begin_disabled(bool(self.listening))
            if imgui.button('Apply controller settings'):
                try:self.controller.apply(self.draft);self.feedback = 'Controller settings saved.'
                except ValueError as exc:self.feedback = str(exc)
            imgui.same_line()
            if imgui.button('Reset defaults'):
                self.draft = validate_config(DEFAULT);self.feedback = 'Defaults restored. Apply to save.'
            imgui.end_disabled()
            if self.feedback:imgui.text_wrapped(self.feedback)
            imgui.text_wrapped(self.controller.error or self.controller.status)
            imgui.end_popup()
        # Recording intentionally survives this popup losing focus: SDL devices
        # may only report input while the game is focused. Cancel/timeout/close
        # still release the native recording capture.

    def close(self):
        self.cancel_recording()
        self.controller.close()
