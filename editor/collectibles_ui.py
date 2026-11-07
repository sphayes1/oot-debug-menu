"""Separate Skulltula and bean dropdowns in the Teleport tab."""
from imgui_bundle import imgui
from collectibles import CATALOG,BEANS,BeanState,destination


class CollectiblesPanel:
    def __init__(self,editor,teleport_panel):
        self.editor=editor;self.teleport=teleport_panel
        self.selected={'skulltulas':0,'beans':0}

    def plant_job(self,ids):
        BeanState(self.editor.binding).plant(ids)
        return self.editor.connect()

    def draw(self):
        imgui.separator_text('Collectible locations')
        self.dropdown('skulltulas','Gold Skulltulas (100)')
        imgui.text_wrapped('Skulltula warps use exact actor placements with a small height clearance. Wall/ceiling targets can leave you airborne. Night, bugs and other spawn requirements still apply.')
        self.dropdown('beans','Bean patches (11)')
        states=(self.editor.values or {}).get('beans',{})
        imgui.text('Planted: %d / 11'%sum(states.values()))
        selected=CATALOG['beans'][self.selected['beans']]
        idle=not self.teleport.unavailable()
        imgui.begin_disabled(not idle or states.get(selected['id'],False))
        if imgui.button('Plant selected bean'):
            self.editor.native_undo_blocked=True
            self.editor.submit('Plant bean',lambda key=selected['id']:self.plant_job([key]))
        imgui.end_disabled();imgui.same_line()
        imgui.begin_disabled(not idle or (len(states)==11 and all(states.values())))
        if imgui.button('Plant all 11 beans'):
            self.editor.native_undo_blocked=True
            self.editor.submit('Plant all beans',lambda:self.plant_job(list(BEANS)))
        imgui.end_disabled()
        imgui.text_wrapped('Planting sets only the selected patch flags, without consuming inventory beans. The current area reloads if its patch changes; remote patches appear planted when visited. A grown platform requires Adult Link.')

    def dropdown(self,kind,label):
        rows=CATALOG[kind];index=self.selected[kind]
        age=(self.editor.values or {}).get('gear',{}).get('active_age','Child')
        imgui.push_id(kind)
        if imgui.begin_combo(label,rows[index]['label']):
            for i,row in enumerate(rows):
                pose=destination(row,age)
                suffix=' / '+pose['age']
                if imgui.selectable('%03d | '%(i+1)+row['label']+suffix,i==index)[0]:self.selected[kind]=i
            imgui.end_combo()
        row=rows[self.selected[kind]];pose=destination(row,age)
        if row.get('notes'):imgui.text_disabled('; '.join(row['notes']))
        imgui.begin_disabled(self.teleport.unavailable(pose['age']))
        if imgui.button('Teleport to selected '+('Skulltula' if kind=='skulltulas' else 'bean patch')):
            self.teleport.queue_warp(pose,CATALOG['source_sha256'])
        imgui.end_disabled()
        if self.teleport.unavailable(pose['age']) and self.editor.connected:
            imgui.text_disabled('Requires '+pose['age']+' Link, or Allow any era.')
        imgui.pop_id()
