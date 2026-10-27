#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$ROOT_DIR/LatestBuild"
CONFIGURATION=Release
CHECK_ONLY=0
DEPS_DIR="${CHARGELIMITER_DEPS_DIR:-$ROOT_DIR/.build-deps}"
export CHARGELIMITER_DEPS_DIR="$DEPS_DIR"

usage() {
    cat <<'EOF'
用法: ./build.sh [--debug] [--check] [--help]

编译主程序和后台守护进程，输出 LatestBuild/ChargeLimiter.ipa，供巨魔安装。
不需要开发者证书、描述文件或 MonkeyDev，不会自动安装到设备。
首次运行自动下载并准备依赖，缓存到 .build-deps，无需修改 /opt。
使用 ldid 写入项目的私有权限，供巨魔在安装时保留。

  --debug    使用 Debug 配置（默认 Release）
  --check    仅检查本地依赖，不下载或编译
  --help     显示帮助

环境变量:
  MIN_IOS_VERSION  最低 iOS 版本；默认取 12.0 与当前 SDK 支持下限的较高值
  LDID             ldid 可执行文件路径（默认从 PATH 或项目缓存查找）
  CHARGELIMITER_DEPS_DIR  依赖缓存目录（默认 .build-deps）
  DEVELOPER_DIR    指定 Xcode 开发者目录（由 xcodebuild/xcrun 使用）
EOF
}

for arg in "$@"; do
    case "$arg" in
        --debug) CONFIGURATION=Debug ;;
        --check) CHECK_ONLY=1 ;;
        --help|-h) usage; exit 0 ;;
        *) printf '未知参数: %s\n' "$arg" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ "$(uname -s)" != Darwin ]]; then
    echo '需要在安装完整 Xcode 的 macOS 上运行。' >&2
    exit 1
fi

missing=0
for tool in xcodebuild xcrun ditto plutil zip otool curl tar shasum python3; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf '缺少工具: %s\n' "$tool" >&2
        missing=1
    fi
done
if (( missing )); then exit 1; fi

SDK_PATH="$(xcrun --sdk iphoneos --show-sdk-path)"
SDK_MIN="$(/usr/libexec/PlistBuddy -c 'Print :SupportedTargets:iphoneos:MinimumDeploymentTarget' "$SDK_PATH/SDKSettings.plist")"
MIN_IOS_VERSION="${MIN_IOS_VERSION:-$(awk -v sdk="$SDK_MIN" 'BEGIN { print (sdk + 0 > 12 ? sdk : "12.0") }')}"
if [[ ! "$MIN_IOS_VERSION" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
    echo 'MIN_IOS_VERSION 必须是版本号，例如 15.0。' >&2
    exit 1
fi
if ! awk -v chosen="$MIN_IOS_VERSION" -v sdk="$SDK_MIN" 'BEGIN { exit !(chosen + 0 >= sdk + 0) }'; then
    printf '当前 SDK 最低支持 iOS %s；如需更旧系统，请使用支持它的 Xcode。\n' "$SDK_MIN" >&2
    exit 1
fi
export MIN_IOS_VERSION
if (( ! CHECK_ONLY )); then
    /bin/bash "$ROOT_DIR/scripts/prepare-deps.sh"
fi
LDID_BIN="${LDID:-$(command -v ldid || true)}"
if [[ -z "$LDID_BIN" && -x "$DEPS_DIR/bin/ldid" ]]; then
    LDID_BIN="$DEPS_DIR/bin/ldid"
fi
if [[ ! -x "$LDID_BIN" ]]; then
    echo '缺少 ldid：运行 ./build.sh 自动准备，或通过 LDID 指定路径。' >&2
    missing=1
fi
for header in IOKit/IOKitLib.h IOKit/hid/IOHIDService.h; do
    if [[ ! -f "$DEPS_DIR/headers/$header" ]]; then
        printf '缺少私有头文件: %s（运行 ./build.sh 自动准备）\n' "$header" >&2
        missing=1
    fi
done
FRAMEWORK_DIR="$DEPS_DIR/frameworks/GCDWebServers.framework"
if [[ ! -f "$FRAMEWORK_DIR/Headers/GCDWebServers.h" || ! -f "$FRAMEWORK_DIR/GCDWebServers" ]]; then
    echo '缺少项目内的 GCDWebServers.framework（运行 ./build.sh 自动准备）。' >&2
    missing=1
fi
if (( missing )); then exit 1; fi

printf '依赖检查通过，配置: %s，最低系统: iOS %s\n' "$CONFIGURATION" "$MIN_IOS_VERSION"
if (( CHECK_ONLY )); then exit 0; fi

mkdir -p "$BUILD_DIR"
LOG_PATH="$BUILD_DIR/build.log"
trap 'printf "构建失败，请查看 %s\n" "$LOG_PATH" >&2' ERR
cd "$ROOT_DIR"
xcodebuild \
    -project "$ROOT_DIR/ChargeLimiter.xcodeproj" \
    -scheme ChargeLimiter \
    -configuration "$CONFIGURATION" \
    -sdk iphoneos \
    -destination 'generic/platform=iOS' \
    -derivedDataPath "$BUILD_DIR/DerivedData" \
    ARCHS=arm64 ONLY_ACTIVE_ARCH=NO \
    "CHARGELIMITER_FRAMEWORK_DIR=$DEPS_DIR/frameworks" \
    'HEADER_SEARCH_PATHS=$(inherited) "'"$DEPS_DIR/headers"'"' \
    'FRAMEWORK_SEARCH_PATHS=$(inherited) "'"$DEPS_DIR/frameworks"'"' \
    "IPHONEOS_DEPLOYMENT_TARGET=$MIN_IOS_VERSION" \
    CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY= \
    ENABLE_USER_SCRIPT_SANDBOXING=NO CHARGELIMITER_IPA_BUILD=YES \
    MonkeyDevBuildPackageOnAnyBuild=NO MonkeyDevInstallOnAnyBuild=NO \
    build 2>&1 | tee "$LOG_PATH"

PRODUCTS_DIR="$BUILD_DIR/DerivedData/Build/Products/$CONFIGURATION-iphoneos"
APP_SOURCE="$PRODUCTS_DIR/ChargeLimiter.app"
DAEMON_SOURCE="$PRODUCTS_DIR/ChargeLimiterDaemon.app/ChargeLimiterDaemon"
[[ -x "$APP_SOURCE/ChargeLimiter" && -x "$DAEMON_SOURCE" ]]

STAGING_DIR="$(mktemp -d "$BUILD_DIR/ipa.XXXXXX")"
trap 'rm -rf -- "$STAGING_DIR"' EXIT
APP_DIR="$STAGING_DIR/Payload/ChargeLimiter.app"
mkdir -p "$STAGING_DIR/Payload"
ditto "$APP_SOURCE" "$APP_DIR"
cp "$DAEMON_SOURCE" "$APP_DIR/ChargeLimiterDaemon"
chmod 755 "$APP_DIR/ChargeLimiterDaemon"
rm -rf -- "$APP_DIR/_CodeSignature" "$APP_DIR/embedded.mobileprovision"

# A dynamic GCDWebServers build must travel with the app and daemon.
if otool -L "$APP_DIR/ChargeLimiter" "$APP_DIR/ChargeLimiterDaemon" | grep -q '@rpath/GCDWebServers.framework/'; then
    mkdir -p "$APP_DIR/Frameworks"
    ditto "$FRAMEWORK_DIR" "$APP_DIR/Frameworks/GCDWebServers.framework"
    rm -rf -- "$APP_DIR/Frameworks/GCDWebServers.framework/_CodeSignature"
    "$LDID_BIN" -S "$APP_DIR/Frameworks/GCDWebServers.framework/GCDWebServers"
fi

ENTITLEMENTS="$ROOT_DIR/ChargeLimiter/ChargeLimiter.entitlements"
"$LDID_BIN" "-S$ENTITLEMENTS" "$APP_DIR/ChargeLimiterDaemon"
"$LDID_BIN" "-S$ENTITLEMENTS" "$APP_DIR/ChargeLimiter"
plutil -lint "$APP_DIR/Info.plist"
python3 "$ROOT_DIR/scripts/package-ipa.py" "$APP_DIR" "$STAGING_DIR/ChargeLimiter.ipa"
python3 "$ROOT_DIR/scripts/package-ipa.py" "$APP_DIR" "$STAGING_DIR/ChargeLimiter-iOS16.ipa" --store
python3 "$ROOT_DIR/scripts/verify-ipa.py" "$STAGING_DIR/ChargeLimiter.ipa"
python3 "$ROOT_DIR/scripts/verify-ipa.py" "$STAGING_DIR/ChargeLimiter-iOS16.ipa"
mv -f "$STAGING_DIR/ChargeLimiter.ipa" "$BUILD_DIR/ChargeLimiter.ipa"
mv -f "$STAGING_DIR/ChargeLimiter-iOS16.ipa" "$BUILD_DIR/ChargeLimiter-iOS16.ipa"
cp -f "$BUILD_DIR/ChargeLimiter.ipa" "$BUILD_DIR/ChargeLimiter-TrollStore.ipa"
printf '\n已生成: %s\n' "$BUILD_DIR/ChargeLimiter.ipa"
printf '巨魔安装文件: %s\n' "$BUILD_DIR/ChargeLimiter-TrollStore.ipa"
printf '无压缩兼容测试包: %s\n' "$BUILD_DIR/ChargeLimiter-iOS16.ipa"
echo '用巨魔安装后，打开 App 并开启全局开关；锁屏充电控制由独立守护进程执行。'
