# Getting started

You can use the portable download without installing Python or building anything.
Keep your Ocarina `.nup`, `prod.keys` and `title.keys` available on this computer.
Putting the keys beside the `.nup` lets Setup find them automatically.

## 1. Download a version

Open the project's **Releases** page and expand **Assets**.

| Download | Choose it when |
| --- | --- |
| **OOT-Debug-Menu-Mainline-Win64.zip** | You want the standard Lichii build with the debug tools. Start here. |
| **OOT-Debug-Menu-Optimized-Win64.zip** | You want to try our additional performance settings and patches. |

The debug tools are the same in both. Performance depends on your computer.
Extract each version into its own folder if you want to try both.

## 2. Extract the ZIP

1. Right-click the downloaded ZIP and choose **Extract All**.
2. Choose a folder, such as `C:\Games\OOT Debug Menu`.
3. Open the extracted folder. You should see **Start Ocarina + Debug Menu.cmd**,
   **Setup.cmd**, and the `editor`, `emulator` and `python` folders.

Launch the `.cmd` files from this extracted folder.

## 3. Start the game and menu

Double-click **Start Ocarina + Debug Menu.cmd**.

On the first run, Setup asks you to select your Ocarina `.nup`. It may also ask
you to select `prod.keys` and `title.keys` if it cannot find them automatically.
After Setup finishes, the launcher opens **two windows**:

- **The game/emulator window** — play Ocarina here.
- **Ocarina of Time - Debug Menu** — change items, teleport and use the tools here.

The first launch can take longer while shaders are prepared. Keep the `.nup`
at the location you selected. Run **Setup.cmd** again if you move it.

## 4. Load gameplay, then connect

1. Click the **game window**.
2. Load a save or start **New Game**. On keyboard, **C** is A/Confirm.
3. Wait until you can control Link.
4. Click the **debug-menu window** and choose **Connect / Refresh**.
5. Check that the top of the menu says **Connected to gameplay** in green.

You are ready. Click back into the game window whenever you want to play.
Keep both windows open while using the tools.

## Basic controls

The portable package starts with keyboard controls.

| Action | Key |
| --- | --- |
| Move | W, A, S, D |
| Camera | I, J, K, L |
| A / confirm / interact | C |
| B / cancel / put away | X |
| X / jump | V |
| Y / attack | Z |
| L / R | Q / E |
| ZL / ZR | R / T |
| Plus / Minus | M / N |
| D-pad | Arrow keys |
| Pull out owned ocarina | Left arrow |
| Songbook while holding ocarina | Hold R (ZL) |

Controller settings depend on the controller. If you already have working
Lichii controller settings, close the game and use **Import Controller Settings.cmd**
to select that emulator's configuration file. The import tool enables the
controller profile for future launches. Keyboard controls remain available through
**Start Keyboard + Debug Menu.cmd**.

## Using the debug menu

| Tab or control | What it does |
| --- | --- |
| Inventory / Equipment | Give items, change quantities and select equipment. |
| Songs | Learn standard songs. Put away the ocarina and close game menus first. |
| Teleport | Choose an area or saved location. Wait for loading to finish. |
| Save current location | Add your current scene, coordinates and facing to your bookmarks. |
| Change age | Reload as Child/Adult Link and restore your location. |
| Position controls | Read/edit X, Y and Z; use the nudge buttons for small changes. |
| Camera | Toggle free flight, then optionally teleport Link to the camera. |
| Collision | Show collision over gameplay; keep controlling Link or use free flight. |
| Actors | Search actors and teleport to their original map placements. |
| Hotkeys... | Configure quick save and load. |
| Controller... | Customize controller camera controls and save/load combinations. |

Actor destinations are original map positions. Moving, spawned or conditionally
visible actors may be elsewhere or absent. **Allow any era** is an experimental
override; keep it off for normal use.

For free flight, keep the **Camera** tab focused in the debug-menu window.
Use **WASD** to fly, **Q/E** for down/up, hold the **right mouse button** to look,
and hold **Shift** to move faster. **Escape** restores the normal camera.
**Teleport Link to camera** moves Link to that viewpoint; he can fall or enter a
loading zone there. See [free-camera controls](FREE-CAMERA.md) for details.

For collision, open **Collision** and check **Show collision overlay**. The menu
reads your selected NUP automatically; the first area can take a few seconds.
Click the game to play normally, or switch to **Camera** to fly with collision
still visible. Use windowed or borderless mode. Uncheck the toggle or close the
menu to remove it. See [collision controls and coverage](COLLISION.md).

## Save your progress

Controller defaults: **LB/L + Minus** enters free camera, **B** exits and **A**
teleports and exits. Left stick moves, right stick looks, LT/RT fly down/up.
Hold **all four shoulder buttons + D-pad Left** to quick save, or **D-pad Right**
to load. Focus the game and release the chord after pressing it. **Controller...**
lets you change these combinations and flight settings; see [controller guide](CONTROLLER.md).

Press **F5** while the game has focus to create a direct checkpoint. Press **F6**
to load that checkpoint. The same actions use the controller chords above. First
make a checkpoint with F5; F6 does not select an unrelated autosave. No menus or
confirmations are opened. Close game menus before using these actions.

Saving measured about half a second in testing. Loading rebuilds the area and
measured about 11-13 seconds. This is a normal game checkpoint, not a full emulator
save state: the exact animation, enemy positions and temporary physics are not
captured. Keyboard shortcuts can be changed in **Hotkeys...**. In this debug
profile, emulator Stop/Restart are moved to Ctrl+Shift+F5 / Ctrl+Shift+F6.

Your progress is stored in **editor\runtime\nand** inside this package.
Close the game before backing up that folder.

To move progress to another version:

1. Close both game sessions.
2. Back up the destination version's `editor\runtime\nand` folder.
3. Copy the entire `nand` folder from the version whose progress you want into
   the destination's `editor\runtime` folder.
4. Start the destination version normally.

The older private portable package used **inventory-editor\runtime\nand**.
Copy that `nand` folder into the new package's **editor\runtime** folder to migrate.

## If something does not work

| Symptom | What to try |
| --- | --- |
| Files open like an archive / launcher cannot find Python | Use Extract All, then open the extracted folder. |
| Setup asks for files | Select the `.nup` first, then each named key file when prompted. |
| The `.nup` moved or Setup selected the wrong file | Close the game, run Setup.cmd and select it again. |
| Debug menu says Disconnected | Load gameplay until Link can move, then click Connect / Refresh. |
| Items or teleport buttons are unavailable | Connect to gameplay, close game menus and wait for the current action/loading to finish. |
| Keyboard controls do nothing | Click inside the game window to give it focus. |
| Game is already running / port is already in use | Close the other emulator session, then use one package launcher. |
| Only the game window was closed | Close the old debug-menu window and start both again with Start Ocarina + Debug Menu.cmd. |
| Need to reopen just the debug menu | Use Open Debug Menu.cmd while the game launched by this package is still running. |
| Game crashes or Setup reports an error | Run Check Setup.cmd and include its message, your package version and an error screenshot in your report. |

The source and build instructions are in README.md and docs/RELEASES.md for
developers. Portable users can use the launchers above.
