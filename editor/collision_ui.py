"""Collision controls and coalesced read-only snapshots on the editor's IO worker."""
import time
from imgui_bundle import imgui
from collision import CollisionReader, Overlay
from collision_scene import KINDS, SceneSource


class CollisionPanel:
    def __init__(self, editor):
        self.editor = editor
        self.reader = CollisionReader(editor.binding)
        self.overlay = Overlay()
        self.source = None
        self.enabled = False
        self.mask = 63
        self.radius = 100.
        self.fill = True
        self.opacity = .12
        self.xray = False
        self.last_send = 0.
        self.snapshot = None
        self.snapshot_at = 0.
        self.geometry = None
        self.message = 'Enable during gameplay. Collision follows the normal or free-flight camera.'
        self.loading = ''
        self.generation = 0

    def set_enabled(self, enabled):
        self.generation += 1
        self.enabled = enabled
        self.snapshot = None
        if enabled:
            try:
                self.overlay.start()
                self.message = 'Preparing collision from your NUP...'
            except Exception as exc:
                self.enabled = False
                self.overlay.stop()
                self.message = str(exc)
        else:
            self.overlay.stop()
            self.message = 'Collision overlay off.'

    def read(self, generation):
        try:
            snapshot = self.reader.read()
            if snapshot.get('waiting'):
                return dict(kind='collision', generation=generation, waiting=True)
            if self.source is None:
                self.source = SceneSource()
            key, _ = self.source.selection(snapshot['scene'], snapshot['eye'], self.radius)
            if self.geometry and self.geometry['key'] == key:
                return dict(kind='collision', generation=generation, snapshot=snapshot, geometry=self.geometry)
            geometry = self.source.build(snapshot['scene'], self.progress, snapshot['eye'], self.radius)
            # Area may change while decoding the first mesh. Never pair an old
            # area with a new camera; re-read after cache work.
            fresh = self.reader.read()
            if fresh.get('waiting') or fresh['scene'] != snapshot['scene'] or fresh['session'] != snapshot['session']:
                return dict(kind='collision', generation=generation, waiting=True)
            return dict(kind='collision', generation=generation, snapshot=fresh, geometry=geometry)
        except Exception as exc:
            return dict(kind='collision', generation=generation, error=str(exc))
        finally:
            self.loading = ''

    def progress(self, message):
        self.loading = message

    def accept(self, result):
        if not self.enabled or result['generation'] != self.generation:
            return
        if result.get('error'):
            self.set_enabled(False)
            self.message = result['error']
        elif result.get('waiting'):
            self.snapshot = None
        else:
            self.snapshot = result['snapshot']
            self.snapshot_at = time.monotonic()
            self.geometry = result['geometry']
            self.message = '%s: %s triangles' % (self.snapshot['scene'], format(self.geometry['triangles'], ','))

    def tick(self):
        if not self.enabled:
            return
        if not self.editor.connected:
            self.set_enabled(False)
            self.message = 'Disconnected; collision overlay hidden. Reconnect, then enable again.'
            return
        try:
            status = self.overlay.poll()
            if status.get('error'):
                raise RuntimeError(status['error'])
            now = time.monotonic()
            if now-self.last_send < 1/30:
                return
            self.last_send = now
            if self.snapshot and self.geometry and now-self.snapshot_at < .4:
                self.overlay.send(**self.snapshot, path=self.geometry['path'], visible=True,
                                  mask=self.mask, radius=self.radius, fill=self.fill,
                                  opacity=self.opacity, xray=self.xray)
            else:
                self.overlay.send(visible=False)
            e = self.editor
            if e.future is None and not e.pending:
                generation = self.generation
                e.submit('Collision snapshot', lambda generation=generation: self.read(generation))
        except Exception as exc:
            self.set_enabled(False)
            self.message = str(exc)

    def draw(self):
        imgui.text_wrapped('Draw collision over the running game. Keep playing Link normally, or use the Camera tab to fly through the area.')
        imgui.begin_disabled(not self.editor.connected and not self.enabled)
        changed, enabled = imgui.checkbox('Show collision overlay', self.enabled)
        if changed:
            self.set_enabled(enabled)
        imgui.end_disabled()
        imgui.text_wrapped(self.loading or self.message)
        if self.enabled and self.overlay.last_result.get('ready'):
            imgui.text_disabled('Overlay visible' if self.overlay.last_result.get('visible') else 'Overlay waiting for the game window / fresh camera')
        imgui.separator_text('Display')
        for label, (kind, color) in KINDS.items():
            changed, checked = imgui.checkbox(label, bool(self.mask & (1 << kind)))
            if changed:
                self.mask = self.mask | (1 << kind) if checked else self.mask & ~(1 << kind)
            imgui.same_line()
            imgui.text_colored((*color, 1.), '---')
        _, self.fill = imgui.checkbox('Translucent surfaces', self.fill)
        _, self.xray = imgui.checkbox('X-ray (show through collision)', self.xray)
        imgui.set_next_item_width(260)
        _, self.radius = imgui.slider_float('Distance from camera', self.radius, 10., 500., '%.0f units')
        imgui.set_next_item_width(260)
        _, self.opacity = imgui.slider_float('Surface opacity', self.opacity, .02, .5, '%.2f')
        imgui.text_wrapped('The overlay passes clicks through to the game. Use windowed or borderless mode. It hides when you switch to another app, minimize the game, disconnect or close this menu.')
        imgui.separator_text('Coverage')
        imgui.text_wrapped('Shows authored terrain, baked solids, invisible walls and recognized trigger volumes. Moving objects, removed objects and runtime-enabled state can differ from these original placements. Curved shapes are tessellated. This does not change game collision.')
        if self.geometry and self.geometry.get('issues'):
            if imgui.tree_node('Some geometry could not be decoded'):
                for issue in self.geometry['issues'][:12]:
                    imgui.text_wrapped(issue)
                imgui.tree_pop()

    def close(self):
        self.generation += 1
        self.enabled = False
        self.overlay.stop()
