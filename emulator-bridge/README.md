# Emulator bridge

The client talks to the existing Lichii/Eden NX2 newline-delimited JSON debug
service on loopback. It uses `status`, memory read/search, guarded
`compare_write32`, screenshots and frame-based controller input. The source also
retains the gated native GameData Int enqueue endpoint; that endpoint alone does
not prove a game's displayed health/magic changed.

`oot-debug-writes.patch` contains memory reads/search, frame-based injected input,
the inventory CAS writer, guarded native queue writer, their validation headers,
connection handling and nonblocking KLightLock dependency. It is a debug-only
delta against the actual pinned Lichii archive listed in `provenance.json`.
The performance sampler and GPU-memory reader are excluded. It is not a
complete debug-server implementation for an unrelated emulator.

Check the baseline source hashes in `provenance.json` (LF line endings), then apply with
`git apply --check emulator-bridge/oot-debug-writes.patch` from the emulator
checkout (use the actual absolute patch path). Apply and build with that
emulator's normal CMake instructions. A freshly rebuilt emulator bridge has not
yet been gameplay-tested as part of this repository extraction. The known
reference executable hash documents prior validation, not a bundled binary.

Enable only these switches for the debug session:

```text
EDEN_NX2_DEBUG_SERVER=127.0.0.1:6545
EDEN_NX2_DEBUG_DIR=<this repository>/editor/runtime/live-debug
EDEN_NX2_LIVE_INVENTORY=1
```

The launcher handles these switches and writes a fresh PID/start-time session
receipt. Do not reuse an old binding across launches. Rendering, clocks, frame
limits, shader behavior and performance environment variables are outside this
bridge's scope.

The Mainline portable release uses official Lichii build 117, pinned in
`mainline117-provenance.json`. Apply `mainline117-guarded-writer.patch` to that
revision. It adds the guarded writer and its lock dependency. It also renames
one local variable in `KeplerCompute::BypassOotNetwork` because MSVC rejects its
shadowing of a class member (C4458); this rename does not change behavior.

For controller camera/save shortcuts, apply the matching additive patch after
that base: `controller-optimized.patch` after `oot-debug-writes.patch`, or
`controller-mainline.patch` after `mainline117-guarded-writer.patch`. Their
before/after LF hashes and patch hashes are pinned in controller-provenance.json.
Both patch applications were reconstructed and verified against their exact
base sources. The optimized public recipe excludes the private performance
sampler, as before. The addon changes only four HID/debug files.

`controller_debug` protocol 1 supplies mapped Player1/Handheld buttons, sticks,
sample counts and one-shot action sequence numbers. It requires the existing
Ocarina live-debug gate and one owned two-second capture lease. The native HID
filter detects chords before they reach the guest, and scripted save/load input
is applied after that filter. Other debug methods remain serialized on a single
worker; the bounded controller heartbeat stays responsive on the IO thread.
See [controller guide](../docs/CONTROLLER.md) and controller/test_controller.cpp.
