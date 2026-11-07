# Architecture

| Layer | Responsibility | Performance ownership |
| --- | --- | --- |
| `editor/` | Dear ImGui controls, schemas, validation, worker serialization, audits | None |
| `launcher.py` | Separate storage profile, debug endpoint opt-in and launch receipt | Preserves user-provided renderer/input configuration |
| `tools/setup_game.py`, `mods/` | Source-hash-checked game-side debug override generation | No FPS, shadow or renderer overrides |
| `emulator-bridge/` | Compare-and-write and native queue validation delta | No renderer/timing patches |
| External emulator | CPU/GPU emulation, graphics/audio, scheduling and optimization | Owned outside this repository |

`live.Client` serializes newline-delimited JSON requests over one localhost
connection. `Bindings` resolves typed GameData descriptors from the current
session, checks the title, game revision, heap ranges and lookup maps, and
invalidates stale bindings. A single worker serializes game operations while
the UI continues rendering. An uncertain write is never automatically replayed.

Simple ownership/count changes use guarded compare-and-write. Native game
handlers consume one-shot debug requests for scene transitions, position changes,
equipment refresh and fixed-song acquisition. Pending events/menus/loads and
unsupported revisions are refused. Native operations invalidate generic undo.

`actor_catalog.py` opens short-lived, read-only SQLite connections. Search and
pagination do not modify game memory. Teleports resolve exact placement IDs,
check area and actor-presence age restrictions, then call the existing scene
transport. The database stores original anchors and source provenance, not live
actor transforms.

Native save/load shortcuts inspect bounded screen patterns before issuing input.
They automate the normal game menu, including confirmations, and stop on an
unknown state. They do not deserialize emulator state or overwrite save files.

Game-side recipes reference source ranges and modified bytes. Setup validates
the NUP table, every source member and all reconstructed output hashes before
publishing. The resource-table recipe updates allocation sizes for the edited
sequences; the small authored IPS patch enables the debug scene selector.
