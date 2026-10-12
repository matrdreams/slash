#!/usr/bin/env bash
# Wait for Redroid to finish booting, then install + enable ADBKeyBoard.
set -euo pipefail
SERIAL=${1:-127.0.0.1:15556}; TIMEOUT=${TIMEOUT:-1800}
APK=${APK:-/workspace/vm/ADBKeyboard.apk}
APK_URL=${APK_URL:-https://github.com/senzhk/ADBKeyBoard/raw/master/ADBKeyboard.apk}
[[ -f $APK ]] || { APK=/tmp/ADBKeyboard.apk; wget -qO "$APK" "$APK_URL"; }
end=$((SECONDS+TIMEOUT))
until adb connect "$SERIAL" >/dev/null 2>&1 && [[ $(adb -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r') == 1 ]]; do
  ((SECONDS<end)) || { echo "timeout waiting for $SERIAL" >&2; exit 1; }; sleep 5; done
echo "boot_completed after ${SECONDS}s"
adb -s "$SERIAL" install -r "$APK"
adb -s "$SERIAL" shell ime enable com.android.adbkeyboard/.AdbIME
adb -s "$SERIAL" shell ime set com.android.adbkeyboard/.AdbIME
