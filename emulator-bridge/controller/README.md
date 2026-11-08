# Native controller capture

`debug_controller.h` owns mapped-button chord detection, one-shot events,
controller capture, release gates and the two-second editor lease. `rpc.cpp.inc`
is the guarded `controller_debug` endpoint used by the additive patches in the
parent folder. All normal debug operations remain serialized; this bounded
heartbeat runs independently of frame-timed scripted input.

`test_controller.cpp` exercises chord edges, held-button suppression, guest input
capture, scripted-input ordering, recording, lease expiry and owner isolation.
It is standalone and does not launch a game. From a Windows x64 MSVC developer
shell at the repository root:

```powershell
New-Item -ItemType Directory -Force build | Out-Null
cl /nologo /std:c++20 /EHsc emulator-bridge/controller/test_controller.cpp /Fe:build/controller-test.exe /Fo:build/controller-test.obj
./build/controller-test.exe
```

For end users, use the portable release and its **Controller...** menu; rebuilding
the emulator is unnecessary. See [controller controls](../../docs/CONTROLLER.md).
