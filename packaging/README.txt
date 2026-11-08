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
Ctrl+Alt+F5: quick save. Ctrl+Alt+F9: load newest save, including autosaves.

CONTROLLER
If your controller already works in another Lichii setup, close the game and
run Import Controller Settings.cmd. Select that emulator's configuration file.
The import tool preserves this package's graphics/storage settings.
Start Keyboard + Debug Menu.cmd switches back to keyboard controls.

SAVES
Save normally in the game, or use the quick-save shortcut. Your progress is in
editor\runtime\nand. Close the game before copying/backing up that folder.
Mainline and Optimized use separate profiles; see START HERE.txt to move a save.

QUICK FIXES
Disconnected: load gameplay until Link can move, then Connect / Refresh.
Keys or game file missing/moved: close the game and run Setup.cmd again.
Game already running: close the other emulator session and start one package.
Need just the menu again: Open Debug Menu.cmd.
Need help: run Check Setup.cmd and report its message and your package version.

PACKAGE VERSION
Variant: @VARIANT@
Emulator revision: @REVISION@
Mainline uses official Lichii source plus the debug bridge. Optimized uses our
accepted custom executable and additional performance profile. The tools are the
same. Game files, keys, personal saves and extracted item artwork are supplied
or generated locally during Setup.
