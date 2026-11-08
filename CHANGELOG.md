# Changes

## 0.2.1 - 2026-11-08

- Replace save-menu automation with direct native game checkpoints on F5/F6.
  Controller save/load chords use the same native transport, without confirmation
  inputs. Loading rebuilds the area; full emulator save states remain future work.
- Archive the exact quick-save progress independently of the game's rotating slots;
  verify and restore the archive if its native slot changes before loading.
- Reserve F5/F6 in debug profiles; emulator Stop/Restart move to Ctrl+Shift+F5/F6.
- Fix controller binding edits: Save binding and close persists and activates the
  binding immediately. Show the saved camera shortcut and unsaved changes.
- Keep performance executables/profiles unchanged and preserve normal menu loads.

## 0.2.0 — 2026-11-08

- Native free-flight camera, independent of Link, with teleport-to-camera.
  Successful teleport now restores normal view.
- Customizable controller camera shortcuts: LB/L + Minus enters, B exits,
  A teleports and exits. Left/right sticks fly/look, LT/RT move down/up.
- Controller quick save/load: all four shoulders + D-pad Left/Right, with
  normal-save confirmations handled automatically. Keyboard shortcuts remain.
- Collision overlay over gameplay, using the user's NUP automatically, with
  terrain/wall/zone filters, translucent faces, X-ray and nearby-tile loading.
- Leased controller input capture prevents shortcut buttons/sticks reaching
  Link during camera flight and save/load automation.
- Updated mainline/optimized bridge builds, portable dependencies, instructions
  and corresponding emulator source archives.

204 offline editor tests pass. Native chord/capture/lease tests pass. Camera
teleport and normal save/load were checked live on a copied save. Physical pad
button mappings still need user verification. Collision shows authored geometry;
moving/removed/conditional actors may differ. Save automation recognizes English.

## 0.1.0

Initial public inventory, equipment, songs, teleports, coordinates, age switching,
actor catalogue, normal save/load keyboard shortcuts and two portable variants.
