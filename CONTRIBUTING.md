# Contributing

Keep debug functionality independent of emulator performance work. Submit
rendering, shader, timing, FPS, PGO and graphics-profile changes to the emulator
project rather than this client repository.

Run the offline self-check and unit suite described in README.md. Add focused
tests for new transport guards, session handling or data migrations. Live tests
must identify the exact game/bridge revision and report observed gameplay effects
separately from successful RPC publication.

Do not commit keys, game containers, saves, extracted artwork, replacement game
assets, emulator binaries or local session/configuration files. Game-side changes
should remain source-checked recipes generated from the user's own dump.

New field and asset discoveries should update docs/FILE-GUIDE.md, including source
provenance and whether the behavior has actually been demonstrated in gameplay.
