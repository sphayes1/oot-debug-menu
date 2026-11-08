// Gated mapped-controller endpoint. One owned lease; physical input is filtered
// before existing scripted injection, so native Save/Load automation still works.
json ControllerDebug(ToolState& state, const json& params) {
    if (!InventoryWritesEnabled() || state.program_id != OOT_PROGRAM_ID ||
        state.stopping.load(std::memory_order_relaxed))
        throw std::runtime_error{"Ocarina live debug controls are not enabled"};
    auto& hid = state.system.HIDCore();
    auto* controller = hid.GetEmulatedController(HID::NpadIdType::Player1);
    const char* name = "Player1";
    if (!controller->IsConnected()) {
        controller = hid.GetEmulatedController(HID::NpadIdType::Handheld);
        name = "Handheld";
    }
    if (!controller->IsConnected())
        throw std::runtime_error{"neither player 1 nor handheld controller is connected"};
    HID::DebugControls::Chords chords{};
    const auto& list = params.at("bindings");
    if (!list.is_array() || list.size() != chords.size())
        throw std::runtime_error{"five controller bindings are required"};
    for (size_t i = 0; i < chords.size(); ++i)
        chords[i] = list[i].get<u64>();
    const auto snapshot = HID::DebugControls::bridge.Poll(
        controller, params.at("owner").get<std::string>(), params.value("enabled", true),
        params.value("armed", false), chords,
        params.contains("capture") ? std::optional{params.at("capture").get<bool>()} : std::nullopt,
        params.contains("complete") ? std::optional{params.at("complete").get<u64>()} : std::nullopt,
        params.value("recording", false));
    return {{"protocol", 1}, {"controller", name}, {"buttons", snapshot.buttons},
            {"axes", snapshot.axes}, {"sequence", snapshot.sequence}, {"samples", snapshot.samples},
            {"action", snapshot.action}, {"camera", snapshot.camera},
            {"blocked", snapshot.blocked}, {"lease_ms", 2000}};
}

