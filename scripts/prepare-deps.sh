#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DEPS_DIR="${CHARGELIMITER_DEPS_DIR:-$ROOT_DIR/.build-deps}"
MIN_IOS_VERSION="${MIN_IOS_VERSION:?需要由 build.sh 指定最低系统版本}"
mkdir -p "$DEPS_DIR/bin" "$DEPS_DIR/downloads" "$DEPS_DIR/frameworks"

# Versions and SHA-256 digests are pinned; only fetch from the upstream projects.
download() {
    local url="$1" dest="$2" digest="$3"
    if [[ -f "$dest" ]] && [[ "$(shasum -a 256 "$dest" | awk '{print $1}')" == "$digest" ]]; then
        return
    fi
    printf '下载依赖: %s\n' "$url"
    curl --fail --location --retry 2 --connect-timeout 20 --max-time 180 "$url" -o "$dest.part"
    if [[ "$(shasum -a 256 "$dest.part" | awk '{print $1}')" != "$digest" ]]; then
        rm -f "$dest.part"
        echo '下载文件的 SHA-256 校验失败。' >&2
        exit 1
    fi
    mv -f "$dest.part" "$dest"
}

if [[ -z "${LDID:-}" ]] && ! command -v ldid >/dev/null 2>&1; then
    case "$(uname -m)" in
        arm64) arch=arm64; digest=5dff8e6b8d9dc3ff7226276c81e09930865f15381f54cb55b98b196a94c5ca50 ;;
        x86_64) arch=x86_64; digest=9d46e0feedf96e399edfca09872802ba21e729f79c01927ad25ea2b0a35bca23 ;;
        *) echo 'ldid 自动下载仅支持 arm64/x86_64 Mac。' >&2; exit 1 ;;
    esac
    download "https://github.com/ProcursusTeam/ldid/releases/download/v2.1.5-procursus7/ldid_macosx_$arch" \
        "$DEPS_DIR/bin/ldid" "$digest"
    chmod +x "$DEPS_DIR/bin/ldid"
fi

HEADERS_REV=13c1f17176d7efe6871551cd69a75b71ac4eeaf1
if [[ ! -f "$DEPS_DIR/headers/.revision" ]] || [[ "$(cat "$DEPS_DIR/headers/.revision")" != "$HEADERS_REV" ]]; then
    download "https://codeload.github.com/theos/headers/tar.gz/$HEADERS_REV" \
        "$DEPS_DIR/downloads/headers-pinned.tar.gz" 2865737f72bf92b9eb94e732d5ec0f709bec7527521eb79c33413e0c6b5c6693
    mkdir -p "$DEPS_DIR/headers"
    tar -xzf "$DEPS_DIR/downloads/headers-pinned.tar.gz" -C "$DEPS_DIR/headers" --strip-components=1
    printf '%s\n' "$HEADERS_REV" > "$DEPS_DIR/headers/.revision"
fi

FRAMEWORK="$DEPS_DIR/frameworks/GCDWebServers.framework"
SDK_VERSION="$(xcrun --sdk iphoneos --show-sdk-version)"
BUILD_KEY="3.5.4-arm64-$SDK_VERSION-$MIN_IOS_VERSION-$(xcodebuild -version | tr '\n' ' ')"
if [[ ! -f "$FRAMEWORK/GCDWebServers" ]] || [[ ! -f "$DEPS_DIR/frameworks/.build-key" ]] || \
    [[ "$(cat "$DEPS_DIR/frameworks/.build-key")" != "$BUILD_KEY" ]]; then
    download 'https://codeload.github.com/swisspol/GCDWebServer/tar.gz/refs/tags/3.5.4' \
        "$DEPS_DIR/downloads/GCDWebServer.tar.gz" 5da4668b3b274ceff5d47f4c9ae22c3d7078932071a52ed8f607513642c969a7
    mkdir -p "$DEPS_DIR/GCDWebServer"
    tar -xzf "$DEPS_DIR/downloads/GCDWebServer.tar.gz" -C "$DEPS_DIR/GCDWebServer" --strip-components=1
    echo '编译 GCDWebServers（iOS 真机 arm64）…'
    if ! xcodebuild -project "$DEPS_DIR/GCDWebServer/GCDWebServer.xcodeproj" \
        -scheme 'GCDWebServers (iOS)' -configuration Release -sdk iphoneos \
        -destination 'generic/platform=iOS' -derivedDataPath "$DEPS_DIR/webserver-build" \
        ARCHS=arm64 "IPHONEOS_DEPLOYMENT_TARGET=$MIN_IOS_VERSION" \
        CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO GCC_TREAT_WARNINGS_AS_ERRORS=NO \
        build > "$DEPS_DIR/webserver-build.log" 2>&1; then
        tail -n 60 "$DEPS_DIR/webserver-build.log" >&2
        printf 'GCDWebServers 编译失败，完整日志: %s\n' "$DEPS_DIR/webserver-build.log" >&2
        exit 1
    fi
    rm -rf -- "$FRAMEWORK"
    ditto "$DEPS_DIR/webserver-build/Build/Products/Release-iphoneos/GCDWebServers.framework" "$FRAMEWORK"
    printf '%s\n' "$BUILD_KEY" > "$DEPS_DIR/frameworks/.build-key"
fi
