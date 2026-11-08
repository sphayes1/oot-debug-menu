# Changes

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
