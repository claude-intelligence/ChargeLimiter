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
    if (!writeError && !stubborn && !stubbornInflow) hardware[@"ExternalConnected"]=@(value);
    return writeError;
}
static int setBatteryStatus(BOOL value) {
    ++writes;
    if (!writeError && !stubborn) { hardware[@"IsCharging"]=@(value); hardware[@"InstantAmperage"]=value ? @295 : @0; }
    return writeError;
}
static void resetBatteryStatus() { hardware[@"IsCharging"]=@YES; hardware[@"InstantAmperage"]=@295; hardware[@"ExternalConnected"]=@YES; }
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
code = (pre + section('static BOOL isAdaptorConnect(', 'static int setChargeStatus(')
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
    g_manual_stop=NO; g_policy_memory={}; g_verify_scheduled=NO; scheduled=nil;
    cancelControl(); initConf(NO); g_enable=YES; conf[@"enable"]=@YES;
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
    reset(); writeError=-2; hardware[@"AppleRawCurrentCapacity"]=@4500; onBatteryEvent(1);
    expire(); expire(); expire(); assert(writes==3 && g_control_error==-2 && [g_control_state isEqual:@"failed"]);
    reset(); stubborn=true; hardware[@"AppleRawCurrentCapacity"]=@4500; onBatteryEvent(1);
    set(@"enable",@NO); if(scheduled) scheduled(); expire(); assert(writes==1 && [g_control_reason isEqual:@"disabled"]);
    reset(); stubborn=true; hardware[@"AppleRawCurrentCapacity"]=@4500; onBatteryEvent(1);
    hardware[@"ExternalChargeCapable"]=@NO; onBatteryEvent(1); expire(); assert(writes==1 && [g_control_reason isEqual:@"no_power"]);
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
    puts("Actual daemon controller/API passed: immediate settings, read-back, retry limits, cancel, mAh resume, manual, temperature and read failure");
}}
'''
with tempfile.TemporaryDirectory(prefix='charge-controller-test-') as tmp:
    source=Path(tmp)/'test.mm';source.write_text(code+post)
    executable=Path(tmp)/'test'
    subprocess.run(['xcrun','--sdk','macosx','clang++','-std=c++14','-fobjc-arc','-fblocks','-framework','Foundation','-I',str(root/'ChargeLimiter'),str(source),'-o',str(executable)],check=True)
    subprocess.run([str(executable)],check=True)
