"""SoH-style two-row fixed-song controls in the live ImGui companion."""
from imgui_bundle import imgui,hello_imgui
from songs import SCHEMA


class SongsPanel:
    def __init__(self,editor):
        self.editor=editor

    def learn(self,ids):
        self.editor.native_undo_blocked=True
        self.editor.submit('Learn songs',lambda:self.job(ids))

    def job(self,ids):
        self.editor.songs.learn(ids)
        return self.editor.read_values()

    def draw(self):
        values=(self.editor.values or {}).get('songs')
        if values is None:
            imgui.text_wrapped('Load gameplay and connect to read the songbook.')
            return
        rows=SCHEMA['songs']
        imgui.separator_text('Songs')
        imgui.text('Learned: %d / 12'%sum(values.values()))
        if imgui.button('Learn all 12 songs'):
            self.learn([s['id'] for s in rows])
        imgui.text_wrapped('Click a note to learn that song immediately. Put away the ocarina and close game menus before editing. Save normally in-game to keep songs.')
        if imgui.begin_table('song-notes',6,imgui.TableFlags_.sizing_stretch_same):
            for song in rows:
                imgui.table_next_column();imgui.push_id(song['id'])
                learned=values[song['id']]
                imgui.begin_disabled(learned)
                clicked=hello_imgui.image_button_from_asset('icons/soh-song-note.png',(24,36),
                    tint_col=tuple(song['color']) if learned else (.42,.42,.42,1.))
                imgui.end_disabled()
                if clicked:self.learn([song['id']])
                if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
                    imgui.set_tooltip(song['label']+(' — learned' if learned else ' — click to learn'))
                imgui.text_wrapped(song['label'])
                imgui.text_disabled('Learned' if learned else 'Not learned')
                imgui.pop_id()
            imgui.end_table()
        imgui.spacing()
        imgui.text_wrapped("Scarecrow's Song uses a custom recorded tune; record it in-game. Song removal is not enabled yet.")
