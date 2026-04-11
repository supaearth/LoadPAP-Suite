#!/bin/bash

# ────────────────────────────────────────────────
#  LoadPAP Family — START.command
#  ดับเบิลคลิกไฟล์นี้เพื่อเปิดโปรแกรม
# ────────────────────────────────────────────────

cd "$(dirname "$0")"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   LoadPAP Family — กำลังเปิดระบบ    ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── เช็คเบื้องต้น ────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "❌  ไม่พบ Python! กรุณารัน INSTALL.command ก่อน"
    echo ""
    read -p "กด Enter เพื่อปิด..."
    exit 1
fi

if [ ! -f "0_Main.py" ]; then
    echo "❌  ไม่พบไฟล์โปรแกรม!"
    echo "    กรุณาตรวจสอบว่า START.command อยู่ใน folder LoadPAP"
    echo ""
    read -p "กด Enter เพื่อปิด..."
    exit 1
fi

# ── เช็ค token เก่า (ถ้า Google login มีปัญหา) ──
if [ -f "token.pickle" ]; then
    TOKEN_AGE=$(( ($(date +%s) - $(stat -f%m token.pickle)) / 86400 ))
    if [ $TOKEN_AGE -gt 6 ]; then
        echo "🔄 รีเฟรช Google Token..."
        rm -f token.pickle
    fi
fi

# ── เปิดโปรแกรม ──────────────────────────────────
echo "🚀 กำลังเปิด LoadPAP Family..."
echo "    (รอสักครู่ Chrome จะเปิดขึ้นมาเอง)"
echo ""
echo "────────────────────────────────────────"
echo "  ปิดโปรแกรม: กด Ctrl+C ในหน้าต่างนี้"
echo "  หรือปิดหน้าต่าง Terminal นี้ได้เลย"
echo "────────────────────────────────────────"
echo ""

# รอให้ Streamlit พร้อมก่อนเปิด browser
python3 -m streamlit run 0_Main.py --server.headless true &
STREAMLIT_PID=$!

sleep 4

# เปิด Chrome
open -a "Google Chrome" "http://localhost:8501" 2>/dev/null || \
open "http://localhost:8501"

echo "✅  โปรแกรมเปิดแล้ว! ดูที่ Chrome"
echo ""
echo "⚠️  อย่าปิดหน้าต่าง Terminal นี้ขณะใช้งาน"
echo ""

# รอจนกว่า Streamlit จะถูกปิด
wait $STREAMLIT_PID
