# Instant save states: follow-up engineering

User decision, 2026-11-08: first implement direct native game checkpoints with
F5/F6 and no menu inputs, then build full emulator save states as a separate
milestone. Full save states are not implemented by the current emulator.

Direct game checkpoints serialize normal progress and reload the area. They do
not capture the exact running frame, temporary actor state, RNG, all physics or
audio/GPU execution. Do not describe them as emulator save states. Measure and
report their save and load latency separately.

The selected optimized source is
`upstream-share/oot-performance-161/source/Lichii-88ffd1f312f9a38fd45575dc8e1c7d66ef9b4f6e`.
Its `core/core.h` exposes Pause/Run/StallApplication and its ARM interfaces expose
thread contexts, but there is no complete machine-state serializer or debug RPC
for capture/restore. A thread context or RAM dump is not a machine snapshot.

## Required state and synchronization

1. Establish an acknowledged safe point across every guest CPU core, scheduler,
   service worker and GPU submission thread. Finish or represent outstanding GPU
   work and invalidate unsafe host/JIT references. Pause alone is not proof that
   every host worker and device is idle.
2. Capture guest RAM and mappings, all CPU register contexts and pending execution,
   kernel objects/handles/wait queues, timers and virtual clocks, IPC/service state,
   memory ownership, GPU registers/resources/queries/synchronization, audio and
   input state. Define what filesystem changes are reversible and keep them in an
   isolated profile. Do not copy arbitrary live C++ objects containing mutexes,
   host pointers, fibers or OS handles and expect them to restore correctly.
3. Restore in a documented dependency order, rebuild host/device resources and
   caches where necessary, resume virtual time consistently and release all
   captured inputs. Handle an interrupted restore without resuming mixed states.
4. Pin emulator build, game revision, memory layout, enabled patches and graphics
   compatibility in a versioned snapshot header. Validate all sections before
   modifying the live machine. Reject mismatches explicitly.

## Incremental acceptance gates

- Read-only capture inventory and memory/latency measurement; no restore yet.
- A deterministic guest test covering registers, memory, multiple threads, timers,
  events, IPC and page mappings, with repeated capture/restore checks.
- GPU/audio test with active rendering and outstanding synchronization. Verify
  visual output and resumed execution, not just an unchanged screenshot.
- Same-process, one-slot in-memory OoT snapshot in an isolated build/profile.
  Capture position, facing, animation, health/ammo, RNG and a dynamic actor. Advance
  gameplay, restore repeatedly, and prove the captured transient state returns.
- Chest/collectible/scene transition and save-file interaction tests; long repeated
  cycles, error recovery, memory leaks, controller held-input release and restart.
- Only then add optional disk persistence, multiple slots, portable builds and
  mainline/optimized compatibility. Keep performance work separate.

The user's PC has 8 GiB VRAM and constrained host commit capacity. Measure actual
captured guest/device data before choosing storage; virtual memory reservation is
not the amount that needs copying. Additional pagefile capacity does not provide
RAM bandwidth or make GPU snapshots instantaneous. Investigate deltas/compression
only after a correct full snapshot exists. Report measured pause/save/load times;
do not promise subsecond restore until demonstrated on this machine.

The debug launcher reserves F5/F6 by reassigning emulator Stop/Restart to
Ctrl+Shift+F5 / Ctrl+Shift+F6 in its private profile. Future save states must retain
that separation. Never silently make
F5 terminate emulation or run the old menu macro as a fallback.
