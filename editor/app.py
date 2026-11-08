"""Live Dear ImGui editor. One background worker serializes all game IO."""
import json
import logging
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from imgui_bundle import imgui, hello_imgui
import backend
from live import Bindings
from bottles import ICONS as BOTTLE_ICONS
import presentation as model
from native_ui import native_message, whole_heart_maximum
from teleport_ui import TeleportPanel
from position_ui import PositionPanel
from songs_ui import SongsPanel
from camera_ui import CameraPanel
from collision_ui import CollisionPanel
from songs import Songs
from collectibles import BeanState

# Enable individual fields only after their actual gameplay effect is demonstrated.
NATIVE_GAMEPLAY_VERIFIED = {'Life': False, 'MaxLife': False, 'MP': False, 'MPMax': False}
PLAYER_CURRENT_LIFE_VERIFIED = True
PLAYER_CURRENT_MAGIC_VERIFIED = True

logging.basicConfig(filename=backend.ROOT/'editor.log', level=logging.INFO)

class Editor:
    def __init__(self):
        self.binding = Bindings()
        self.songs = Songs(self.binding)
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='inventory-live')
        self.future = None
        self.operation = ''
        self.pending = []
        self.values = None
        self.connected = False
        self.message = 'Load a save in the inventory game, then connect.'
        self.error = False
        self.last_poll = 0
        self.filter = ''
        self.drafts = {}
        self.restrict_valid = True
        self.allow_any_age_items = False
        self.sync_buttons = True
        self.native = None
        self.native_receipt = None
        self.native_undo_blocked = False
        self.player_life = None
        self.player_magic = None
        self.icons = {r['id']:'icons/'+Path(r['png']).name for r in json.loads(
            (backend.ROOT/'assets/icons/manifest.json').read_text(encoding='utf-8'))['icons']}
        for suffix in 'ABCDE':self.icons['Bottle'+suffix]=self.icons['Item_Bottle']
        self.icons['Item_NormalBoot']=self.icons['gItemIconBootsKokiriTex']
        self.actor_ages={}
        self.teleport_panel = TeleportPanel(self)
        self.position_panel = PositionPanel(self)
        self.songs_panel = SongsPanel(self)
        self.camera_panel = CameraPanel(self)
        self.collision_panel = CollisionPanel(self)
        self.location_reader = None
        from hotkeys import HotkeysPanel
        self.hotkeys_panel = HotkeysPanel(self)
        from controller_ui import ControllerPanel
        self.controller_panel = ControllerPanel(self)
        from actor_catalog_ui import ActorsPanel
        self.actors_panel = ActorsPanel(self)
        for entries in json.loads((backend.ROOT/'research/pouch-ui-table.json').read_text(encoding='utf-8')).values():
            if isinstance(entries,list):
                for entry in entries:
                    for actor in entry.get('Actor',[]):
                        self.actor_ages.setdefault(actor['ActorShort'],set()).update(age for age in ('Adult','Child') if actor.get('IsUsable'+age,False))

    def submit(self, label, operation):
        if label != 'Refresh' and not label.startswith(('Camera ', 'Collision ')) and self.camera_panel.camera.active:
            original = operation
            def operation():
                self.camera_panel.stop()
                return original()
        if self.future is None:
            self.operation = label
            self.future = self.worker.submit(operation)
        elif label!='Refresh':
            self.pending.append((label,operation))

    def pump(self):
        if self.future is not None and self.future.done():
            try:
                result = self.future.result()
                native_result = isinstance(result, dict) and result.get('kind') in ('native','player','position','checkpoint')
                if native_result:
                    self.native_receipt = result['receipt']
                    if result['kind'] == 'checkpoint':
                        self.values = result['values']
                        self.connected = True
                        self.error = False
                        self.message = ('Checkpoint saved' if result['action']=='save' else 'Checkpoint loaded')+f" in {self.native_receipt['seconds']:.2f} seconds."
                    elif result['kind'] == 'position':
                        self.error = self.native_receipt['state'] != 'applied'
                        self.message = 'Position updated.' if not self.error else 'Inspect the position audit before trying again.'
                    elif result['kind'] == 'player':
                        state = self.native_receipt['state']
                        field = 'magic' if self.native_receipt.get('field') == 'MP' else 'health'
                        self.error = state != 'applied'
                        self.message = ('Current '+field+' updated.' if state == 'applied' else
                            field.capitalize()+' changed during the edit; inspect its audit. No automatic retry.')
                    else:
                        self.message, self.error = native_message(self.native_receipt)
                    if result.get('values') is not None:
                        self.values = result['values']
                        self.connected = True
                elif isinstance(result, dict) and result.get('kind') == 'collision':
                    self.collision_panel.accept(result)
                elif isinstance(result, dict) and result.get('kind') == 'camera':
                    self.camera_panel.accept(result)
                    self.message = result['message']
                    self.error = False
                elif isinstance(result, dict) and 'items' in result:
                    self.values = result
                    self.connected = True
                if self.operation == 'Live edit' and self.binding.last_edit is not None:
                    self.native_undo_blocked = False
                if self.operation not in ('Refresh', 'Camera flight', 'Collision snapshot') and not native_result and not (isinstance(result, dict) and result.get('kind') == 'camera'):
                    self.message = self.operation+' complete.'
                    self.error = False
            except Exception as exc:
                logging.exception('Live operation failed')
                self.message = str(exc)
                self.error = True
                self.connected = False
                if self.operation in ('Connect','Refresh'):
                    self.connected = False
            self.future = None
            if self.operation != 'Collision snapshot':
                self.last_poll = time.monotonic()
        if self.future is None and self.pending:
            self.submit(*self.pending.pop(0))
        if self.connected and self.future is None and time.monotonic()-self.last_poll > 1:
            self.submit('Refresh', self.read_values)

    def connect(self):
        values = self.binding.connect()
        camera = self.camera_panel.camera
        if camera.session_id is not None and camera.session_id != tuple(self.binding.session_id):
            camera.active = False
            camera.previous = None
            camera.session_id = None
        if camera.session_id is None:
            from camera import FLAG, SENTINEL
            if self.camera_panel.camera.fields.field('String64', FLAG) == SENTINEL:
                self.camera_panel.stop()
        values['songs'] = self.songs.view()
        values['beans'] = BeanState(self.binding).view()
        from location_capture import LocationCapture
        self.location_reader = LocationCapture(self.binding)
        self.add_location(values)
        self.player_life = None
        self.player_magic = None
        if PLAYER_CURRENT_LIFE_VERIFIED:
            try:
                from player_life import PlayerLifeBindings
                player = PlayerLifeBindings(self.binding)
                values['player_life'] = player.bind()
                self.player_life = player
            except Exception as exc:
                logging.info('Player health binding unavailable: %s', exc)
        if PLAYER_CURRENT_MAGIC_VERIFIED and self.player_life is not None:
            try:
                from player_magic import PlayerMagicBindings
                magic = PlayerMagicBindings(self.player_life)
                values['player_magic'] = magic.bind()
                self.player_magic = magic
            except Exception as exc:
                logging.info('Player magic binding unavailable: %s', exc)
        return values

    def read_values(self):
        self.camera_panel.camera.check()
        values = self.binding.view()
        values['songs'] = self.songs.view()
        values['beans'] = BeanState(self.binding).view()
        self.add_location(values)
        if self.player_life is not None:
            try:
                values['player_life'] = self.player_life.read()
            except Exception as exc:
                logging.info('Player health binding changed: %s', exc)
                self.player_life = None
                self.player_magic = None
        if self.player_magic is not None:
            try:
                values['player_magic'] = self.player_magic.read()
            except Exception as exc:
                logging.info('Player magic binding changed: %s', exc)
                self.player_magic = None
        return values

    def add_location(self, values):
        if self.location_reader is not None:
            try:
                values['location'] = self.location_reader.capture()
            except Exception as exc:
                values['location_error'] = str(exc)

    def launch(self):
        if backend.emulator_running():
            raise ValueError('A game is already running. Connect to the inventory profile, or close it before launching.')
        from launcher import launch_game
        launch_game()

    def edit(self, changes):
        if self.sync_buttons and self.values and self.binding.assignments:
            changes=model.sync_assignments(changes,self.values,self.binding.assignments.schema['symbol_actors'])
        if self.values and changes.get('capacities'):
            changes=dict(changes)
            counts=dict(changes.get('counts',{}))
            ammo={'Arrow':('Item_Arrow_Normal',),'DekuSeed':('Item_DekuSeed',),
                  'Bomb':('Item_Bomb','Item_Bombchu'),'DekuNut':('Item_DekuNut',),'DekuStick':('Item_DekuStick',)}
            for semantic,limit in changes['capacities'].items():
                if semantic=='Rupee' and self.values['rupees']>limit:changes['rupees']=limit
                for actor in ammo.get(semantic,()):
                    if self.values['counts'][actor]>limit:counts[actor]=limit
            if counts:changes['counts']=counts
        self.submit('Live edit', lambda:self.binding.apply(changes))

    def native_edit(self, field, expected, value):
        if not NATIVE_GAMEPLAY_VERIFIED.get(field, False):
            raise ValueError('This native field has not passed gameplay validation')
        # Capture the user-visible expected value now; stale values must be refused.
        self.native_undo_blocked = True
        self.submit('Native '+field, lambda:self.native_job(field, expected, value))

    def player_edit(self, expected, value):
        if not PLAYER_CURRENT_LIFE_VERIFIED or self.player_life is None:
            raise ValueError('Connect the verified active player health state first')
        self.native_undo_blocked = True
        self.submit('Player health', lambda:self.player_job(expected, value))

    def player_job(self, expected, value):
        self.binding.last_edit = None
        if self.player_life is None:
            raise ValueError('Player health binding changed; connect again')
        receipt = self.player_life.write_current(expected, value)
        result = dict(kind='player', receipt=receipt, values=None)
        try:
            result['values'] = self.read_values()
        except Exception as exc:
            result['refresh_error'] = str(exc)
        return result

    def magic_edit(self, expected, value):
        if not PLAYER_CURRENT_MAGIC_VERIFIED or self.player_magic is None:
            raise ValueError('Connect the verified active player magic state first')
        self.native_undo_blocked = True
        self.submit('Player magic', lambda:self.magic_job(expected, value))

    def magic_job(self, expected, value):
        self.binding.last_edit = None
        if self.player_magic is None:
            raise ValueError('Player magic binding changed; connect again')
        receipt = self.player_magic.write_current(expected, value)
        result = dict(kind='player', receipt=receipt, values=None)
        try:
            result['values'] = self.read_values()
        except Exception as exc:
            result['refresh_error'] = str(exc)
        return result

    def native_job(self, field, expected, value):
        from native_requests import NativeRequests
        # A native action cannot leave generic Undo pointing at an older inventory edit.
        # Native changes need a future separately guarded inverse, never raw-word rollback.
        self.binding.last_edit = None
        if self.native is None or self.native.session_id != tuple(self.binding.session_id):
            native = NativeRequests(self.binding)
            native.bind()
            self.native = native
        receipt = self.native.set_int(field, expected, value, busy_retries=0)
        result = dict(kind='native', receipt=receipt, values=None)
        try:
            result['values'] = self.binding.view()
        except Exception as exc:
            result['refresh_error'] = str(exc)
        return result

    def equipped_border(self,actor):
        if actor in self.values.get('gear',{}).get('equipped_actor_ids',[]):
            low,high=imgui.get_item_rect_min(),imgui.get_item_rect_max()
            imgui.get_window_draw_list().add_rect((low.x-2,low.y-2),(high.x+2,high.y+2),
                imgui.get_color_u32((1,1,1,1)),0,0,2)

    def assignment_border(self,actor):
        gear=self.values.get('gear',{})
        active=gear.get('assignments',{}).get(gear.get('active_age'),{})
        if actor in active.get('actors',[]) or actor==active.get('symbol'):
            low,high=imgui.get_item_rect_min(),imgui.get_item_rect_max()
            imgui.get_window_draw_list().add_rect((low.x-2,low.y-2),(high.x+2,high.y+2),
                imgui.get_color_u32((1,.65,0,1)),0,0,2)

    def item(self, row):
        actor = row['id']
        if actor.startswith('Bottle'):
            self.bottle(row)
            return
        owned = self.values['items'].get(actor,False)
        if actor in self.icons:
            clicked = hello_imgui.image_button_from_asset(self.icons[actor],(40,40),
                tint_col=(1,1,1,1) if owned else (.35,.35,.35,.55))
        else:
            clicked = imgui.button(''.join(w[0] for w in row['label'].split())[:4]+'##'+actor,(46,46))
        self.equipped_border(actor)
        if imgui.is_item_hovered():
            imgui.set_tooltip(row['label']+(' (owned)' if owned else ' (absent)')+'\nClick to toggle')
        if clicked:
            changes={'items':{actor:not owned}}
            if actor=='Item_FairyBless_DefenseDouble':
                from enhancements import upgrade_changes
                changes.update(upgrade_changes('defense',actor if not owned else None))
            self.edit(changes)
        if row['count_max']>1:
            self.counter('##count-'+actor,self.values['counts'][actor],0,row['count_max'],
                lambda n:self.edit({'counts':{actor:n}}),width=46)

    def bottle(self,row):
        slot=row['id']
        state=self.values.get('bottles',{}).get(slot,{'content':'Empty'})
        owned=self.values['items'][slot]
        icon=self.icons[BOTTLE_ICONS[state['content']]]
        imgui.push_id(slot)
        clicked=hello_imgui.image_button_from_asset(icon,(40,40)) if owned else imgui.button('##empty',(46,46))
        if clicked:
            imgui.open_popup('contents')
        if owned:self.assignment_border(slot)
        if imgui.is_item_hovered():imgui.set_tooltip(slot+' â€” '+(state['content'] if owned else 'absent')+'\nClick to choose contents')
        if imgui.begin_popup('contents'):
            if imgui.button('##None',(46,46)):
                self.edit({'items':{slot:False}})
                imgui.close_current_popup()
            if imgui.is_item_hovered():imgui.set_tooltip('None')
            for i,(content,icon_id) in enumerate(BOTTLE_ICONS.items()):
                if (i+1)%8:imgui.same_line()
                if hello_imgui.image_button_from_asset(self.icons[icon_id],(40,40)):
                    self.edit({'counts':{slot:1},'bottles':{slot:content}})
                    imgui.close_current_popup()
                if imgui.is_item_hovered():imgui.set_tooltip(content)
            imgui.end_popup()
        imgui.pop_id()

    def slot_picker(self,slot):
        if slot.choices[0].startswith('Bottle'):
            self.bottle(self.binding.items[slot.choices[0]])
            return
        actor=model.selected(slot,self.values['counts'])
        imgui.push_id(slot.key)
        if actor and actor in self.icons:
            clicked=hello_imgui.image_button_from_asset(self.icons[actor],(40,40))
        elif slot in model.UPGRADES+(model.MAGIC,) and slot.choices[0] in self.icons:
            clicked=hello_imgui.image_button_from_asset(self.icons[slot.choices[0]],(40,40),tint_col=(.35,.35,.35,.55))
        else:clicked=imgui.button('##empty',(46,46))
        if clicked:imgui.open_popup('picker')
        if actor:self.equipped_border(actor)
        if actor:self.assignment_border(actor)
        if imgui.is_item_hovered():
            imgui.set_tooltip(self.binding.items[actor]['label'] if actor else slot.label+' (None)')
        if imgui.begin_popup('picker'):
            if imgui.button('##none',(46,46)):
                self.edit(model.selection_changes(slot,None,self.values['counts']))
                imgui.close_current_popup()
            if imgui.is_item_hovered():imgui.set_tooltip('None')
            for i,choice in enumerate(slot.choices):
                if (i+1)%8:imgui.same_line()
                if choice in self.icons:
                    picked=hello_imgui.image_button_from_asset(self.icons[choice],(40,40))
                else:picked=imgui.button(self.binding.items[choice]['label']+'##pick',(46,46))
                if imgui.is_item_hovered():imgui.set_tooltip(self.binding.items[choice]['label'])
                if picked:
                    self.edit(model.selection_changes(slot,choice,self.values['counts']))
                    imgui.close_current_popup()
            imgui.end_popup()
        if actor and slot.ammo:
            ammo=slot.ammo
            semantic={'Item_Arrow_Normal':'Arrow','Item_DekuSeed':'DekuSeed','Item_Bomb':'Bomb',
                      'Item_Bombchu':'Bomb','Item_DekuStick':'DekuStick','Item_DekuNut':'DekuNut'}.get(ammo)
            limit=self.binding.items[ammo]['count_max']
            if self.restrict_valid and semantic:limit=min(limit,self.values['capacities'][semantic])
            self.counter('##ammo',self.values['counts'][ammo],0,limit,
                lambda n:self.edit({'counts':{ammo:n}}),width=46)
        imgui.pop_id()

    def inventory(self):
        if imgui.begin_table('inventoryCards',2,imgui.TableFlags_.sizing_stretch_same):
            imgui.table_next_column()
            self.start_card('Items')
            _,self.sync_buttons=imgui.checkbox('Keep button items in sync',self.sync_buttons)
            if imgui.begin_table('slotGrid',6,imgui.TableFlags_.sizing_fixed_fit):
                for slot in model.INVENTORY:
                    imgui.table_next_column()
                    self.slot_picker(slot)
                imgui.end_table()
            self.end_card()
            self.start_card('Actions')
            _,self.restrict_valid=imgui.checkbox('Restrict to valid items',self.restrict_valid)
            if imgui.is_item_hovered():imgui.set_tooltip('Ammo inputs follow the current bag capacity. Remake item types remain tied to their native slots.')
            if imgui.button('Give All'):
                self.edit(model.inventory_action(True,self.values['counts'],self.binding.items))
            imgui.same_line()
            if imgui.button('Reset'):
                self.edit(model.inventory_action(False,self.values['counts'],self.binding.items))
            self.end_card()
            self.start_card('Remake additions')
            for i,slot in enumerate(model.EXTRA_INVENTORY):
                if i:imgui.same_line()
                imgui.begin_group()
                self.slot_picker(slot)
                imgui.end_group()
            self.end_card()
            imgui.table_next_column()
            self.button_items()
            self.group('Masks',{'Masks'})
            self.group('Amiibo masks',{'RemakeMasks'})
            self.group('Additional items',{'InventoryExtras'})
            imgui.end_table()

    def button_items(self):
        self.start_card('Button Items')
        gear=self.values.get('gear',{})
        schema=self.binding.assignments.schema
        for age in ('Child','Adult'):
            selected=gear['assignments'][age]
            imgui.text(age+' quick use'+(' (active)' if age==gear['active_age'] else ''))
            imgui.push_id('button-'+age)
            actor=next((a for a in selected['actors'] if a in self.icons),None)
            if selected['symbol'].startswith('Bottle'):
                state=self.values['bottles'][selected['symbol']]
                actor=BOTTLE_ICONS[state['content']]
            if actor:clicked=hello_imgui.image_button_from_asset(self.icons[actor],(40,40))
            else:clicked=imgui.button('##selected',(46,46))
            if clicked:imgui.open_popup('assignment')
            if imgui.is_item_hovered():imgui.set_tooltip(selected['symbol'])
            if imgui.begin_popup('assignment'):
                _, self.allow_any_age_items = imgui.checkbox('Allow items from any age', self.allow_any_age_items)
                if imgui.is_item_hovered():
                    imgui.set_tooltip('Show owned items from both ages. The game may still block their use.')
                imgui.separator()
                visible=model.assignment_choices(schema,age,self.values['items'],self.values['bottles'],
                    self.actor_ages,restrict_valid=self.restrict_valid,allow_any_age=self.allow_any_age_items)
                for i,symbol in enumerate(visible):
                    if i%8:imgui.same_line()
                    choices=schema['symbol_actors'].get(symbol,[])
                    icon_actor=next((a for a in choices if a in self.icons),None)
                    if symbol.startswith('Bottle'):icon_actor=BOTTLE_ICONS[self.values['bottles'][symbol]['content']]
                    imgui.push_id(symbol)
                    if icon_actor:picked=hello_imgui.image_button_from_asset(self.icons[icon_actor],(40,40))
                    else:picked=imgui.button('' if symbol=='Empty' else symbol,(46,46))
                    if imgui.is_item_hovered():imgui.set_tooltip('None' if symbol=='Empty' else symbol)
                    if picked:
                        self.edit({'assignments':{age:symbol},'allow_unowned_assignment':not self.restrict_valid})
                        imgui.close_current_popup()
                    imgui.pop_id()
                imgui.end_popup()
            imgui.pop_id()
        self.end_card()

    def upgrades(self):
        self.start_card('Upgrades')
        for i,slot in enumerate(model.UPGRADES):
            if i:imgui.same_line()
            self.slot_picker(slot)
        current=model.selected(model.WALLET,self.values['counts'])
        labels=('Small (200)','Medium (500)','Large (1000)')
        preview=labels[model.WALLET.choices.index(current)] if current else 'None'
        if imgui.begin_combo('Wallet',preview):
            for i,(actor,label) in enumerate(zip(model.WALLET.choices,labels)):
                if imgui.selectable(label,actor==current)[0]:self.edit(model.selection_changes(model.WALLET,actor,self.values['counts']))
            imgui.end_combo()
        for slot,numbers in ((model.STICK_BAG,(0,10,20,30)),(model.NUT_BAG,(0,20,30,40))):
            actor=model.selected(slot,self.values['counts'])
            level=slot.choices.index(actor)+1 if actor else 0
            changed,level=imgui.slider_int(slot.label,level,0,3,str(numbers[level]))
            if changed:self.edit(model.selection_changes(slot,slot.choices[level-1] if level else None,self.values['counts']))
        self.end_card()
        self.start_card('Magic and defense')
        self.slot_picker(model.MAGIC)
        imgui.same_line()
        self.item(self.binding.items['Item_FairyBless_DefenseDouble'])
        self.end_card()

    def start_card(self,title):
        flags=imgui.ChildFlags_.border|imgui.ChildFlags_.auto_resize_y|imgui.ChildFlags_.always_auto_resize
        imgui.begin_child('card-'+title,(0,0),flags)
        imgui.text_colored((.7,.7,.7,1),title)
        imgui.spacing()

    @staticmethod
    def end_card():
        imgui.end_child()
        imgui.spacing()

    def counter(self,label,current,minimum,maximum,commit,width=160):
        value=self.drafts.get(label,current)
        imgui.set_next_item_width(width)
        changed,value=imgui.input_int(label,value,0,0,imgui.InputTextFlags_.enter_returns_true)
        self.drafts[label]=value
        if changed or imgui.is_item_deactivated_after_edit():
            commit(max(minimum,min(maximum,value)))
            self.drafts.pop(label,None)
        elif not imgui.is_item_active():
            self.drafts.pop(label,None)

    def group(self,title,groups):
        rows = [r for r in self.binding.items.values() if r['group'] in groups and
                self.filter.lower() in (r['label']+' '+r['id']).lower()]
        if rows:
            self.start_card(title)
            if imgui.begin_table('grid-'+title,6,imgui.TableFlags_.sizing_fixed_fit):
                for row in rows:
                    imgui.table_next_column()
                    self.item(row)
                imgui.end_table()
            self.end_card()

    def general(self):
        imgui.separator_text('Rupees')
        self.counter('Rupees',self.values['rupees'],0,self.values['wallet_capacity'],lambda n:self.edit({'rupees':n}))
        imgui.text_disabled('Live changes take effect immediately. Save in the game to keep them.')
        imgui.separator_text('Health')
        player = self.values.get('player_life')
        current = player['current'] if player else self.values['health']
        maximum = player['maximum'] if player else self.values['max_health']
        imgui.text(f"Current hearts: {current/4:g}    Maximum: {maximum/4:g}")
        imgui.begin_disabled(not PLAYER_CURRENT_LIFE_VERIFIED or not player or self.player_life is None)
        self.counter('Current health (quarter-hearts)', current, 0, min(80,maximum),
            lambda n:self.player_edit(current, n))
        if imgui.button('Refill hearts'):
            self.player_edit(current, maximum)
        imgui.end_disabled()
        imgui.begin_disabled(not NATIVE_GAMEPLAY_VERIFIED['MaxLife'])
        self.counter('Maximum health (quarter-hearts)', self.values['max_health'], 12, 80,
            lambda n:self.native_edit('MaxLife', self.values['max_health'], whole_heart_maximum(n)))
        imgui.end_disabled()
        if not player:
            imgui.text_disabled('Connect while gameplay is loaded to bind current health.')
        imgui.text_disabled('Maximum health editing is under validation.')
        magic=self.values['enhancements']
        active_magic=self.values.get('player_magic')
        magic_current=active_magic['current'] if active_magic else magic['MP']
        magic_maximum=active_magic['maximum'] if active_magic else magic['MPMax']
        self.start_card('Magic')
        imgui.begin_disabled(not PLAYER_CURRENT_MAGIC_VERIFIED or not active_magic or self.player_magic is None)
        self.counter('Current magic', magic_current, 0, min(48,magic_maximum),
            lambda n:self.magic_edit(magic_current, n))
        if imgui.button('Refill magic'):self.magic_edit(magic_current, magic_maximum)
        imgui.end_disabled()
        imgui.begin_disabled(not NATIVE_GAMEPLAY_VERIFIED['MPMax'])
        if imgui.begin_combo('Magic capacity', str(magic['MPMax'])):
            for capacity in (0,24,48):
                if imgui.selectable(str(capacity), capacity == magic['MPMax'])[0]:
                    self.native_edit('MPMax', magic['MPMax'], capacity)
            imgui.end_combo()
        imgui.end_disabled()
        if not active_magic:
            imgui.text_disabled('Connect while gameplay is loaded to bind current magic.')
        imgui.text_disabled('Magic capacity editing is under validation.')
        self.end_card()

    def gui(self):
        self.pump()
        self.hotkeys_panel.pump()
        self.controller_panel.pump()
        busy=(self.future is not None and self.operation not in ('Refresh', 'Camera flight', 'Collision snapshot')) or bool(self.pending)
        imgui.text('Ocarina Debug Menu')
        imgui.same_line()
        imgui.text_colored((.45,.85,.55,1) if self.connected else (1,.7,.3,1),
            'Connected to gameplay' if self.connected else 'Disconnected')
        imgui.separator()
        imgui.begin_disabled(busy)
        if imgui.button('Connect / Refresh'):self.submit('Connect',self.connect)
        imgui.same_line()
        if imgui.button('Launch debug game'):self.submit('Launch',self.launch)
        imgui.same_line()
        imgui.begin_disabled(not self.connected or self.binding.last_edit is None or self.native_undo_blocked)
        if imgui.button('Undo last edit'):self.submit('Undo',self.binding.undo)
        imgui.end_disabled()
        imgui.end_disabled()
        imgui.same_line()
        self.hotkeys_panel.draw()
        imgui.same_line()
        self.controller_panel.draw()
        imgui.text_colored((1,.45,.4,1) if self.error else (.7,.8,.9,1),self.message)
        if self.future is not None and self.operation!='Refresh':
            imgui.same_line()
            imgui.text_disabled(self.operation+'...')
        if not self.values:
            imgui.text_wrapped('Start the isolated inventory game, load your save, and connect. Keep playing while this editor is open; changes do not require a restart.')
            if imgui.begin_tab_bar('OfflineBrowserTabs'):
                if imgui.begin_tab_item('Actors')[0]:
                    self.actors_panel.draw();imgui.end_tab_item()
                if imgui.begin_tab_item('Teleport')[0]:
                    self.teleport_panel.draw();imgui.end_tab_item()
                imgui.end_tab_bar()
            return
        imgui.separator()
        if imgui.begin_tab_bar('SaveEditorTabs'):
            if imgui.begin_tab_item('Actors')[0]:
                self.actors_panel.draw()
                imgui.end_tab_item()
            if imgui.begin_tab_item('Collision')[0]:
                self.collision_panel.draw()
                imgui.end_tab_item()
            if imgui.begin_tab_item('Camera')[0]:
                self.camera_panel.draw()
                imgui.end_tab_item()
            imgui.begin_disabled(not self.connected or busy)
            if imgui.begin_tab_item('Teleport')[0]:
                self.teleport_panel.draw()
                imgui.end_tab_item()
            if imgui.begin_tab_item('General')[0]:
                self.general()
                imgui.end_tab_item()
            if imgui.begin_tab_item('Inventory')[0]:
                self.inventory()
                imgui.end_tab_item()
            if imgui.begin_tab_item('Equipment')[0]:
                if imgui.begin_table('equipmentCards',2,imgui.TableFlags_.sizing_stretch_same):
                    imgui.table_next_column()
                    self.start_card('Equipment')
                    for actors in model.EQUIPMENT_ROWS:
                        for i,actor in enumerate(actors):
                            if i:imgui.same_line()
                            self.item(self.binding.items[actor])
                    self.end_card()
                    self.upgrades()
                    imgui.table_next_column()
                    self.group('Masks',{'Masks','RemakeMasks'})
                    self.group('Additional gear',{'EquipmentExtras'})
                    imgui.end_table()
                imgui.end_tab_item()
            if imgui.begin_tab_item('Songs')[0]:
                self.songs_panel.draw()
                imgui.end_tab_item()
            if imgui.begin_tab_item('Quest Status')[0]:
                self.group('Quest items',{'Quest'})
                self.group('Fishing',{'Fishing'})
                imgui.end_tab_item()
            imgui.end_disabled()
            imgui.end_tab_bar()
        self.collision_panel.tick()

def main():
    backend.prepare_profile()
    hello_imgui.set_assets_folder(str(backend.ROOT/'assets'))
    editor = Editor()
    params = hello_imgui.RunnerParams()
    params.app_window_params.window_title = 'Ocarina of Time - Debug Menu'
    params.app_window_params.window_geometry.size = (920,680)
    params.app_window_params.restore_previous_geometry = True
    params.callbacks.show_gui = editor.gui
    editor.runner_params = params
    def fonts():
        import os
        font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/segoeui.ttf'
        if font.exists():imgui.get_io().font_default=imgui.get_io().fonts.add_font_from_file_ttf(str(font),16)
    params.callbacks.load_additional_fonts = fonts
    def style():
        imgui.get_io().font_global_scale = 1.0
        imgui.get_style().item_spacing = (8,8)
        imgui.get_style().window_padding = (12,10)
        imgui.get_style().child_rounding = 3
    params.callbacks.post_init = style
    params.fps_idling.fps_idle = 20
    try:hello_imgui.run(params)
    finally:
        editor.controller_panel.close()
        editor.collision_panel.close()
        editor.hotkeys_panel.hotkeys.close()
        try:
            editor.worker.submit(editor.camera_panel.stop).result(timeout=8)
        except Exception:
            logging.exception('Camera cleanup failed; use Restore normal camera after reconnecting')
        editor.worker.shutdown(wait=False, cancel_futures=False)

if __name__ == '__main__':
    try:main()
    except Exception:
        logging.exception('Inventory editor stopped')
        raise
