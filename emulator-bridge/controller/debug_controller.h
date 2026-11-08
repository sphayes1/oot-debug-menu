// SPDX-License-Identifier: GPL-3.0-or-later
// Debug-only mapped controller capture. No renderer/timing modifications.
#pragma once
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>

namespace Core::HID::DebugControls {
using Clock = std::chrono::steady_clock;
using Buttons = std::uint64_t;
using Axes = std::array<std::int32_t, 4>;
using Chords = std::array<Buttons, 5>; // enter, exit, teleport, save, load
struct Snapshot {
    Buttons buttons{};
    Axes axes{};
    std::uint64_t sequence{};
    std::uint64_t samples{};
    int action{-1};
    bool camera{}, blocked{};
};

class Bridge {
public:
    Snapshot Poll(const void* device, const std::string& owner, bool enabled, bool armed,
                  const Chords& chords, std::optional<bool> capture,
                  std::optional<std::uint64_t> complete, bool recording,
                  Clock::time_point now = Clock::now()) {
        std::scoped_lock lock{mutex};
        if (owner.size() < 16 || owner.size() > 64)
            throw std::runtime_error{"controller owner token is invalid"};
        if (!owner_id.empty() && owner_id != owner && now < deadline)
            throw std::runtime_error{"controller debug controls belong to another editor"};
        if (!enabled) {
            target.store(nullptr, std::memory_order_release);
            owner_id.clear();
            state = {};
            return state;
        }
        for (const auto mask : chords)
            if (!mask || (mask & ~Buttons{0xffff}))
                throw std::runtime_error{"invalid controller button chord"};
        for (size_t i = 0; i < chords.size(); ++i)
            for (size_t j = i+1; j < chords.size(); ++j)
                if (chords[i] == chords[j])
                    throw std::runtime_error{"controller chords must be different"};
        if (owner_id != owner || target.load(std::memory_order_relaxed) != device || now >= deadline) {
            state = {};
            latch.fill(false);
            pending = false;
            release_gate = true; // Never trigger a chord held during connection.
        }
        owner_id = owner;
        deadline = now+std::chrono::seconds{2};
        bindings = chords;
        is_armed = armed;
        if (is_recording && !recording)
            release_gate = true;
        is_recording = recording;
        if (complete && *complete == state.sequence && pending) {
            pending = false;
            state.action = -1;
            state.camera = capture.value_or(false);
            release_gate = !state.camera;
        } else if (capture && !pending && state.camera != *capture) {
            state.camera = *capture;
            release_gate = !state.camera;
        }
        state.blocked = state.camera || pending || release_gate || is_recording;
        target.store(device, std::memory_order_release);
        return state;
    }

    Buttons Filter(const void* device, Buttons buttons, const Axes& axes,
                   Clock::time_point now = Clock::now()) {
        if (target.load(std::memory_order_acquire) != device)
            return buttons;
        std::scoped_lock lock{mutex};
        if (now >= deadline) {
            target.store(nullptr, std::memory_order_release);
            return buttons; // Fail open when the editor closes or stops polling.
        }
        state.buttons = buttons & 0xffff;
        state.axes = axes;
        ++state.samples;
        bool neutral = state.buttons == 0;
        for (const auto axis : axes)
            neutral = neutral && std::abs(static_cast<double>(axis)) < 6000;
        if (release_gate && neutral)
            release_gate = false;
        for (size_t i = 0; i < bindings.size(); ++i) {
            const bool held = (state.buttons & bindings[i]) == bindings[i];
            const bool rising = held && !latch[i];
            latch[i] = held;
            const bool allowed = state.camera ? (i != 0) : (i == 0 || i == 3 || i == 4);
            if (rising && allowed && is_armed && !pending && !release_gate && !is_recording) {
                state.action = static_cast<int>(i);
                ++state.sequence;
                pending = true;
                break;
            }
        }
        state.blocked = state.camera || pending || release_gate || is_recording;
        return state.blocked ? 0 : buttons;
    }

    bool Blocked(const void* device, Clock::time_point now = Clock::now()) {
        if (target.load(std::memory_order_acquire) != device)
            return false;
        std::scoped_lock lock{mutex};
        return now < deadline && state.blocked;
    }

private:
    std::atomic<const void*> target{};
    std::mutex mutex;
    std::string owner_id;
    Clock::time_point deadline{};
    Snapshot state{};
    Chords bindings{};
    std::array<bool, 5> latch{};
    bool is_armed{}, is_recording{}, pending{}, release_gate{};
};
inline Bridge bridge;
} // namespace Core::HID::DebugControls
