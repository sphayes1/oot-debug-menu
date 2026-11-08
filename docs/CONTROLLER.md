# Controller camera and save shortcuts

Start gameplay, open the debug menu and click **Connect / Refresh**. Keep the
game window focused when using controller shortcuts. The menu can stay behind
the game; selecting the Camera tab is not required for controller flight.

| Default control | Action |
| --- | --- |
| LB / L + Minus (`-`) | Enter free camera |
| Left stick | Fly forward/back and strafe |
| Right stick | Look around |
| RT / ZR | Fly up |
| LT / ZL | Fly down |
| B | Exit camera and restore the normal view |
| A | Teleport Link to the camera, then restore normal view |
| LB + RB + LT + RT + D-pad Left | Quick save |
| LB + RB + LT + RT + D-pad Right | Load the newest save, including autosaves |

The names refer to the emulator's mapped game buttons. With an Xbox-style
controller, `L/R/ZL/ZR` correspond to `LB/RB/LT/RT`; A/B follow the game's
mapping, which may differ from the letters printed on your controller.

Camera input is consumed before it reaches the game, so the sticks do not move
Link while flying. The entry chord does not open the Minus menu; teleport A
and exit B do not also activate gameplay actions. Release the buttons and
centre the sticks before resuming normal play. Recognized chords fire once
per press and do not repeat while held.

Save/load uses the existing normal-save automation and handles confirmation
dialogs automatically. Menus briefly appear. Release the chord while it runs.
These are normal game saves, not emulator save states. Saving while in free
camera first restores the normal view and saves Link's actual position.

## Customize

Click **Controller...** at the top of the debug menu. Each action has an **Edit**
button. Either select its buttons with the checkboxes, or click **Record
controller combination**, focus the game, press the combination and release it.
Return to the menu and click **Apply controller settings**.

You can also swap movement/look sticks, change up/down buttons, tune deadzone
and look speed, or invert vertical look. Movement speed uses the existing
Camera tab slider. Settings persist in local `editor/controller-hotkeys.json`;
existing keyboard shortcuts remain in `editor/hotkeys.json`.

Empty, duplicate and overlapping shortcuts are rejected rather than silently
choosing an action. **Reset defaults**, then **Apply**, restores the table above.

The updated emulator bridge is required. If the Controller popup reports an
old bridge, use a build containing `controller_debug` protocol 1. Inventory,
keyboard shortcuts and keyboard camera remain available on the older bridge.
The controller uses the emulator's mapped Player 1 or Handheld input, supporting
the same devices the emulator supports; no separate XInput driver is installed.

The debug menu owns a two-second native input lease and refreshes it on a
dedicated connection. Closing/disconnecting the editor or an expired lease
releases capture. If the editor crashes with the native free camera still
enabled, reconnect and use **Restore normal camera**, as with keyboard flight.

Teleport remains limited to the current loaded area; gravity and loading zones
still apply. The collision overlay can remain enabled during controller flight.
