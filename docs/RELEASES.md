# Release variants

Both public portable variants are built from the same debug-menu source commit.
The variant selects an independently identified emulator and profile; it does
not fork the debug-menu implementation.

| Variant | Emulator | Custom performance overrides |
| --- | --- | --- |
| Mainline | Official Lichii source at the pinned release, with only the guarded debug-writer bridge added | None |
| Optimized | Accepted custom checkpoint executable, identified by SHA256 and source provenance | Explicit external profile, recorded in package metadata |

Release names are `OOT-Debug-Menu-Mainline-Win64.zip` and
`OOT-Debug-Menu-Optimized-Win64.zip`. Each includes a self-contained Python
runtime, the same debug client, original generated item badges and a separate
save/profile directory. Users supply their own supported NUP and keys. Setup
reconstructs game-side debug files locally rather than distributing them.

The mainline build is an unofficial debug-enabled build of official source,
not a byte-for-byte upstream download. Upstream's own optimizations remain part
of mainline; only our additional performance work is omitted.

## Reproducible packaging

Use64-bit Python3.10 with requirements.txt installed. Provide the compatible
emulator runtime directory, its corresponding source tree and a reviewed profile:

```powershell
python packaging/build_release.py --variant mainline --emulator-dir <runtime> --emulator-source <source> --profile <mainline-profile.json>
python packaging/build_release.py --variant optimized --emulator-dir <runtime> --emulator-source <source> --profile <optimized-profile.json>
```

A profile records `variant`, `revision`, `emulator_sha256`, `environment`,
`configuration` and `files`. Mainline rejects any nonempty custom environment,
renderer/CPU configuration or override list.
Optimized file recipes must verify both source and output hashes and stay inside
the selected mod directory. Profiles do not contain keys, game containers or saves.
Emulator/profile inputs live outside this debug repository so performance work
can evolve independently.

The builder checks the executable's debug capabilities and reviewed hash, and
produces a per-file manifest, source-commit identifier and SHA256 receipt.
Publish corresponding emulator source/patches and build instructions alongside
the binary releases. Report actual gameplay validation separately from package
integrity and import checks.
