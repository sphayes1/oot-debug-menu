"""ImGui destination browser and persistent bookmark controls."""
import re
from datetime import datetime
from imgui_bundle import imgui
from locations import LocationStore, presets
from location_capture import LocationCapture
from teleport import TeleportTransport

LIVE_TELEPORT_VERIFIED = True


class TeleportPanel:
    def __init__(self, editor):
        self.editor = editor
        self.store = LocationStore()
        self.areas = presets()
        self.name = ''
        self.filter = ''
        self.age = 0
        self.advanced = False
        self.allow_any_era = False
        self.last_capture = None
        from collectibles_ui import CollectiblesPanel
        self.collectibles = CollectiblesPanel(editor,self)

    def save_here(self, name):
        pose = LocationCapture(self.editor.binding).capture()
        if not name.strip():
            name = self.label(pose['banc']) + ' ' + datetime.now().strftime('%H:%M:%S')
        row = self.store.save(name, pose, self.editor.binding.schema['source_sha256'])
        self.last_capture = row
        return {'kind': 'location_saved', 'location': row}

    @staticmethod
    def label(banc):
        return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', banc).replace('_', ' ').replace('Hounted', 'Haunted')

    def warp_to(self, pose, revision=None, *, allow_any_era=False):
        TeleportTransport(self.editor.binding).warp(pose, revision, allow_any_era=allow_any_era)
        return self.editor.connect()

    def queue_warp(self, pose, revision=None):
        # Capture the checkbox at click time, including for queued requests.
        allow = self.allow_any_era
        self.editor.submit('Teleport', lambda: self.warp_to(pose, revision, allow_any_era=allow))

    def change_age(self, age):
        from age_switch import AgeSwitch
        self.editor.binding.last_edit = None
        self.editor.native_undo_blocked = True
        switch = AgeSwitch(self.editor.binding, self.store)
        switch.switch(age)
        self.last_capture = switch.last_bookmark
        self.age = int(age == 'Adult')
        return self.editor.connect()

    def preset_pose(self, banc, entry):
        point = self.areas[banc][entry]
        age = self.editor.values['gear']['active_age']
        return dict(banc=banc, age=age, position=point['Trans'], rotation=point['Rot'],
                    rotation_units='radians', entry=entry)

    def unavailable(self, age=None):
        active = (self.editor.values or {}).get('gear', {}).get('active_age')
        return (not LIVE_TELEPORT_VERIFIED or not self.editor.connected or
                (self.editor.future is not None and self.editor.operation != 'Refresh') or
                bool(self.editor.pending) or (not self.allow_any_era and age is not None and age != active))

    def draw(self):
        editor = self.editor
        editor.position_panel.draw()
        imgui.separator_text("Link's age")
        active = (editor.values or {}).get('gear', {}).get('active_age')
        imgui.text('Current: ' + (active or 'Load a save and connect'))
        for i, age in enumerate(('Child', 'Adult')):
            if i:
                imgui.same_line()
            imgui.begin_disabled(self.unavailable() or active == age)
            if imgui.button('Become ' + age + ' Link'):
                editor.submit('Change age', lambda age=age: self.change_age(age))
            imgui.end_disabled()
        imgui.text_wrapped('Changing age saves your current location below, then reloads this same spot as the other age. Wait for loading before moving.')
        changed, self.allow_any_era = imgui.checkbox('Allow any era (untested)', self.allow_any_era)
        if changed and self.allow_any_era:
            self.age = 2
        if self.allow_any_era:
            imgui.text_colored((1., .7, .25, 1.), 'Untested: opposite-era areas may break events, spawns or loading.')
            imgui.text_wrapped("Link keeps his current age. This also unlocks opposite-era bookmarks.")
        self.collectibles.draw()
        imgui.separator_text('Saved locations')
        _, self.name = imgui.input_text('Location name (optional)', self.name)
        imgui.begin_disabled(not editor.connected or
                             (editor.future is not None and editor.operation != 'Refresh') or bool(editor.pending))
        if imgui.button('Save current location'):
            name = self.name
            editor.submit('Save location', lambda: self.save_here(name))
        imgui.end_disabled()
        imgui.text_wrapped('Bookmarks are stored in the editor and remain available after closing the game.')
        try:
            rows = self.store.read()
        except (ValueError, OSError) as exc:
            imgui.text_wrapped(str(exc))
            rows = []
        if not rows:
            imgui.text_disabled('No saved locations yet.')
        for row in rows:
            imgui.push_id(row['id'])
            pose = row['pose']
            imgui.begin_disabled(self.unavailable(pose['age']))
            if imgui.button('Teleport##saved'):
                self.queue_warp(row['pose'], row['game_revision'])
            imgui.end_disabled()
            imgui.same_line()
            imgui.text(row['name'] + ' | ' + self.label(pose['banc']))
            imgui.text_disabled('  X %.2f  Y %.2f  Z %.2f' % tuple(pose['position']))
            imgui.pop_id()

        imgui.separator_text('Around Hyrule')
        _, self.filter = imgui.input_text('Find area', self.filter)
        _, self.age = imgui.combo('Era', self.age, ['Child', 'Adult', 'All'])
        _, self.advanced = imgui.checkbox('Include boss arenas and special scenes', self.advanced)
        imgui.text_wrapped('Teleport loads the area during gameplay. Wait for loading to finish before moving.')
        common = {'KokiriForest', 'LostWood', 'SacredForestMeadow', 'HyruleField', 'Market',
                  'HyruleCastle', 'KakarikoVillage', 'Graveyard', 'DeathMountainTrail',
                  'DeathMountainCrater', 'GoronCity', 'ZoraRiver', 'ZoraDomain', 'ZoraFountain',
                  'LakeHylia', 'GerudoValley', 'GerudoFortress', 'HountedWasteland', 'DesertColossus',
                  'TempleOfTime', 'InsideTheDekuTree', 'DodongoCavern', 'InsideJabuJabuBelly',
                  'ForestTemple', 'FireTemple', 'WaterTemple', 'ShadowTemple', 'SpiritTemple',
                  'BottomOfTheWell', 'IceCavern', 'GerudoTrainingGround', 'InsideGanonCastle'}
        if not imgui.begin_table('destinations', 3, imgui.TableFlags_.sizing_stretch_same):
            return
        # These landmarks share the Hyrule Field area in the remake's own assets.
        landmarks = [('Lake Hylia Child', 'HyruleField_Child', 'MiniGame_Fishing_PlayerStart'),
                     ('Lake Hylia Adult', 'HyruleField_Adult', 'MiniGame_Fishing_PlayerStart'),
                     ('Temple of Time Child', 'HyruleField_Child', 'StartPos_DoorOfTime')]
        for label, banc, entry in landmarks:
            age = 'Adult' if '_Adult' in banc else 'Child'
            if self.filter.casefold() not in label.casefold() or (self.age != 2 and self.age != (age == 'Adult')):
                continue
            imgui.table_next_column()
            imgui.begin_disabled(self.unavailable(age))
            if imgui.button(label):
                pose = self.preset_pose(banc, entry)
                self.queue_warp(pose)
            imgui.end_disabled()
        for banc, entries in self.areas.items():
            if self.filter.casefold() not in banc.casefold():
                continue
            if self.age != 2 and ('_Adult' in banc if self.age == 0 else '_Child' in banc):
                continue
            if not self.advanced and banc.split('_')[0] not in common:
                continue
            label = self.label(banc)
            age = 'Adult' if '_Adult' in banc else 'Child' if '_Child' in banc else None
            entry = '' if '' in entries else 'EntrancePos' if 'EntrancePos' in entries else next(iter(entries))
            imgui.table_next_column()
            imgui.push_id(banc)
            imgui.begin_disabled(self.unavailable(age))
            if imgui.button(label):
                pose = self.preset_pose(banc, entry)
                self.queue_warp(pose)
            imgui.end_disabled()
            if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
                imgui.set_tooltip(f'{len(entries)} named entry points extracted from this game')
            if len(entries) > 1:
                imgui.same_line()
                if imgui.small_button('...'):
                    imgui.open_popup('entry-points')
                if imgui.begin_popup('entry-points'):
                    imgui.text(label)
                    imgui.begin_disabled(self.unavailable(age))
                    for name in entries:
                        if imgui.selectable(name or 'Default entrance', False)[0]:
                            pose = self.preset_pose(banc, name)
                            self.queue_warp(pose)
                    imgui.end_disabled()
                    imgui.end_popup()
            imgui.pop_id()
        imgui.end_table()
