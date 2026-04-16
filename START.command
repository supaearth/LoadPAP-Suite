#!/bin/bash
# LoadPAP Suite — START.command
# สร้างโดย setup.py — ห้ามแก้ไข path ด้วยมือ

PROJECT_DIR="/Users/macstudio/Documents/LoadPAP - Suite"
STREAMLIT="/Users/macstudio/Documents/LoadPAP - Suite/venv/bin/streamlit"
MAIN_PY="/Users/macstudio/Documents/LoadPAP - Suite/0_Main.py"

cd "$PROJECT_DIR"

# ─── แสดง Terminal window ───
echo ""
echo "╔══════════════════════════════════╗"
echo "║      LoadPAP Suite — Starting    ║"
echo "╚══════════════════════════════════╝"
echo ""

# ─── เช็ค internet ก่อน pull ───
echo "🔄 กำลังเช็ค update..."
if ping -c 1 github.com &> /dev/null; then
    git -C "$PROJECT_DIR" fetch origin main -q 2>/dev/null

    # merge แบบ safe — ถ้า conflict เอาของ local ไว้เสมอ
    MERGE_OUTPUT=$(git -C "$PROJECT_DIR" merge -X ours origin/main 2>&1)

    if echo "$MERGE_OUTPUT" | grep -q "Already up to date"; then
        echo "✅ โปรแกรมเป็นเวอร์ชันล่าสุดแล้ว"
    else
        echo "✅ อัพเดทเสร็จแล้ว"

        # เช็คว่า requirements.txt เปลี่ยนมั้ย
        CHANGED=$(git -C "$PROJECT_DIR" diff HEAD@{1} HEAD --name-only 2>/dev/null | grep requirements.txt)
        if [ -n "$CHANGED" ]; then
            echo "📦 กำลังอัพเดท packages..."
            "$PROJECT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt" -q
            echo "✅ อัพเดท packages เสร็จแล้ว"
        fi
    fi
else
    echo "⚠️  ไม่มี internet — ข้ามการ update"
fi

echo ""

# ─── เช็ค credentials ───
if [ ! -f "$PROJECT_DIR/credentials.json" ]; then
    echo "❌ ไม่พบ credentials.json"
    echo "   กรุณาวางไฟล์ credentials.json ในโฟลเดอร์:"
    echo "   $PROJECT_DIR"
    echo ""
    echo "กด Enter เพื่อปิด..."
    read
    exit 1
fi

# ─── รัน Streamlit ───
echo "🚀 กำลังเปิด LoadPAP..."
"$STREAMLIT" run "$MAIN_PY" --server.headless true --server.port 8501 &
STREAMLIT_PID=$!

# รอให้ Streamlit พร้อม
sleep 3

# เปิด Chrome
open -a "Google Chrome" "http://localhost:8501" 2>/dev/null || open "http://localhost:8501"

echo "✅ LoadPAP เปิดแล้วที่ http://localhost:8501"
echo ""
echo "⚠️  อย่าปิดหน้าต่างนี้ระหว่างใช้งาน"
echo "   กด Ctrl+C เพื่อปิดโปรแกรม"
echo ""

# รอจนกว่า user จะกด Ctrl+C
wait $STREAMLIT_PID
