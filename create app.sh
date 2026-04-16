#!/bin/bash

# หา Python ที่ใช้ได้
PYTHON=""
for cmd in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v $cmd &>/dev/null; then
        PYTHON=$(command -v $cmd)
        break
    fi
done

if [ -z "$PYTHON" ]; then
    osascript -e 'display dialog "❌ ไม่พบ Python กรุณาติดตั้งที่ python.org ก่อน" buttons {"OK"}'
    exit 1
fi

FOLDER="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$FOLDER/LoadPAP.app"

# สร้าง .app structure
mkdir -p "$APP_PATH/Contents/MacOS"

cat > "$APP_PATH/Contents/MacOS/LoadPAP" << EOF
#!/bin/bash
cd "$FOLDER"
$PYTHON start.py
EOF

chmod +x "$APP_PATH/Contents/MacOS/LoadPAP"

cat > "$APP_PATH/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>LoadPAP</string>
    <key>CFBundleName</key>
    <string>LoadPAP</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
</dict>
</plist>
EOF

osascript -e 'display dialog "✅ สร้าง LoadPAP.app เสร็จแล้ว!\nดับเบิลคลิก LoadPAP.app เพื่อเปิดโปรแกรมได้เลย" buttons {"OK"}'