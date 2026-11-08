# File guide

| File or directory | Role |
| --- | --- |
| `run.py` | Public entry point and offline self-check; prepares generated metadata/badges. |
| `launcher.py` | Debug-only launch, separate storage paths, session receipt and selected emulator/game checks. |
| `editor/app.py`, `presentation.py` | Main ImGui window and item/slot presentation rules. |
| `editor/live.py` | Loopback JSON client, current-session descriptor discovery and GameData validation. |
| `editor/backend.py` | Profile creation, typed save parsing and guarded offline save transactions. |
| `editor/assignments.py`, `bottles.py`, `capacities.py`, `enhancements.py`, `ocarinas.py` | Item assignments, bottle contents, ammo limits, upgrades and ocarina ownership/use fields. |
| `editor/native_requests.py`, `native_ui.py`, `player_life.py`, `player_magic.py` | Guarded native requests, result reporting and current player health/magic writers. |
| `editor/location_capture.py`, `locations.py` | Read current scene/pose and validate/store bookmarks. |
| `editor/teleport.py`, `teleport_ui.py`, `age_switch.py` | Scene/entrance teleport transport, UI and age reload with pose restoration. |
| `editor/position.py`, `position_ui.py` | Live coordinates, direct updates and axis nudges. |
| `editor/camera.py`, `camera_ui.py` | Revision-checked camera reading, unsaved native free-flight requests, camera-relative keyboard/mouse movement and teleporting Link to the observed viewpoint. |
| `mods/camera-protocol.json`, `docs/FREE-CAMERA.md` | Authored EventCamera graph additions, original asset hashes, native cutscene priority, mailbox ownership and live verification. The original PlayerCamera pack is unchanged. |
| `editor/equipment_sync.py`, `songs.py`, `songs_ui.py` | One-shot equipment refresh and native fixed-song acquisition. |
| `editor/collectibles.py`, `collectibles_ui.py` | Skulltula/bean destinations and bean planting. |
| `editor/hotkeys.py`, `save_actions.py`, `save-menu-patterns.json` | Foreground-scoped Windows shortcuts and English game-menu recognition. Pattern data contains small recognition crops, not full screenshots. |
| `editor/actor_catalog.py`, `actor_catalog_ui.py` | Indexed actor/placement queries, filters and guarded placement teleports. |
| `editor/*schema.json`, `editor/research/*schema.json`, `editor/data/` | Revision-pinned, reverse-engineered field layouts and item metadata. |
| `data/actor-catalog.sqlite3.gz`, `actor-catalog.json` | Compressed coordinate/physics metadata and integrity receipt; expanded locally on first run. No actor packs or models. |
| `editor/research/dynamic-selection/hand-selected.json` |51 selected definitions, comparison features, reasons and source hashes. |
| `data/icon-ids.json`, `tools/prepare_data.py` | Identifier list and original text-badge/music-note drawing. No extracted game/SoH sprites. |
| `tools/nup.py`, `tools/assets.py` | Read-only indexed NUP access and decompression with the dump's own dictionaries. |
| `tools/setup_game.py` | Builds only debug overrides from the user's source members and writes ignored local settings. |
| `mods/recipes.json`, `mods/exefs/*.ips`, `mods/manifest.json` | Minimal patch recipes, authored scene-selector patch and expected output hashes/protocol versions. |
| `emulator-bridge/` | Source-only debug delta and pinned upstream provenance. |
| `emulator-bridge/mainline117-guarded-writer.patch`, `mainline117-provenance.json` | Five bridge/lock files against official build117 plus one behavior-preserving local variable rename for MSVC compatibility; upstream renderer/timing behavior is preserved. |
| `packaging/build_release.py`, `bundle_python.py`, `portable.py` | Build either self-contained portable variant from one client source and explicit external emulator/profile inputs. |
| `tools/apply_profile.py` | Source/output-hash-checked external emulator override application. Mainline refuses all custom environment/override entries. |
| `docs/GETTING-STARTED.md`, portable `START HERE.txt` | Beginner download/extraction, first launch, connect, controls, save migration and troubleshooting walkthrough. |
| `tools/controller_config.py`, portable `Import Controller Settings.cmd` | Imports only Controls from a working emulator configuration; rendering and storage settings stay intact. |
| `docs/SCREENSHOTS.md`, `docs/screenshots/` | Nine menu-only screenshots from the public renderer, with no cursor, click overlay, desktop or game window. The manifest pins each image hash and captured client revision. |
| `tools/capture_screenshots.py` | Read-only connected-menu framebuffer export for refreshing documentation images; requires a configured public portable profile and loaded gameplay. |
| `editor/test_*.py`, `.github/workflows/tests.yml` | Offline behavior/boundary tests and Windows CI. |

All personal/runtime data belongs under ignored paths. The main development
workspace and old private bundle retain their existing files and launchers;
this standalone tree does not relocate or rewrite that working session.

Camera asset mapping: `Pack/Actor/EventCamera.pack.zs` contains
`AI/EventCamera.root.ainb`, which runs in the actor's PostSensor AI stage.
The camera recipe adds an optional `ExecuteCameraSetTarget` and
`ExecuteCameraSwitchActiveToOwn` branch. The original root remains the fallback;
`QueryIsPlayingMainEvent` takes priority over the debug request. RESTBL allocations
for the pack and its inner AI grow with this graph. Independent movement, looking,
normal-camera restoration and teleport-to-camera were observed in live gameplay
on 2026-11-08. See the camera guide for limitations and controls.

Collision mapping (2026-11-08):

| File / member | Purpose |
| --- | --- |
| `editor/collision_ui.py`, `collision.py` | Collision tab, coalesced read-only camera snapshots, session guards and renderer lifetime. |
| `editor/collision_overlay.py` | Transparent, click-through GLFW 3.4/OpenGL companion over the game client; shares no GL context with ImGui. |
| `editor/collision_geometry.py`, `collision_scene.py` | Bounded Phive/BYML readers, primitive tessellation, actor transforms, nearby-tile selection and ignored local cache. |
| `Phive/StaticCompoundBody/<area>/*.bphsc.zs` | Terrain/compound mesh geometry, compressed vertices and baked shape instances. Tiled terrain has 250-unit X/Z tiles and an embedded origin. |
| `Phive/Shape/Dcc/*.bphsh.zs` | Local-space actor collision meshes referenced from shape parameters. |
| `Pack/Actor/*.pack.zs` | ActorParam PhysicsRef → ControllerSet → ShapeParam, including inherited boxes/cylinders/spheres/capsules/meshes. |
| `Banc/<area>/*_{Static,Dynamic}.bcett.byml.zs` | Placement transforms and AI references for authored walls, recognized reset/no-respawn/loading volumes. |
| Camera manager + `0x3ab0`, + `0x3b50` | Validated view and row-major perspective projection used for overlay alignment. |
| `editor/runtime/collision/` | Private geometry derived locally from the user's NUP. Never included in source or portable packages. |
| `docs/COLLISION.md`, `editor/test_collision.py` | Controls, coverage/provenance, observed live acceptance and reader/session/worker regression checks. |

Phive owner/material ranges do not reliably correspond to concatenated TAG0
instance order in this dump. Sensor exclusion uses authored position/scale;
global material IDs are not presented as verified gameplay surface types.
Live overlay alignment, normal Link movement and native free-camera movement
were observed in Castle Town. Runtime moving actor collision remains untracked.

Controller mapping (2026-11-08): `editor/controller.py` owns validation,
game-focus-scoped native polling, analog shaping and ignored local
`controller-hotkeys.json`. `controller_ui.py` provides shortcut editing/recording
and dispatches onto the existing game IO worker. `camera_ui.py` now flushes
controller flight independently of the Camera tab; a successful teleport restores
normal view. `hotkeys.py` exposes the same normal save/load operation to both
keyboard and controller dispatch, including automatic confirmations.

`emulator-bridge/controller/` contains the native leased capture state machine,
RPC insertion and focused C++ tests. `controller-{optimized,mainline}.patch`
applies after the corresponding existing bridge patch; controller-provenance.json
pins the exact before/after sources. Only mapped HID input and the debug server
change. All original debug operations stay serialized on one worker; only the
bounded controller heartbeat runs on the IO thread, so frame-timed save/load
does not starve the two-second input lease. Scripted input is applied after
physical-input filtering. No renderer, game asset or performance setting changes.
