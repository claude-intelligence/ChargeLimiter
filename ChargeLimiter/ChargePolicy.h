#pragma once
#include <cmath>

namespace ChargePolicy {
enum class Reason { Disabled, NoPower, InvalidData, LowBattery, Capacity, Temperature, Manual, Resume, Plug, Edge, Waiting };
struct Input {
    bool enabled = false, connected = false, newPlug = false, manualStop = false;
    bool useMah = true, temperatureEnabled = false, plugMode = true;
    double percent = NAN, mah = NAN, temperature = NAN;
    double fullMah = NAN; // NominalChargeCapacity: 电池实际满容量

    double stopPercent = 80, startPercent = 20, stopMah = 4308, startMah = 4100;
    double stopTemperature = 35, startTemperature = 10;
};
struct Memory { bool capacityHold = false, temperatureHold = false; };
struct Decision { int charge = -1; Reason reason = Reason::Waiting; bool fallback = false; };
inline bool valid(double n) { return std::isfinite(n); }
inline Decision evaluate(const Input& i, Memory& m) {
    if (!i.enabled) { m = {}; return {-1, i.manualStop ? Reason::Manual : Reason::Disabled, false}; }
    if (!i.connected) { m = {}; return {-1, Reason::NoPower, false}; }
    if (!valid(i.percent) || i.percent < 0 || i.percent > 100) return {-1, Reason::InvalidData, false};
    if (i.percent <= 5) { m = {}; return {1, Reason::LowBattery, false}; }
    // 上限高于电池实际满容量时读数永远到不了, mAh控制会静默失效, 必须回落到百分比
    bool reachable = !(valid(i.fullMah) && i.fullMah > 0 && i.stopMah > i.fullMah);
    bool mah = i.useMah && valid(i.mah) && i.mah > 0 && reachable;
    double capacity = mah ? i.mah : i.percent;
    double upper = mah ? i.stopMah : i.stopPercent;
    double lower = mah ? i.startMah : i.startPercent;
    bool fallback = i.useMah && !mah;
    if (!(valid(upper) && valid(lower) && lower >= 0 && upper > lower)) return {-1, Reason::InvalidData, fallback};
    if (capacity >= upper) m.capacityHold = true;
    if (m.capacityHold && capacity <= lower) m.capacityHold = false;
    bool wasHot = m.temperatureHold;
    if (!i.temperatureEnabled) m.temperatureHold = false;
    else if (valid(i.temperature)) {
        if (i.temperature >= i.stopTemperature) m.temperatureHold = true;
        else if (i.temperature <= i.startTemperature) m.temperatureHold = false;
    }
    if (i.manualStop) return {0, Reason::Manual, fallback};
    if (m.capacityHold) return {0, Reason::Capacity, fallback};
    if (m.temperatureHold) return {0, Reason::Temperature, fallback};
    if (i.temperatureEnabled && !valid(i.temperature)) return {-1, Reason::InvalidData, fallback};
    if (capacity <= lower || (wasHot && !m.temperatureHold)) return {1, Reason::Resume, fallback};
    if (i.newPlug) return {i.plugMode ? 1 : 0, i.plugMode ? Reason::Plug : Reason::Edge, fallback};
    return {-1, Reason::Waiting, fallback};
}

// One target change / explicit user retry starts one bounded command episode.
struct Retry {
    int target = -1, inflow = -1, attempts = 0;
    bool pending = false, failed = false;
    double due = 0;
    void reset(int charge, int input) { *this = {}; target = charge; inflow = input; }
    bool canWrite(double now) const { return target >= 0 && !failed && attempts < 3 && (!pending || now >= due); }
    void wrote(double now, bool accepted, double grace) {
        ++attempts; pending = true; failed = false;
        due = now + (accepted ? grace : 5);
    }
    void observe(bool matches, double now) {
        if (matches) { pending = false; failed = false; }
        else if (pending && now >= due && attempts >= 3) { pending = false; failed = true; }
        else if (!pending && attempts >= 3) failed = true;
    }
};
}
