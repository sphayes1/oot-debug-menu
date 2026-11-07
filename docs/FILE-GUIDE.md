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
| `emulator-bridge/mainline117-guarded-writer.patch`, `mainline117-provenance.json` | Minimal five-file guarded writer port against official build117; renderer and timing source remain upstream. |
| `packaging/build_release.py`, `bundle_python.py`, `portable.py` | Build either self-contained portable variant from one client source and explicit external emulator/profile inputs. |
| `tools/apply_profile.py` | Source/output-hash-checked external emulator override application. Mainline refuses all custom environment/override entries. |
| `docs/GETTING-STARTED.md`, portable `START HERE.txt` | Beginner download/extraction, first launch, connect, controls, save migration and troubleshooting walkthrough. |
| `tools/controller_config.py`, portable `Import Controller Settings.cmd` | Imports only Controls from a working emulator configuration; rendering and storage settings stay intact. |
| `editor/test_*.py`, `.github/workflows/tests.yml` | Offline behavior/boundary tests and Windows CI. |

All personal/runtime data belongs under ignored paths. The main development
workspace and old private bundle retain their existing files and launchers;
this standalone tree does not relocate or rewrite that working session.
