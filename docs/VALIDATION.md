# Validation

## Release 0.2.1

213 local editor tests pass.

- Copied-save direct saves measured 0.42-0.53 seconds; native area reloads measured
  10.8-13.6 seconds. Input/input_sequence RPCs are prohibited inside checkpoint
  calls by the live test harness. HUD, position, rupees and subsequent movement
  were checked, rather than treating restored GameData alone as a successful load.
- Repeated cycles, a Hyrule Field-to-Market load, opposite-age restoration,
  camera enable/disable and the unchanged normal menu-load path passed.
- A copied native slot was deliberately overwritten; load restored the immutable
  archived progress and the original rupee count. Current slot bytes are backed
  up and verified before a guarded atomic replacement.
- User physically verified customized Up camera entry and B exit, with the debug
  window visible and minimized, and in their normal profile.
- Six debug overrides reconstruct from revision-checked patch recipes. Required
  graph entry/state flags are checked by the private authoring harness.
- Emulator binaries and performance configuration are unchanged from 0.2.0.
  Live checkpoint tests used the optimized bridge build; the Mainline bundle uses
  the same game-side module and Python transport, with offline package validation.
- Full emulator state capture/restore is not implemented. Captured progress does
  not include every transient actor, animation, RNG, physics or GPU/audio state.

## Previous release 0.2.0

Release 0.2.0 was checked on Windows x64 with Python 3.10 on November 8, 2026.

- 204 editor tests pass with the optional private recognition fixtures present.
  Those fixtures remain ignored; the recognition case skips when absent.
- The offline self-check initializes the client, native dependencies, schemas,
  generated badges and read-only actor catalogue without launching a game.
- Focused native C++ tests cover controller chords, held-button suppression,
  input capture, scripted-input ordering, recording, lease expiry and ownership.
- Both mainline and optimized controller/debug bridge builds compiled. Their
  additive patches were applied to exact base sources and all output hashes
  verified. The public optimized recipe excludes private performance tools.
- Five debug overrides reconstruct locally from source-checked recipes. The
  native free camera adds the EventCamera pack. Original game files stay intact.
- Live copied-save checks covered camera movement, teleport with normal-view
  restoration, normal save and newest-save load with confirmations automated.
  During long frame-timed input and those actions, 1,413 controller heartbeats
  completed with zero errors and a maximum response time of 94 ms.
- Collision was observed aligned over Castle Town with Link movement and native
  free-camera movement. Nearby Hyrule Field tile decoding was checked offline.
- Controller settings rendered correctly; polling reported game focus and
  advancing mapped samples. Physical controller presses have not been observed.
  Short automated keyboard chords produced no held SDL samples and are not
  counted as successful physical-controller validation.
- Boundary tests/audits check storage rebasing, renderer/input preservation,
  allowed debug source paths, patch hashes, catalogue integrity and absence of
  keys, runtime files and extracted game assets from tracked source.

Release ZIP validation uses fresh extraction and checks CRC, every file hash,
embedded Python/native imports, generated badges and setup against the local
NUP. Receipts record the exact source commit/emulator hash. Gameplay is reported
separately from package integrity and imports.

Saves use the game's normal path. Teleport still allows gravity/loading zones.
Collision is authored geometry, with runtime moving/destroyed/conditional state
untracked. Read [controller](CONTROLLER.md), [camera](FREE-CAMERA.md) and
[collision](COLLISION.md) guides. These checks are not a performance benchmark.
