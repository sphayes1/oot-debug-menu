"""Live coordinate reader, manual destinations and per-axis nudge controls."""
from imgui_bundle import imgui
from position import PositionTransport, STEPS


class PositionPanel:
    def __init__(self, editor):
        self.editor = editor
        self.draft = [0., 0., 0.]
        self.context = None

    def move(self, value=None, *, axis=None, delta=None, expected_area=None):
        self.editor.binding.last_edit = None
        self.editor.native_undo_blocked = True
        receipt = PositionTransport(self.editor.binding).move(value, axis=axis, delta=delta, expected_area=expected_area)
        values = self.editor.read_values()
        return dict(kind='position', receipt=receipt, values=values)

    def draw(self):
        e = self.editor
        pose = (e.values or {}).get('location')
        disabled = (not e.connected or not pose or
                    (e.future is not None and e.operation != 'Refresh') or bool(e.pending))
        area = pose['banc'] if pose else None
        imgui.separator_text('Live coordinates')
        if pose:
            context = (tuple(e.binding.session_id), pose['banc'], pose['age'])
            if context != self.context:
                self.draft = list(pose['position'])
                self.context = context
            imgui.text(pose['banc'] + ' | ' + pose['age'] + ' Link')
            imgui.text('X %.3f    Y %.3f    Z %.3f' % tuple(pose['position']))
        else:
            imgui.text_disabled('Position unavailable')
            imgui.text_disabled((e.values or {}).get('location_error', 'Load a save and connect to read coordinates.'))
        imgui.begin_disabled(disabled)
        if imgui.button('Copy current XYZ to fields') and pose:
            self.draft = list(pose['position'])
        if imgui.begin_table('coordinateControls', 8, imgui.TableFlags_.sizing_fixed_fit):
            for axis, label in enumerate(('X', 'Y', 'Z')):
                imgui.push_id(label)
                imgui.table_next_row()
                imgui.table_next_column(); imgui.text(label)
                imgui.table_next_column(); imgui.set_next_item_width(120)
                _, self.draft[axis] = imgui.input_float('##coordinate', self.draft[axis], 0, 0, '%.3f')
                for step in STEPS:
                    imgui.table_next_column()
                    if imgui.button('%+d' % step, (48, 0)):
                        e.submit('Nudge '+label, lambda axis=axis, step=step, area=area: self.move(axis=axis, delta=step, expected_area=area))
                imgui.pop_id()
            imgui.end_table()
        if imgui.button('Move to entered XYZ'):
            value = list(self.draft)
            e.submit('Move to XYZ', lambda value=value, area=area: self.move(value, expected_area=area))
        imgui.end_disabled()
        imgui.text_wrapped('Y is height. Nudges use your latest position and move immediately within this area. Gravity still applies.')
