// SPDX-License-Identifier: GPL-3.0-or-later
#include "debug_controller.h"
#include <cassert>
#include <iostream>
using namespace Core::HID::DebugControls;
int main() {
    Bridge b;
    const void* device = &b;
    const auto now = Clock::now();
    const std::string owner = "controller-test-owner";
    const Chords chords{(1<<6)|(1<<11), 2, 1, (15<<6)|(1<<12), (15<<6)|(1<<14)};
    const Axes neutral{};
    auto poll = [&](std::optional<bool> camera={}, std::optional<std::uint64_t> complete={}) {
        return b.Poll(device, owner, true, true, chords, camera, complete, false, now);
    };
    poll(false);
    assert(b.Filter(device, chords[0], neutral, now) == 0); // Held on connect cannot activate.
    assert(poll().action == -1);
    b.Filter(device, 0, neutral, now);
    assert(b.Filter(device, chords[0], neutral, now) == 0); // Minus never reaches the guest.
    auto s = poll();assert(s.action == 0 && s.sequence == 1 && s.blocked);
    b.Filter(device, chords[0], neutral, now);
    assert(poll().sequence == 1); // No repeat while held.
    poll(true, 1);
    b.Filter(device, 0, neutral, now);
    assert(b.Filter(device, 0, {30000,0,20000,0}, now) == 0);
    assert(b.Blocked(device, now));
    s = poll();assert(s.axes[0] == 30000 && s.camera);
    b.Filter(device, chords[2], neutral, now);
    s = poll();assert(s.action == 2 && s.sequence == 2);
    poll(false, 2);
    assert(b.Filter(device, chords[2], neutral, now) == 0); // Teleport A swallowed until release.
    b.Filter(device, 0, neutral, now);
    assert(b.Filter(device, 1, neutral, now) == 1); // A restored for normal play.
    b.Filter(device, 0, neutral, now);
    assert(b.Filter(device, chords[3], neutral, now) == 0);
    s = poll();assert(s.action == 3 && s.sequence == 3);
    assert(b.Blocked(device, now)); // Physical save chord stays blocked during menu automation.
    const Buttons scriptedA = 1;
    assert((b.Filter(device, chords[3], neutral, now) | scriptedA) == scriptedA);
    poll(false, 3);
    b.Filter(device, 0, neutral, now);
    b.Filter(device, chords[4], neutral, now);
    s = poll();assert(s.action == 4 && s.sequence == 4);
    bool foreign = false;
    try { b.Poll(device,"another-controller-owner",false,false,chords,{}, {},false,now); }
    catch (const std::runtime_error&) { foreign = true; }
    assert(foreign);
    assert(b.Filter(device, 1, neutral, now+std::chrono::seconds{3}) == 1);
    assert(!b.Blocked(device, now+std::chrono::seconds{3}));
    poll(false);
    b.Filter(device, 0, neutral, now);
    b.Poll(device,owner,true,true,chords,{}, {},true,now);
    assert(b.Filter(device, chords[0], neutral, now) == 0); // Recording does not execute a chord.
    assert(poll().action == -1);
    b.Poll(device,owner,false,false,chords,{}, {},false,now);
    assert(b.Filter(device, 1, neutral, now) == 1);
    std::cout << "Controller chord, capture, injection, lease and ownership checks passed\n";
}
