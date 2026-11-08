# Collision overlay

1. Start the game and debug menu using your usual launcher. Load gameplay.
2. Click **Connect / Refresh**, open **Collision**, and check **Show collision overlay**.
3. Click the game window to play normally. Collision stays visible and the
   overlay passes mouse clicks through to the game.
4. To explore without moving Link, open **Camera** and enable free flight.
   Keep that tab focused for WASD, Q/E and right-drag controls. Collision
   follows the camera. **Teleport Link to camera** still works.
5. Uncheck the collision toggle to remove the overlay. Closing the debug menu
   also removes it.

No Cheat Engine, separate viewer or RomFS extraction is needed. The menu finds
the NUP selected during Setup, reads it without modifying it, and builds a
private cache under `editor/runtime/collision`. The first visit to a large area
can take several seconds. Nearby tiles load as the camera moves. A distance of
100 units is a useful starting point; a smaller distance reduces clutter.

Use windowed or borderless mode. The overlay fits the game's projection inside
its client area, including letterboxing, and follows window movement/resizing.
It hides when the game is minimized, another application has focus, loading
starts, fresh camera data stops, or the game connection is lost. Reconnect and
enable it again after restarting the emulator.

The filters show neutral terrain/baked solids, red authored invisible walls,
orange climb/push walls, purple recognized void/reset zones, teal no-respawn
zones and blue loading volumes. Other actor walls are optional. **Translucent
surfaces** adds faint faces; **X-ray** shows collision behind other collision.
The overlay has its own depth buffer, so it can draw over Link and the HUD.

This is authored collision visualization. Moving objects, removed objects,
conditional activation and spawned actors are not tracked live. Curves are
tessellated, and only recognized trigger logic is classified. No approximate
actor bounding boxes are substituted for missing collision meshes. Unsupported
geometry is reported in the tab. Colours describe the identified source type;
they do not prove that every wall affects Link. The overlay changes no game
collision, graphics settings or save fields. Drawing it uses additional GPU
time, especially with X-ray or a large distance.

## Implementation and provenance

The format investigation was informed by
[mrissaoussama/oot26-tools](https://github.com/mrissaoussama/oot26-tools/tree/5c8d03ecf674bf62c7e72954c885b6f177e71480).
This project implements its own bounded readers and OpenGL overlay. It does
not distribute that viewer's code, prebuilt geometry, game files or CE table.

`collision_geometry.py` decodes Phive TAG0 mesh/convex/compound data and primitive
shapes. `collision_scene.py` reads the user's NUP, applies authored transforms,
selects nearby 250-unit tiles, classifies actor walls/recognized areas, and
publishes local NumPy caches. BYML inheritance and decompression reuse the dump's
own dictionaries. Non-solid baked areas are excluded by matching authored
position/scale. In the tested dump, owner/material global indices did not
consistently correspond to compound-array order; baked geometry remains neutral
instead of claiming verified material colours or per-actor ownership.

`collision.py` validates the game session, camera-manager revision, typed area
object and camera matrices through the existing loopback bridge. View data is
at manager + `0x3ab0`; the row-major perspective matrix is at + `0x3b50`.
`collision_ui.py` coalesces reads on the existing editor worker, leaving native
free flight active. Old session/area snapshots are never paired with a newly
decoded mesh.

`collision_overlay.py` runs a separate OpenGL context/process using GLFW 3.4
mouse pass-through and per-pixel transparency. It accepts authenticated local
UDP snapshots from its parent, validates mesh paths inside its own runtime,
and exits when the parent closes or its heartbeat stops. The renderer never
writes game memory. Set `OOT_COLLISION_CAPTURE=1` only for development to save
one cursor-free overlay framebuffer to `editor/runtime/collision-preview.png`.

Live validation on 2026-11-08 used the isolated optimized camera lab and OOT
1.1.1, original main SHA256
`7db9ddfda088c22d219ef13496decd7077c68cd67d4b37f53f4ac46a082768f2`.
The overlay was observed over Castle Town, Link moved 7.35 world units with it
enabled, and an independent free-camera move was observed within 0.00002 units
of its target. Other areas and runtime actor changes are not exhaustively
validated. This feature does not establish a new performance baseline.
