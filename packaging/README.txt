START HERE - OOT DEBUG MENU (@VARIANT@)

1. Right-click the downloaded ZIP and choose Extract All.
2. Open the extracted folder.
3. Double-click Start Ocarina + Debug Menu.cmd.
4. On the first run, select your Ocarina .nup. Select prod.keys and title.keys
   if Setup asks for them. Keeping the keys beside the .nup helps Setup find them.
5. The game and debug menu open in separate windows. Click the game window,
   then load a save or start New Game. On keyboard, C is A/Confirm.
6. Wait until you can control Link. Click the debug-menu window and choose
   Connect / Refresh. Look for Connected to gameplay in green.

You can now play and use the tools. Click inside the game window to control Link.
The first game launch can take longer while shaders are prepared.
Python is already included. Keep the .nup where you selected it during Setup.

FULL STEP-BY-STEP INSTRUCTIONS: Open START HERE.txt in this folder.
It includes a keyboard table, controller import, save migration and troubleshooting.

KEYBOARD BASICS
WASD: move. IJKL: camera. C: A/confirm/interact. X: B/cancel.
V: X/jump. Z: Y/attack. Q/E: L/R. R/T: ZL/ZR. M/N: Plus/Minus.
Arrow keys: D-pad. Left arrow: pull out an owned ocarina. Hold R: songbook.
F5: direct quick save. F6: load your last quick-save checkpoint. No menus.
Make a checkpoint with F5 first. Loading rebuilds the area (about 11-14 seconds
in local testing). These are game checkpoints, not full emulator save states.

CONTROLLER
If your controller already works in another Lichii setup, close the game and
run Import Controller Settings.cmd. Select that emulator's configuration file.
The import tool preserves this package's graphics/storage settings.
Start Keyboard + Debug Menu.cmd switches back to keyboard controls.

After loading gameplay, click Connect / Refresh. With the game focused:
LB/L + Minus enters the free camera. B exits. A teleports and restores normal view.
Left stick flies; right stick looks; LT/RT fly down/up.
All four shoulders + D-pad Left saves; D-pad Right loads the latest save.
Confirmations are handled automatically. Release the chord while it runs.
Click Controller... to customize these bindings and stick settings.

COLLISION
In the Collision tab, enable Show collision overlay. Keep playing normally,
or use the Camera tab/controller to fly through the area. Your NUP supplies
the geometry automatically; the first visit can take several seconds.
Use windowed or borderless mode. Moving/removed objects are not tracked live.

SAVES
Save normally in the game, or use the quick-save shortcut. Your progress is in
editor\runtime\nand. Close the game before copying/backing up that folder.
Mainline and Optimized use separate profiles; see START HERE.txt to move a save.

UPGRADING FROM AN OLDER DOWNLOAD
Extract the new ZIP into a new folder. Close both games before copying anything.
Copy your old editor\runtime\nand folder into the new package's editor\runtime.
You can also copy editor\locations.json, hotkeys.json and controller-hotkeys.json
if present. Run the new Setup.cmd; keep the new game overrides and emulator.

QUICK FIXES
Disconnected: load gameplay until Link can move, then Connect / Refresh.
Keys or game file missing/moved: close the game and run Setup.cmd again.
Game already running: close the other emulator session and start one package.
Need just the menu again: Open Debug Menu.cmd.
Need help: run Check Setup.cmd and report its message and your package version.

PACKAGE VERSION
Debug menu release: 0.2.1
Variant: @VARIANT@
Emulator revision: @REVISION@
Mainline uses official Lichii source plus the debug bridge. Optimized uses our
accepted custom executable and additional performance profile. The tools are the
same. Game files, keys, personal saves and extracted item artwork are supplied
or generated locally during Setup.
