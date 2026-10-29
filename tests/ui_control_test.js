const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');
const root = path.resolve(__dirname, '..');
const languages = JSON.parse(fs.readFileSync(path.join(root, 'www/lang.json'), 'utf8'));
const context = {
    $: {ajax: options => options.success(languages)},
    VueI18n: function(options) { return options; },
    window: {test: true, addEventListener() {}},
    get_local_lang: () => 'zh_CN', get_local_val: (a, b, fallback) => fallback,
    range: () => [], get_id: () => 'test', setTimeout() {},
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root, 'www/js/app.js'), 'utf8') + '\nglobalThis.appOptions = App;', context);
const app = {...context.appOptions.data(), ...context.appOptions.methods};
app.daemon_alive = true;
app.bat_info = {IsCharging: false, CurrentCapacity: 90};
for (const reason of ['capacity', 'temperature', 'manual', 'disabled', 'low_battery', 'edge', 'invalid_data']) {
    app.control_status = {state: 'confirmed', reason};
    assert.strictEqual(app.get_ui_status(), 'ui_reason_' + reason);
}
app.control_status = {state: 'pending', target: 0};
assert.strictEqual(app.get_ui_status(), 'ui_confirm_stop');
app.control_status.target = 1;
assert.strictEqual(app.get_ui_status(), 'ui_confirm_start');
app.control_status = {state: 'failed', reason: 'capacity', attempts: 3, error: -4};
assert.strictEqual(app.get_ui_status(), 'ui_control_failed');
assert.strictEqual(app.get_control_error(), 'ui_control_not_changed');
app.control_status.error=-5;
assert.strictEqual(app.get_control_error(), 'ui_control_read_failed');
let writes = [], refreshes = 0;
app.ipc_send_wrapper = request => writes.push(request);
app.get_conf = () => refreshes++;
app.set_charge_below_mah(4100);
assert.strictEqual(writes[0].key, 'charge_below_mah');
for (const value of [0, 4308, NaN, 4100.5, '4100']) app.set_charge_below_mah(value);
assert.strictEqual(writes.length, 1);
assert.strictEqual(refreshes, 5);
app.set_charge_above_mah(4100);
assert.strictEqual(writes.length, 1);
app.retry_control();
assert.strictEqual(writes[1].api, 'retry_control');
for (const language of Object.values(languages)) {
    for (const key of ['ui_control_failed', 'ui_confirm_stop', 'ui_confirm_start', 'ui_reason_capacity', 'ui_save_failed']) assert(language[key]);
}
console.log('Frontend control reasons, confirmation states, threshold validation, retry and translations passed');
app.adv_predictive_inhibit_charge=true;
app.bat_info={IsCharging:true,PredictiveChargingInhibit:true,InstantAmperage:0};
assert.strictEqual(app.is_charge(),false);
app.bat_info.PredictiveChargingInhibit=false;app.bat_info.InstantAmperage=2;
assert.strictEqual(app.is_charge(),false);
app.bat_info.InstantAmperage=295;assert.strictEqual(app.is_charge(),true);
app.bat_info.NominalChargeCapacity=4086;app.charge_above_mah=4308;
assert.strictEqual(app.mah_limit_above_estimate(),true);
app.control_status={state:'idle',reason:'no_power'};
assert.strictEqual(app.get_ui_status(),'ui_on_battery');
app.bat_info.PredictiveChargingInhibit=0;app.bat_info.InstantAmperage=2;
assert.strictEqual(app.is_charge(),false);
// 真机对照行: 原始禁充标志必须能区分"读不到"和"未禁充"
app.$t = key => key;
app.bat_info={};
assert.strictEqual(app.predictive_inhibit_text(),'ui_not_reported');
app.bat_info={PredictiveChargingInhibit:false};
assert.strictEqual(app.predictive_inhibit_text(),'ui_inhibit_off');
app.bat_info={PredictiveChargingInhibit:true};
assert.strictEqual(app.predictive_inhibit_text(),'ui_inhibit_on');
for (const language of Object.values(languages)) {
    for (const key of ['ui_predictive_inhibit', 'ui_inhibit_on', 'ui_inhibit_off']) assert(language[key]);
}
// 自定义实际满容量: 换算、阈值警告与取值校验
app.bat_info={NominalChargeCapacity:4190,AppleRawCurrentCapacity:4150};
app.full_mah=0;
assert.strictEqual(app.effective_full_mah(),4190);
assert.strictEqual(app.scaled_mah(),4150);
app.full_mah=4300;
assert.strictEqual(app.effective_full_mah(),4300);
assert.strictEqual(app.scaled_mah(),4259);
app.charge_above_mah=4250;
assert.strictEqual(app.mah_limit_above_estimate(),false);
app.charge_above_mah=4308;
assert.strictEqual(app.mah_limit_above_estimate(),true);
writes=[];refreshes=0;
app.set_full_mah(4300);
assert.strictEqual(writes[0].key,'full_mah');
for (const value of [500, 25000, 4300.5, '4300', NaN, -1]) app.set_full_mah(value);
assert.strictEqual(writes.length,1);
assert.strictEqual(refreshes,6);
app.set_full_mah(0);
assert.strictEqual(writes.length,2);
for (const language of Object.values(languages)) {
    for (const key of ['full_mah', 'full_mah_sys', 'full_mah_desc', 'charge_above_mah_warn']) assert(language[key]);
}
