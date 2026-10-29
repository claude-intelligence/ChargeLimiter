#!/usr/bin/env python3
"""Run the actual Objective-C++ controller/API with deterministic fake battery hardware."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[1]
src = (root / 'ChargeLimiter/daemon.mm').read_text()
def section(start, end):
    return src[src.index(start):src.index(end, src.index(start))]
pre = r'''
#import <Foundation/Foundation.h>
#include <cassert>
#include "ChargePolicy.h"
#define NSFileLog(...) ((void)0)
static dispatch_block_t scheduled;
static void mockDispatchAfter(dispatch_time_t time,dispatch_queue_t queue,dispatch_block_t block) { scheduled=block; }
#define dispatch_after mockDispatchAfter
@interface Service: NSObject
+ (Service*)inst;
- (void)initLocalPush;
@end
@implementation Service
+ (Service*)inst { static Service* instance = [Service new]; return instance; }
- (void)initLocalPush {}
@end
@interface UPSDataSlim: NSObject
@property NSDictionary* props;
@end
@implementation UPSDataSlim @end
static UPSDataSlim* gUPSPS = nil;
static NSDictionary* bat_info;
static NSMutableDictionary* hardware;
static NSMutableDictionary* conf;
static BOOL g_enable=NO, g_enable_floatwnd=NO, g_use_smart=NO;
static int g_serv_boot=0, writes=0, actions=0, writeError=0, readError=0;
static bool stubborn=false, stubbornInflow=false;
static int inflowError=0;
static int resets=0;
static id getlocalKV(NSString* key) { return conf[key]; }
static void setlocalKV(NSString* key,id val) { conf[key]=val; }
static NSDictionary* getAllKV() { return conf; }
static io_service_t getIOPMPSServ() { return 1; }
static int getBatInfoWithServ(io_service_t serv,NSDictionary* __strong* result) {
    if (readError) return readError;
    *result=hardware.copy; return 0;
}
static int getBatInfo(NSDictionary* __strong* result) { return getBatInfoWithServ(1,result); }
static int setInflowStatus(BOOL value) {
    if (inflowError) return inflowError;
    if (!writeError && !stubborn && !stubbornInflow) hardware[@"ExternalConnected"]=@(value);
    return writeError;
}
static int setBatteryStatus(BOOL value) {
    ++writes;
    if (!writeError && !stubborn) {
        if ([getlocalKV(@"adv_predictive_inhibit_charge") boolValue]) {
            // 真实实现强制写IsCharging=YES以保留系统充电图标, IsCharging和电流都
            // 不再反映真实状态, 只有PredictiveChargingInhibit是真的开关
            hardware[@"IsCharging"]=@YES;
            hardware[@"PredictiveChargingInhibit"]=@(!value);
            hardware[@"InstantAmperage"]=value ? @295 : @0;
        } else {
            hardware[@"IsCharging"]=@(value);
            hardware[@"InstantAmperage"]=value ? @295 : @0;
        }
    }
    return writeError;
}
static void resetBatteryStatus() {
    ++resets;
    hardware[@"IsCharging"]=@YES; hardware[@"InstantAmperage"]=@295;
    hardware[@"ExternalConnected"]=@YES; hardware[@"PredictiveChargingInhibit"]=@NO;
}
static int setChargeStatus(BOOL value) { return setBatteryStatus(value); }
static void performAction(NSString* action) { ++actions; }
static void performAcccharge(BOOL value) {}
static void updateStatistics() {}
static void onBatteryEventEnd() {}
static NSDictionary* getThermalData() { return nil; }
static void showFloatwnd(BOOL value) {}
static NSString* getSysVer() { return @"16.2"; }
static NSString* getDevMdoel() { return @"test"; }
static NSString* getAppVer() { return @"test"; }
static int get_sys_boottime() { return 0; }
static NSString* getThermalSimulationMode() { return @"off"; }
static NSString* getPPMSimulationMode() { return @"off"; }
static void setThermalSimulationMode(id value) {}
static void setPPMSimulationMode(id value) {}
static BOOL isSmartChargeEnable() { return NO; }
static void setSmartChargeEnable(BOOL value) {}
static NSArray* getDBData(const char* table,int id,int n) { return @[]; }
'''
code = (pre + section('// 自己下发的停充命令正在生效时为YES', 'static int setChargeStatus(')
        + section('static float getTempAsC(', 'static ChargePolicy::Memory')
        + section('static ChargePolicy::Memory', 'static void initConf(BOOL reset)')
        + section('static void initConf(BOOL reset)', 'static void showFloatwnd(BOOL flag)')
        + section('static NSDictionary* handleReqLocked(', '\nNSDictionary* handleReq(NSDictionary* nsreq) {'))
post = r'''
static void reset() {
    conf=[NSMutableDictionary new];
    hardware=[@{@"CurrentCapacity":@90,@"AppleRawCurrentCapacity":@4200,@"IsCharging":@YES,
               @"InstantAmperage":@295,@"ExternalConnected":@YES,@"ExternalChargeCapable":@YES,
               @"Temperature":@2500,@"PostChargeWaitSeconds":@120,@"AdapterDetails":@{@"Description":@"usb host"}} mutableCopy];
    bat_info=hardware.copy; writeError=0; readError=0; stubborn=false; stubbornInflow=false; writes=0; actions=0;
    g_manual_stop=NO; g_policy_memory={}; g_verify_scheduled=NO; scheduled=nil; g_inhibit_active=NO;
    inflowError=0; cancelControl(); initConf(NO); g_enable=YES; conf[@"enable"]=@YES;
    conf[@"adv_predictive_inhibit_charge"]=@NO; resets=0;
}
static NSDictionary* set(NSString* key,id value) { return handleReqLocked(@{@"api":@"set_conf",@"key":key,@"val":value}); }
static void expire() { g_control_retry.due=NSProcessInfo.processInfo.systemUptime-1; onBatteryEvent(1); }
int main() { @autoreleasepool {
    reset(); hardware[@"AppleRawCurrentCapacity"]=@4308; onBatteryEvent(1);
    assert(writes==1 && [g_control_state isEqual:@"confirmed"] && actions==1);
    onBatteryEvent(1); assert(writes==1 && actions==1);
    hardware[@"AppleRawCurrentCapacity"]=@4200; onBatteryEvent(1); assert(writes==1);
    hardware[@"AppleRawCurrentCapacity"]=@4100; onBatteryEvent(1); assert(writes==2 && [hardware[@"IsCharging"] boolValue]);
    reset(); assert([set(@"charge_above_mah",@4190)[@"status"] intValue]==0); assert(writes==1); // immediate
    assert([set(@"charge_below_mah",@4190)[@"status"] intValue]==-1);
    assert([set(@"charge_above_mah",@4100)[@"status"] intValue]==-1);
    assert([set(@"charge_below_mah",@0)[@"status"] intValue]==-1);
    assert([set(@"charge_below_mah",@4100.5)[@"status"] intValue]==-1);
    reset(); g_enable=NO; hardware[@"AppleRawCurrentCapacity"]=@4500;
    set(@"enable",@YES); assert(writes==1); // enabling evaluates immediately
    reset(); stubborn=true; hardware[@"AppleRawCurrentCapacity"]=@4500; onBatteryEvent(1);
    assert(writes==1 && actions==0 && [g_control_state isEqual:@"pending"]);
    onBatteryEvent(1); assert(writes==1); // notifications cannot bypass the 120-second grace
    expire(); assert(writes==2); expire(); assert(writes==3); expire();
    assert([g_control_state isEqual:@"failed"] && g_control_error==-4);
    for(int j=0;j<20;++j) onBatteryEvent(1); assert(writes==3);
    stubborn=false; hardware[@"AppleRawCurrentCapacity"]=@4200; handleReqLocked(@{@"api":@"retry_control"});
    assert(writes==4 && [g_control_state isEqual:@"confirmed"]);
    // A plugged-in adapter is still connected when ChargeCapable is false at full/paused.
    reset();stubborn=true;hardware[@"ExternalChargeCapable"]=@NO;
    hardware[@"AppleRawCurrentCapacity"]=@4100;hardware[@"IsCharging"]=@NO;
    hardware[@"InstantAmperage"]=@2;onBatteryEvent(1);
    assert([g_control_state isEqual:@"pending"] && [g_control_reason isEqual:@"resume"]);
    // Failed input restoration must keep ownership so retries can still see the adapter.
    reset();conf[@"adv_disable_inflow"]=@YES;hardware[@"AppleRawCurrentCapacity"]=@4308;
    onBatteryEvent(1);assert(g_inhibit_active);
    hardware[@"AppleRawCurrentCapacity"]=@4100;hardware[@"ExternalChargeCapable"]=@NO;inflowError=-2;
    onBatteryEvent(1);assert(g_inhibit_active && [g_control_state isEqual:@"pending"]);
    inflowError=0;expire();assert(!g_inhibit_active && [g_control_state isEqual:@"confirmed"]);
    reset(); writeError=-2; hardware[@"AppleRawCurrentCapacity"]=@4500; onBatteryEvent(1);
    expire(); expire(); expire(); assert(writes==3 && g_control_error==-2 && [g_control_state isEqual:@"failed"]);
    reset(); stubborn=true; hardware[@"AppleRawCurrentCapacity"]=@4500; onBatteryEvent(1);
    set(@"enable",@NO); if(scheduled) scheduled(); expire();
    assert(writes==1 && [g_control_reason isEqual:@"disabled"] && resets>=1 && !g_inhibit_active);
    // 自己禁充会让ExternalChargeCapable变false, 不能据此判为断电而释放控制
    reset(); hardware[@"AppleRawCurrentCapacity"]=@4500; onBatteryEvent(1);
    assert([g_control_reason isEqual:@"capacity"] && g_inhibit_active && resets==0);
    hardware[@"ExternalChargeCapable"]=@NO; onBatteryEvent(1);
    assert([g_control_reason isEqual:@"capacity"] && [g_control_state isEqual:@"confirmed"] && resets==0);
    // 真的拔线才判断电, 且释放控制时必须把电池还原成可充
    hardware[@"ExternalConnected"]=@NO; hardware[@"AdapterDetails"]=@{@"Description":@"batt"};
    onBatteryEvent(1);
    assert([g_control_reason isEqual:@"no_power"] && !g_inhibit_active && resets==1);
    reset(); hardware[@"AppleRawCurrentCapacity"]=@4500; conf[@"adv_disable_inflow"]=@YES; onBatteryEvent(1);
    assert(![hardware[@"ExternalConnected"] boolValue]);
    hardware[@"AppleRawCurrentCapacity"]=@4100;
    hardware[@"AdapterDetails"]=@{@"Description":@"usb host"};onBatteryEvent(1);
    assert([hardware[@"IsCharging"] boolValue] && [hardware[@"ExternalConnected"] boolValue]);
    reset();handleReqLocked(@{@"api":@"set_charge_status",@"flag":@NO});onBatteryEvent(1);
    assert([g_control_reason isEqual:@"manual"] && ![hardware[@"IsCharging"] boolValue]);
    reset();hardware[@"Temperature"]=@3600;set(@"enable_temp",@YES);
    assert([g_control_reason isEqual:@"temperature"] && ![hardware[@"IsCharging"] boolValue]);
    reset();stubborn=true;hardware[@"AppleRawCurrentCapacity"]=@4500;onBatteryEvent(1);
    readError=-1;expire();assert([g_control_state isEqual:@"failed"] && g_control_error==-5 && writes==1);
    onBatteryEvent(1);assert([g_control_state isEqual:@"failed"]);
    reset(); [hardware removeObjectForKey:@"AppleRawCurrentCapacity"];onBatteryEvent(1);
    assert(g_control_fallback && ![hardware[@"IsCharging"] boolValue]);
    reset();conf[@"charge_above_mah"]=@1000;[conf removeObjectForKey:@"charge_below_mah"];initConf(NO);
    assert([conf[@"charge_below_mah"] intValue]==999);
    reset();set(@"charge_below",@80);assert([conf[@"charge_above"] intValue]==85);
    assert([set(@"charge_above",@80)[@"status"] intValue]==-1);
    reset();readError=-1;
    assert([handleReqLocked(@{@"api":@"set_charge_status",@"flag":@NO})[@"status"] intValue]==-1 && writes==0);
    reset();stubbornInflow=true;hardware[@"ExternalConnected"]=@NO;hardware[@"IsCharging"]=@NO;
    hardware[@"InstantAmperage"]=@0;hardware[@"AppleRawCurrentCapacity"]=@4100;onBatteryEvent(1);
    assert([g_control_state isEqual:@"confirmed"] && writes==1);
    // Input restoration may cause a rising adapter flag on each read-back.
    // Such edges must not restart an in-flight confirmation episode.
    reset();stubborn=true;hardware[@"AppleRawCurrentCapacity"]=@4100;
    hardware[@"IsCharging"]=@NO;hardware[@"InstantAmperage"]=@2;
    onBatteryEvent(1);assert(writes==1 && [g_control_state isEqual:@"pending"]);
    for(int j=0;j<3;++j) {
        NSMutableDictionary* previous=[bat_info mutableCopy];
        previous[@"ExternalChargeCapable"]=@NO;bat_info=previous;
        expire();
    }
    assert(writes==3 && [g_control_state isEqual:@"failed"]);
    // A UI refresh must reconcile an overdue pending state as well.
    reset();stubborn=true;hardware[@"AppleRawCurrentCapacity"]=@4100;
    hardware[@"IsCharging"]=@NO;hardware[@"InstantAmperage"]=@2;
    onBatteryEvent(1);
    for(int j=0;j<3;++j) {
        g_control_retry.due=NSProcessInfo.processInfo.systemUptime-1;
        handleReqLocked(@{@"api":@"get_bat_info"});
    }
    assert(writes==3 && [g_control_state isEqual:@"failed"]);
    // 恢复温度必须可达: 过热停充后降回常温就应恢复, 而不是锁死到10度
    reset();conf[@"enable_temp"]=@YES;hardware[@"Temperature"]=@3600;onBatteryEvent(1);
    assert([g_control_reason isEqual:@"temperature"] && ![hardware[@"IsCharging"] boolValue]);
    hardware[@"Temperature"]=@2500;onBatteryEvent(1);
    assert([g_control_reason isEqual:@"resume"] && [hardware[@"IsCharging"] boolValue]);
    // 历史配置里降不到的恢复温度要被迁移, 新设置也要被拦住
    reset();conf[@"charge_temp_below"]=@10;initConf(NO);
    assert((int)getTempAsC(@"charge_temp_below")==30);
    assert([set(@"charge_temp_below",@10)[@"status"] intValue]==-1);
    assert([set(@"charge_temp_below",@28)[@"status"] intValue]==0);
    assert([set(@"charge_temp_above",@70)[@"status"] intValue]==-1);
    // 电池自然充满后电流归零, 不该当成启充失败去重试
    reset();stubborn=true;hardware[@"NominalChargeCapacity"]=@4400;
    hardware[@"AppleRawCurrentCapacity"]=@4100;hardware[@"CurrentCapacity"]=@100;
    hardware[@"IsCharging"]=@NO;hardware[@"InstantAmperage"]=@0;onBatteryEvent(1);
    assert([g_control_state isEqual:@"confirmed"] && writes==0);
    reset();stubborn=true;hardware[@"NominalChargeCapacity"]=@4400;
    hardware[@"AppleRawCurrentCapacity"]=@4100;hardware[@"CurrentCapacity"]=@99;
    hardware[@"IsCharging"]=@NO;hardware[@"InstantAmperage"]=@0;onBatteryEvent(1);
    assert([g_control_state isEqual:@"pending"] && writes==1);
    // 预测禁充模式下IsCharging被强制为YES, 只能靠PredictiveChargingInhibit确认停充
    reset();conf[@"adv_predictive_inhibit_charge"]=@YES;
    hardware[@"AppleRawCurrentCapacity"]=@4308;onBatteryEvent(1);
    assert(writes==1 && [g_control_state isEqual:@"confirmed"] &&
           [hardware[@"IsCharging"] boolValue] && [hardware[@"PredictiveChargingInhibit"] boolValue]);
    for(int j=0;j<5;++j) expire();
    assert(writes==1 && [g_control_state isEqual:@"confirmed"]);
    // Nominal is only an estimate: keep the user's live mAh thresholds above it.
    reset();hardware[@"NominalChargeCapacity"]=@4150;
    hardware[@"AppleRawCurrentCapacity"]=@4120;hardware[@"CurrentCapacity"]=@70;onBatteryEvent(1);
    assert(!g_control_fallback && [g_control_reason isEqual:@"waiting"]);
    hardware[@"CurrentCapacity"]=@85;onBatteryEvent(1);
    assert(!g_control_fallback && [g_control_reason isEqual:@"waiting"] && writes==0);
    hardware[@"AppleRawCurrentCapacity"]=@4308;onBatteryEvent(1);
    assert([g_control_reason isEqual:@"capacity"] && ![hardware[@"IsCharging"] boolValue]);
    // A full percentage or raw reading above Nominal must not hide an active inhibit.
    for (int percent=99;percent<=100;++percent) {
        reset();conf[@"adv_predictive_inhibit_charge"]=@YES;stubborn=true;
        hardware[@"NominalChargeCapacity"]=@4086;hardware[@"AppleRawCurrentCapacity"]=@4100;
        hardware[@"CurrentCapacity"]=@(percent);hardware[@"IsCharging"]=@YES;
        hardware[@"PredictiveChargingInhibit"]=@YES;hardware[@"InstantAmperage"]=@2;
        onBatteryEvent(1);assert(writes==1 && [g_control_state isEqual:@"pending"]);
        expire();expire();expire();assert([g_control_state isEqual:@"failed"] && writes==3);
    }
    reset();stubborn=true;hardware[@"NominalChargeCapacity"]=@4086;
    hardware[@"AppleRawCurrentCapacity"]=@4100;hardware[@"IsCharging"]=@NO;
    hardware[@"InstantAmperage"]=@2;onBatteryEvent(1);
    assert(writes==1 && [g_control_state isEqual:@"pending"]);
    // A command retry and unrelated configuration change must not release a held stop.
    reset();hardware[@"AppleRawCurrentCapacity"]=@4308;onBatteryEvent(1);
    hardware[@"AppleRawCurrentCapacity"]=@4200;onBatteryEvent(1);
    int heldResets=resets;
    handleReqLocked(@{@"api":@"retry_control"});
    assert(resets==heldResets && ![hardware[@"IsCharging"] boolValue]);
    set(@"enable_temp",@YES);
    assert(resets==heldResets && [g_control_reason isEqual:@"capacity"] && ![hardware[@"IsCharging"] boolValue]);
    // Partial writes still own the successfully issued battery stop.
    reset();inflowError=-2;hardware[@"ExternalConnected"]=@NO;
    hardware[@"AppleRawCurrentCapacity"]=@4308;onBatteryEvent(1);
    assert(g_inhibit_active && writes==1);
    hardware[@"ExternalChargeCapable"]=@NO;hardware[@"AdapterDetails"]=@{@"Description":@"batt"};
    onBatteryEvent(1);assert(resets==1 && !g_inhibit_active);
    // Inhibit read-back alone is insufficient if the measured current disagrees.
    reset();conf[@"adv_predictive_inhibit_charge"]=@YES;stubborn=true;
    hardware[@"AppleRawCurrentCapacity"]=@4308;hardware[@"PredictiveChargingInhibit"]=@YES;
    onBatteryEvent(1);assert([g_control_state isEqual:@"pending"]);
    hardware[@"InstantAmperage"]=@0;onBatteryEvent(1);
    assert([g_control_state isEqual:@"confirmed"]);
    reset();conf[@"adv_predictive_inhibit_charge"]=@YES;stubborn=true;
    hardware[@"AppleRawCurrentCapacity"]=@4100;hardware[@"PredictiveChargingInhibit"]=@NO;
    hardware[@"InstantAmperage"]=@2;onBatteryEvent(1);
    assert([g_control_state isEqual:@"pending"]);
    hardware[@"InstantAmperage"]=@295;onBatteryEvent(1);
    assert([g_control_state isEqual:@"confirmed"]);
    // Manual-start errors persist with auto disabled, and explicit retry reissues the start.
    reset();g_enable=NO;conf[@"enable"]=@NO;stubborn=true;
    hardware[@"IsCharging"]=@NO;hardware[@"InstantAmperage"]=@2;
    handleReqLocked(@{@"api":@"set_charge_status",@"flag":@YES});
    expire();expire();expire();assert([g_control_state isEqual:@"failed"] && writes==3);
    onBatteryEvent(1);assert([g_control_state isEqual:@"failed"] && writes==3);
    stubborn=false;handleReqLocked(@{@"api":@"retry_control"});
    assert(writes==4 && [g_control_state isEqual:@"confirmed"]);
    // 自定义实际满容量: 电量计压住的读数要按比例换算, 否则mAh上限永远到不了
    reset(); hardware[@"NominalChargeCapacity"]=@4190; hardware[@"AppleRawCurrentCapacity"]=@4150;
    conf[@"charge_above_mah"]=@4250; conf[@"charge_below_mah"]=@4000; g_policy_memory={};
    onBatteryEvent(1); assert(writes==0 && ![g_control_reason isEqual:@"capacity"]);
    reset(); hardware[@"NominalChargeCapacity"]=@4190; hardware[@"AppleRawCurrentCapacity"]=@4150;
    conf[@"charge_above_mah"]=@4250; conf[@"charge_below_mah"]=@4000; conf[@"full_mah"]=@4300;
    g_policy_memory={}; onBatteryEvent(1);
    assert(writes==1 && [g_control_reason isEqual:@"capacity"] && g_inhibit_active);
    // 上限高于实际满容量时, 读数顶住就停, 不再无限充
    reset(); hardware[@"NominalChargeCapacity"]=@4190; hardware[@"AppleRawCurrentCapacity"]=@4190;
    conf[@"charge_above_mah"]=@4308; conf[@"charge_below_mah"]=@4000; g_policy_memory={};
    onBatteryEvent(1); assert(writes==1 && [g_control_reason isEqual:@"capacity"]);
    reset(); assert([set(@"full_mah",@0)[@"status"] intValue]==0);
    assert([set(@"full_mah",@4300)[@"status"] intValue]==0);
    assert([set(@"full_mah",@500)[@"status"] intValue]==-1);
    assert([set(@"full_mah",@25000)[@"status"] intValue]==-1);
    assert([set(@"full_mah",@4300.5)[@"status"] intValue]==-1);
    assert([set(@"full_mah",@"4300")[@"status"] intValue]==-1);
    // 非法值在启动校验时清回自动
    reset(); conf[@"full_mah"]=@800; initConf(NO);
    assert([getlocalKV(@"full_mah") intValue]==0);
    puts("Actual daemon controller/API passed: immediate settings, read-back, retry limits, cancel, mAh resume, manual, temperature and read failure");
}}
'''
with tempfile.TemporaryDirectory(prefix='charge-controller-test-') as tmp:
    source=Path(tmp)/'test.mm';source.write_text(code+post)
    executable=Path(tmp)/'test'
    subprocess.run(['xcrun','--sdk','macosx','clang++','-std=c++14','-fobjc-arc','-fblocks','-framework','Foundation','-I',str(root/'ChargeLimiter'),str(source),'-o',str(executable)],check=True)
    subprocess.run([str(executable)],check=True)
