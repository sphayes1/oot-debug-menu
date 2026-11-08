"""Keyboard flight is tab-scoped; controller flight is scoped to game focus."""
import math
import time
from imgui_bundle import imgui
from camera import Camera, fly
from controller import chord


class CameraPanel:
    def __init__(self, editor):
        self.editor = editor
        self.camera = Camera(editor.binding)
        self.desired = None
        self.speed = 10.
        self.last_frame = time.monotonic()
        self.last_send = 0.
        self.dirty = False

    def set_enabled(self, enabled):
        if enabled:
            pose = self.camera.enable()
        else:
            self.camera.disable()
            pose = None
        return dict(kind='camera', pose=pose, message='Free flight enabled.' if enabled else 'Normal camera restored.')

    def accept(self, result):
        self.desired = result.get('pose')
        self.dirty = False

    def stop(self):
        self.camera.disable()
        self.dirty = False

    def teleport(self):
        receipt = self.camera.teleport()
        # Keep flight active if teleport fails. Only restore the view after the
        # observed position transport succeeds.
        self.camera.disable()
        self.desired = None
        self.dirty = False
        self.editor.native_undo_blocked = True
        self.editor.binding.last_edit = None
        return dict(kind='camera', pose=None, receipt=receipt,
                    message='Link teleported to the camera; normal view restored. Gravity still applies.')

    def draw(self):
        e = self.editor
        active = self.camera.active
        busy = e.future is not None or bool(e.pending)
        now = time.monotonic()
        dt = min(.08, now-self.last_frame)
        self.last_frame = now
        imgui.text_wrapped('Fly the camera independently of Link, then bring Link to the viewpoint.')
        imgui.begin_disabled(busy or not e.connected)
        changed, enabled = imgui.checkbox('Free flight debug camera', active)
        if changed:
            e.submit('Camera enable' if enabled else 'Camera disable', lambda enabled=enabled: self.set_enabled(enabled))
        imgui.end_disabled()
        imgui.same_line()
        imgui.begin_disabled(busy)
        if imgui.button('Restore normal camera'):
            e.submit('Camera disable', lambda: self.set_enabled(False))
        imgui.end_disabled()
        imgui.text_wrapped('Keep this Camera tab focused. W/S: forward/back, A/D: strafe, Q/E: down/up. Hold right mouse to look; Shift moves 4x faster. Escape restores the normal camera.')
        bindings = e.controller_panel.controller.config['bindings']
        imgui.text_wrapped('Controller: focus the game. '+chord(bindings['enter'])+' enters, '+chord(bindings['exit'])+' exits, '+chord(bindings['teleport'])+' teleports and restores normal view. Customize under Controller...')
        imgui.set_next_item_width(260)
        _, self.speed = imgui.slider_float('Speed (world units/sec)', self.speed, 1., 100., '%.1f')
        pose = self.desired or self.camera.pose
        if active and pose:
            imgui.text('Camera: X %.3f   Y %.3f   Z %.3f' % tuple(pose['eye']))
            imgui.text('Yaw %.1f   Pitch %.1f degrees' % (math.degrees(pose['yaw']), math.degrees(pose['pitch'])))
        imgui.begin_disabled(not active or not e.connected or busy or self.dirty)
        if imgui.button('Teleport Link to camera'):
            e.submit('Camera teleport', self.teleport)
        imgui.end_disabled()
        imgui.text_wrapped('Teleport stays inside the current area. No collision protection: the camera can pass through walls; Link falls if teleported into the air. Save/load, other edits and area changes end free flight.')
        focused = imgui.is_window_focused(imgui.FocusedFlags_.root_and_child_windows)
        if active and focused and not imgui.get_io().want_text_input:
            if imgui.is_key_pressed(imgui.Key.escape, False) and not busy:
                e.submit('Camera disable', lambda: self.set_enabled(False))
                return
            if not imgui.is_any_item_active():
                down = lambda key: int(imgui.is_key_down(key))
                side = down(imgui.Key.d)-down(imgui.Key.a)
                forward = down(imgui.Key.w)-down(imgui.Key.s)
                vertical = down(imgui.Key.e)-down(imgui.Key.q)
                mouse = imgui.get_io().mouse_delta if imgui.is_mouse_down(1) else (0., 0.)
                dx, dy = (mouse.x, mouse.y) if hasattr(mouse, 'x') else mouse
                boost = 4 if imgui.get_io().key_shift else 1
                if pose and (side or forward or vertical or dx or dy):
                    self.desired = fly(pose, side, forward, vertical, self.speed*boost*dt, dx, dy)
                    self.dirty = True
        self.flush()

    def flush(self):
        e = self.editor
        now = time.monotonic()
        # One pending update; controller input works with any tab / game focus.
        if self.camera.active and self.dirty and e.future is None and not e.pending and now-self.last_send >= 1/30:
            target = dict(self.desired, eye=list(self.desired['eye']))
            self.dirty = False
            self.last_send = now
            e.submit('Camera flight', lambda target=target: self.camera.update(target))
