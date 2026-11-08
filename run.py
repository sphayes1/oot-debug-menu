"""Run the independent debug client; optional game launch uses local settings."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'editor'),str(ROOT)]
from tools.prepare_data import prepare

def main():
    prepare()
    if '--self-check' in sys.argv:
        import app
        from actor_catalog import ActorCatalog
        e=app.Editor()
        try:
            catalog=ActorCatalog()
            assert len(catalog.actors(candidate=1,placed_only=False))==51
            assert catalog.actors(candidate=1,placed_only=False)[0]['id']=='Obj_TBox_A_01'
        finally:
            e.hotkeys_panel.hotkeys.close();e.worker.shutdown()
        print('Debug client and actor catalogue: OK; no game launched')
        return
    if '--start-game' in sys.argv:
        from launcher import launch_game
        launch_game()
    import app
    app.main()

if __name__=='__main__':main()
