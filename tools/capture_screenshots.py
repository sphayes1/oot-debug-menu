"""Capture the real public menu renderer, with no desktop or cursor capture."""
from pathlib import Path
import argparse, hashlib, json, os, sys, time

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--portable',type=Path,required=True)
    parser.add_argument('--tab',choices=['Actors','Teleport','General','Inventory','Equipment','Songs'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    package=args.portable.resolve();out=args.output.resolve();out.parent.mkdir(parents=True,exist_ok=True)
    icons=json.loads((package/'editor/assets/icons/manifest.json').read_text())
    assert all(row['kind']=='original-label' for row in icons['icons'])
    sys.path[:0]=[str(package),str(package/'editor')]
    import portable
    import app
    from imgui_bundle import hello_imgui,imgui
    from PIL import Image
    editor=app.Editor()
    editor.values=editor.connect()
    assert editor.values.get('location'), 'Load gameplay before capturing menus'
    editor.connected=True;editor.message='Connected to gameplay.'
    if args.tab=='Actors':
        editor.actors_panel.candidate=1
        editor.actors_panel.actor='Obj_TBox_A_01'
    hello_imgui.set_assets_folder(str(package/'editor/assets'))
    params=hello_imgui.RunnerParams()
    params.app_window_params.window_title='Ocarina Debug Menu - Documentation Capture'
    height=960
    params.app_window_params.window_geometry.size=(1280,height)
    params.app_window_params.restore_previous_geometry=False
    params.app_window_params.hidden=True
    params.ini_filename=str(out.with_suffix('.capture.ini'))
    params.fps_idling.enable_idling=False
    frames=0
    original=imgui.begin_tab_item
    def selected(label,p_open=None,flags=0):
        if label==args.tab:flags|=imgui.TabItemFlags_.set_selected
        return original(label,p_open,flags)
    imgui.begin_tab_item=selected
    def fonts():
        font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/segoeui.ttf'
        if font.exists():imgui.get_io().font_default=imgui.get_io().fonts.add_font_from_file_ttf(str(font),16)
    def style():
        imgui.get_io().mouse_draw_cursor=False
        imgui.get_style().item_spacing=(8,8)
        imgui.get_style().window_padding=(12,10)
        imgui.get_style().child_rounding=3
    def draw():
        nonlocal frames
        editor.last_poll=time.monotonic()
        editor.gui()
        frames+=1
        if frames>=10:params.app_shall_exit=True
    params.callbacks.load_additional_fonts=fonts
    params.callbacks.post_init=style
    params.callbacks.show_gui=draw
    try:
        hello_imgui.run(params)
        pixels=hello_imgui.final_app_window_screenshot()
        assert pixels.size and pixels.shape[:2]==(height,1280),str(pixels.shape)
        Image.fromarray(pixels).save(out,optimize=True)
        report=dict(tab=args.tab,method='HelloImGui final_app_window_screenshot (renderer framebuffer)',
            cursor_included=False,desktop_or_game_window_included=False,
            source_commit=json.loads((package/'portable-package.json').read_text())['debug_source_commit'],
            sha256=hashlib.sha256(out.read_bytes()).hexdigest(),width=1280,height=height)
        out.with_suffix('.capture.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report))
    finally:
        imgui.begin_tab_item=original
        editor.binding.client.close();editor.hotkeys_panel.hotkeys.close();editor.worker.shutdown()

if __name__=='__main__':main()
