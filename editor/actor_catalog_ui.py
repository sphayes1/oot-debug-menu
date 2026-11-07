"""Dedicated searchable actor catalogue with paged placement teleport controls."""
import json,math
from imgui_bundle import imgui
from actor_catalog import ActorCatalog,FILTERS,FAMILIES,PAGE_SIZE,label,restrictions


class ActorsPanel:
    def __init__(self,editor):
        self.editor=editor;self.catalog=None;self.error=''
        self.search='';self.area=0;self.era=0;self.candidate=0;self.family=0;self.placed_only=False
        self.height=2.;self.actor=None;self.selected=None;self.page=0
        self.actor_key=None;self.place_key=None;self.rows=[];self.page_data={'rows':[],'count':0,'page':0}

    def refresh(self,area,age):
        key=(self.search,area,age,self.candidate,self.family,self.placed_only)
        if key!=self.actor_key:
            self.rows=self.catalog.actors(self.search,area,age,self.candidate,self.family,self.placed_only)
            if self.actor not in {r['id'] for r in self.rows}:
                self.actor=self.rows[0]['id'] if self.rows else None;self.page=0;self.selected=None
            self.actor_key=key;self.place_key=None
        key=(self.actor,area,age,self.page)
        if key!=self.place_key:
            self.page_data=self.catalog.placements(self.actor,area,age,self.page) if self.actor else {'count':0,'page':0,'rows':[]}
            self.page=self.page_data['page'];self.place_key=(self.actor,area,age,self.page)
            if self.selected not in {r['id'] for r in self.page_data['rows']}:
                self.selected=self.page_data['rows'][0]['id'] if self.page_data['rows'] else None

    def queue(self,key):
        height=self.height;allow=self.editor.teleport_panel.allow_any_era
        self.editor.native_undo_blocked=True
        def job():
            self.catalog.teleport(self.editor.binding,key,height,allow)
            return self.editor.connect()
        self.editor.submit('Actor teleport',job)

    def unavailable(self,row,active):
        if self.editor.teleport_panel.unavailable():return 'Connect and wait for the current operation to finish.'
        return restrictions(row,active,self.editor.teleport_panel.allow_any_era)

    def draw(self):
        if self.catalog is None:
            try:self.catalog=ActorCatalog()
            except Exception as exc:self.error=str(exc)
        if self.catalog is None:
            imgui.text_wrapped('Actor catalogue unavailable: '+self.error);return
        active=(self.editor.values or {}).get('gear',{}).get('active_age','')
        current=(self.editor.values or {}).get('location',{}).get('banc','')
        imgui.text('Actor catalogue | '+format(int(self.catalog.meta['actor_count']),',')+' definitions | '+
                   format(int(self.catalog.meta['placement_count']),',')+' original placements')
        imgui.set_next_item_width(min(620.,max(160.,imgui.get_content_region_avail().x*.65)))
        _,self.search=imgui.input_text('Find actor (name or type)',self.search)
        imgui.set_next_item_width(280.)
        _,self.candidate=imgui.combo('Physics filter',self.candidate,list(FILTERS))
        imgui.same_line();_,self.placed_only=imgui.checkbox('With placed locations only',self.placed_only)
        imgui.set_next_item_width(280.)
        _,self.area=imgui.combo('Area',self.area,['All areas','Current area']+[label(a) for a in self.catalog.areas])
        imgui.same_line();imgui.set_next_item_width(160.)
        _,self.era=imgui.combo('Era',self.era,['Current Link','Child','Adult','Any'])
        imgui.set_next_item_width(280.)
        _,self.family=imgui.combo('Name family',self.family,list(FAMILIES))
        imgui.same_line()
        _,self.editor.teleport_panel.allow_any_era=imgui.checkbox('Allow any era (untested)',self.editor.teleport_panel.allow_any_era)
        if self.editor.teleport_panel.allow_any_era:
            imgui.text_colored((1.,.7,.25,1.),'Untested era override: Link keeps his age; events and spawns may differ. Choose Era: Any to browse both.')
        imgui.set_next_item_width(120.)
        _,height=imgui.input_float('Arrival height above actor (Y)',self.height,.5,2.,'%.1f')
        self.height=max(0.,min(100.,height)) if math.isfinite(height) else 2.
        imgui.text_wrapped('Original placement anchors, not live actor positions. Large, moving or wall-mounted objects may leave you inside geometry or airborne; adjust arrival height. Spawn conditions still apply.')
        area='' if self.area==0 else current or '__not_loaded__' if self.area==1 else self.catalog.areas[self.area-2]
        age=active if self.era==0 else ('Child' if self.era==1 else 'Adult' if self.era==2 else '')
        try:self.refresh(area,age)
        except Exception as exc:imgui.text_wrapped(str(exc));return
        imgui.separator()
        if imgui.begin_table('actor-browser-panes',2,imgui.TableFlags_.resizable|imgui.TableFlags_.sizing_stretch_prop):
            imgui.table_setup_column('Actor definitions',0,.4)
            imgui.table_setup_column('Placed locations',0,.6)
            imgui.table_next_column()
            imgui.text(str(len(self.rows))+' matching actor definitions')
            imgui.begin_child('actor-definitions',(0,max(220.,imgui.get_content_region_avail().y-8)),imgui.ChildFlags_.border)
            clipper=imgui.ListClipper();clipper.begin(len(self.rows))
            while clipper.step():
                for i in range(clipper.display_start,clipper.display_end):
                    row=self.rows[i];text=row['id']+' ('+str(row['matches'])+')'
                    if imgui.selectable(text,self.actor==row['id'])[0]:
                        self.actor=row['id'];self.page=0;self.selected=None;self.place_key=None
                    if imgui.is_item_hovered():imgui.set_tooltip(row['label']+'\n'+str(row['matches'])+' placements in these filters; '+str(row['coordinates'])+' with explicit coordinates')
            imgui.end_child()
            imgui.table_next_column()
            imgui.begin_child('actor-placement-pane',(0,max(220.,imgui.get_content_region_avail().y-8)),imgui.ChildFlags_.border)
            # Selection can change in the left pane during this frame.
            self.refresh(area,age)
            row=next((r for r in self.rows if r['id']==self.actor),None)
            if row:self.placements(row,active,area,age)
            else:imgui.text_wrapped('No matches. Try another search, area, era or physics filter.')
            imgui.end_child();imgui.end_table()

    def placements(self,actor,active,area,age):
        imgui.text_wrapped(actor['label'])
        imgui.text_wrapped(actor['id'])
        if actor['closest']:imgui.text_colored((.7,.9,.7,1.),'Hand selected dynamic actor')
        elif actor['tier']:imgui.text_disabled('Physics: '+actor['tier'])
        count=self.page_data['count'];pages=max(1,(count+PAGE_SIZE-1)//PAGE_SIZE)
        if not count:
            if actor['placement_count']:
                imgui.text_wrapped('No placements match the selected area/era. Choose All areas and Era: Any.')
            else:
                imgui.text_wrapped('No direct world placement. This is a spawned, held, event-created, unused or base actor definition; it has no fixed teleport destination in this catalogue.')
            self.actor_details(actor);return
        imgui.text(str(count)+' placements | Page '+str(self.page+1)+' / '+str(pages))
        imgui.begin_disabled(self.page==0)
        if imgui.button('Previous'):self.page-=1
        imgui.end_disabled();imgui.same_line();imgui.begin_disabled(self.page+1>=pages)
        if imgui.button('Next'):self.page+=1
        imgui.end_disabled();imgui.same_line();imgui.set_next_item_width(85.)
        changed,page=imgui.input_int('Page',self.page+1)
        if changed:self.page=max(0,min(pages-1,page-1))
        self.refresh(area,age)
        if imgui.begin_table('actor-placement-table',3,imgui.TableFlags_.row_bg|imgui.TableFlags_.borders_inner_h|imgui.TableFlags_.scroll_y,
                             (0,max(140.,min(400.,imgui.get_content_region_avail().y-170)))):
            imgui.table_setup_column('Go',imgui.TableColumnFlags_.width_fixed,42.)
            imgui.table_setup_column('Area / instance',imgui.TableColumnFlags_.width_stretch)
            imgui.table_setup_column('X, Y, Z',imgui.TableColumnFlags_.width_fixed,175.)
            imgui.table_setup_scroll_freeze(0,1);imgui.table_headers_row()
            for row in self.page_data['rows']:
                imgui.push_id(row['id']);imgui.table_next_row();imgui.table_next_column()
                error=self.unavailable(row,active)
                imgui.begin_disabled(bool(error))
                if imgui.small_button('Go'):self.selected=row['id'];self.queue(row['id'])
                imgui.end_disabled()
                imgui.table_next_column()
                if imgui.selectable(label(row['banc'])+'##location',self.selected==row['id'])[0]:self.selected=row['id']
                if imgui.is_item_hovered():imgui.set_tooltip('Actor instance: '+row['actor_hash']+('\n'+error if error else ''))
                imgui.table_next_column()
                imgui.text('%.2f, %.2f, %.2f'%(row['x'],row['y'],row['z']) if row['has_position'] else 'No explicit XYZ')
                imgui.pop_id()
            imgui.end_table()
        row=next((r for r in self.page_data['rows'] if r['id']==self.selected),None)
        if row:
            imgui.separator();imgui.text_wrapped(label(row['banc'])+' | '+row['actor_hash'])
            if row['has_position']:imgui.text('Actor XYZ: %.3f, %.3f, %.3f'%(row['x'],row['y'],row['z']))
            error=self.unavailable(row,active);imgui.begin_disabled(bool(error))
            if imgui.button('Teleport to selected placement'):self.queue(row['id'])
            imgui.end_disabled()
            if error:imgui.text_wrapped(error)
            if imgui.tree_node('Spawn conditions / placement data'):
                presence=json.loads(row['presence']);dynamic=json.loads(row['dynamic'])
                imgui.text_wrapped('Presence: '+(json.dumps(presence) if presence else 'No placement flag restriction recorded'))
                imgui.text_wrapped('Dynamic parameters: '+json.dumps(dynamic))
                imgui.text_wrapped('Source: '+row['source']);imgui.tree_pop()
        self.actor_details(actor)

    @staticmethod
    def actor_details(actor):
        if imgui.tree_node('Actor definition / physics'):
            imgui.text_wrapped('Logic: '+(actor['logic'] or 'No explicit actor logic reference'))
            imgui.text_wrapped('Native class: '+(actor['class_name'] or 'Not listed'))
            for body in json.loads(actor['physics']):
                imgui.text_wrapped(body['name']+': '+str(body['motion'])+' / '+str(body['layer']))
            imgui.text_wrapped('Source: '+actor['source'])
            if imgui.button('Copy actor name'):imgui.set_clipboard_text(actor['id'])
            imgui.tree_pop()
