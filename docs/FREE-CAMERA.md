# Free-flight camera

Load gameplay, click **Connect / Refresh**, and open the **Camera** tab.
Check **Free flight debug camera**. Keep the debug-menu window and Camera tab
focused for keyboard flight. Restore the normal camera before controlling Link.

Controller flight also works with the game focused, regardless of the selected
debug tab: **LB/L + Minus** enters, **B** exits, **A** teleports and exits. The
left stick moves, right stick looks, and **LT/RT** fly down/up. Customize these
under **Controller...**. See [controller setup](CONTROLLER.md).

| Control | Action |
| --- | --- |
| W / S | Fly forward / backward in the direction the camera faces |
| A / D | Strafe left / right |
| Q / E | Move down / up in world height |
| Hold right mouse and drag | Look around |
| Hold Shift | Move four times faster |
| Speed slider | Set normal flight speed |
| Escape / Restore normal camera | Return to the normal following camera |
| Teleport Link to camera | Move Link to the viewpoint and restore normal view |

Flight does not move Link. Teleporting stays inside the loaded area. The camera
passes through geometry; Link still collides, falls and triggers loading zones.
Save/load, other debug edits and area changes end free flight. Closing the editor
normally clears its request. If the editor stops unexpectedly, reopen it and click
**Connect / Refresh** or **Restore normal camera** to recover the normal view.

Existing portable downloads need an updated client **and** regenerated game-side
overrides. Source users should close the game and rerun the normal setup command
after updating. No emulator rebuild or performance-profile change is required.

## Implementation and verification

The revision-pinned recipe edits only `AI/EventCamera.root.ainb` inside
`Pack/Actor/EventCamera.pack.zs`, plus its two resource-size table allocations.
It retains the original event-camera fallback and leaves the PlayerCamera asset
unchanged. A native `QueryIsPlayingMainEvent` gate prioritizes scripted events.
The new branch sets the resident event camera's eye/look-at and selects that
camera; the original fallback resumes following when the request is cleared.
The authored additions and original/result hashes are in `mods/camera-protocol.json`.

| Unsaved GameData field | Use |
| --- | --- |
| `Sequence_ReservedNextStartPosName` (`0b570ab2`) | Exact `__OOT_FREE_CAMERA_V1__` activation token; shared with entrance/song requests |
| `DebugParam.OverrideTraversePos` (`527fa715`) | Camera eye; also the one-shot player-position payload |
| `Sequence_ReservedNextCancelSleepRot` (`1662143e`) | Camera look-at |

The client serializes these requests with other debug operations. It publishes
the activation token last, clears it before restoring payloads, validates the
current session and scene, and refuses another operation's mailbox contents.
Movement writes are coalesced into one background job at a time. Teleport uses
the observed camera eye and the existing acknowledged native position request.

The rendered view is read from the revision-checked camera-manager slot at
main+`0x4e371e8`, checked through GOT main+`0x4c7dda0` and manager vtable
main+`0x4b73d20`. Its 3x4 view matrix is at manager+`0x3ab0`; the world eye is
`-transpose(R) * translation`. Addresses are resolved afresh for each session.

Live checks on 2026-11-08 demonstrated independent camera translation in adult
Hyrule Field and Market, looking, unchanged Link position during flight, normal
camera restoration, and teleporting Link to the camera. The user observed the
teleport triggering a nearby loading zone. The actual ImGui checkbox, W input and
Escape recovery were also exercised. Native cutscene priority is checked in the
graph; a full story-cutscene regression has not yet been performed. Child-era
and dungeon coverage remain to be exercised.
