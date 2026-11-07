# Extraction validation

Validated locally on Windows x64 with Python 3.10.6 on November 7, 2026.

- 166 tests collected. All 166 pass with the optional private screenshots supplied
  locally. Without those screenshots, 165 pass and one recognition case skips. The
  private fixtures are ignored and are not part of the repository.
- `run.py --self-check` initializes the ImGui client, schemas, generated badges
  and read-only actor catalogue without launching or modifying a game.
- The three NUP-based binary patch recipes plus authored IPS patch reconstruct
  all four accepted debug overrides exactly: 1,384,766 total output bytes. Every
  source and output hash matches the accepted debug manifest.
- The complete debug bridge delta passes `git apply --check` against the pinned
  upstream archive and applies successfully. Its ten resulting source files are
  checked against the recorded LF-normalized output hashes. A fresh full emulator rebuild and
  gameplay test of that extracted delta remain to be performed.
- Boundary tests check storage rebasing, renderer/input-setting preservation,
  debug environment ownership and the absence of performance mod files from the
  debug manifest. The source audit rejects tracked credentials, runtime files,
  private fixtures, emulator binaries and extracted game assets.

Earlier live gameplay checks established the original debug implementation's
inventory, ocarina/song, teleport, age, position, collectibles and hotkey behavior.
The standalone extraction has not yet replaced that working session. GitHub CI
results should be reported separately once this repository has been pushed.

Public release packaging additionally verifies the isolated setup dependencies,
including oead's privately named runtime DLL. External optimized-profile tests
cover source/output hashes, output-path bounds and rejection of custom settings
in mainline. Actual release ZIP receipts record their own validation results.
