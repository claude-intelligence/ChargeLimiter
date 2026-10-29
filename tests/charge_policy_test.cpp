#include "ChargePolicy.h"
#include <cassert>
#include <iostream>
using namespace ChargePolicy;
int main() {
    Input i; Memory m;
    i.enabled = true; i.connected = true; i.percent = 90; i.mah = 4307; i.temperature = 25;
    assert(evaluate(i,m).charge == -1); // No premature stop at 80% in mAh mode.
    i.mah = 4308; assert(evaluate(i,m).reason == Reason::Capacity);
    i.mah = 4200; assert(evaluate(i,m).charge == 0); // Hysteresis survives the fall below upper limit.
    i.mah = 4100; assert(evaluate(i,m).charge == 1);
    i.mah = 4200; assert(evaluate(i,m).charge == -1);
    i.temperatureEnabled = true; i.temperature = 36; assert(evaluate(i,m).reason == Reason::Temperature);
    i.temperature = 30; assert(evaluate(i,m).charge == 0);
    i.temperature = 10; assert(evaluate(i,m).charge == 1);
    i.temperature = 0; i.mah = 4400; assert(evaluate(i,m).reason == Reason::Capacity); // Cold cannot undo capacity hold.
    i.manualStop = true; assert(evaluate(i,m).reason == Reason::Manual);
    i.percent = 5; assert(evaluate(i,m).reason == Reason::LowBattery);
    i.percent = 90; i.enabled = false; assert(evaluate(i,m).reason == Reason::Manual);
    i.manualStop = false; assert(evaluate(i,m).reason == Reason::Disabled);
    i.enabled = true; i.connected = false; assert(evaluate(i,m).reason == Reason::NoPower);
    i.connected = true; i.percent = NAN; assert(evaluate(i,m).reason == Reason::InvalidData);
    i.percent = 81; i.mah = NAN; assert(evaluate(i,m).fallback && evaluate(i,m).charge == 0);
    i.percent = 19; assert(evaluate(i,m).charge == 1);
    m = {}; i.percent = 50; i.mah = 4200; i.newPlug = true; i.plugMode = false;
    assert(evaluate(i,m).reason == Reason::Edge);
    i.plugMode = true; assert(evaluate(i,m).reason == Reason::Plug);
    i.stopMah = i.startMah; assert(evaluate(i,m).reason == Reason::InvalidData);
    i = {}; m = {}; i.enabled=true; i.connected=true; i.percent=90; i.mah=4400;
    i.temperatureEnabled=true; i.temperature=40;
    assert(evaluate(i,m).reason==Reason::Capacity);
    i.mah=4000; i.temperature=30; assert(evaluate(i,m).reason==Reason::Temperature);
    i.temperature=10; assert(evaluate(i,m).charge==1);
    // 上限高于电池实际满容量时mAh读数永远到不了, 必须回落到百分比控制
    i = {}; m = {}; i.enabled=true; i.connected=true; i.percent=70; i.mah=4120;
    i.fullMah=4150; // stopMah 4308 > 4150
    assert(evaluate(i,m).fallback && evaluate(i,m).charge==-1);
    i.percent=85; assert(evaluate(i,m).fallback && evaluate(i,m).reason==Reason::Capacity);
    i.fullMah=4400; m={}; assert(!evaluate(i,m).fallback && evaluate(i,m).charge==-1); // 可达则仍按mAh
    i.fullMah=NAN; m={}; assert(!evaluate(i,m).fallback); // 读不到满容量时不改变原有行为

    Retry r; r.reset(0,0);
    assert(r.canWrite(0)); r.wrote(0,true,120); assert(!r.canWrite(119));
    r.observe(false,120); assert(r.canWrite(120)); r.wrote(120,false,120);
    assert(!r.canWrite(124)); assert(r.canWrite(125)); r.wrote(125,true,10);
    r.observe(false,134); assert(!r.failed); r.observe(false,135); assert(r.failed && !r.canWrite(1000));
    r.observe(true,1001); assert(!r.failed && !r.pending); r.observe(false,1002); assert(r.failed);
    r.reset(1,1); assert(r.attempts == 0 && r.canWrite(1003));
    std::cout << "Policy boundaries, hysteresis, temperature, manual mode, fallback and bounded retries passed\n";
}
