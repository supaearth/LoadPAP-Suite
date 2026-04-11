#!/bin/bash

# ────────────────────────────────────────────────
#  LoadPAP Family — UPDATE.command
#  ดับเบิลคลิกเพื่ออัพเดทโปรแกรมเป็นเวอร์ชั่นล่าสุด
# ────────────────────────────────────────────────

cd "$(dirname "$0")"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   LoadPAP Family — อัพเดทโปรแกรม    ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── เช็ค git ─────────────────────────────────────
if ! command -v git &>/dev/null; then
    echo "❌  ไม่พบ git"
    echo "    ดาวน์โหลดได้ที่ https://git-scm.com/download/mac"
    echo ""
    read -p "กด Enter เพื่อปิดหน้าต่างนี้..."
    exit 1
fi

if [ ! -d ".git" ]; then
    echo "❌  folder นี้ไม่ใช่ Git repo"
    echo "    กรุณาแจ้งผู้ดูแลโปรแกรม"
    echo ""
    read -p "กด Enter เพื่อปิดหน้าต่างนี้..."
    exit 1
fi

# ── ดึงโค้ดใหม่ ───────────────────────────────────
echo "🔄 กำลังดึงโค้ดล่าสุดจาก GitHub..."
git pull origin main

if [ $? -ne 0 ]; then
    echo ""
    echo "❌  อัพเดทไม่สำเร็จ กรุณาแจ้งผู้ดูแลโปรแกรม"
    echo ""
    read -p "กด Enter เพื่อปิดหน้าต่างนี้..."
    exit 1
fi

echo ""
echo "📦 กำลังอัพเดท Library..."
python3 -m pip install -r requirements.txt --quiet --upgrade
echo "✅  Library อัพเดทแล้ว"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   ✅  อัพเดทเสร็จสมบูรณ์!            ║"
echo "╚══════════════════════════════════════╝"
echo ""

read -p "เปิดโปรแกรมเลยไหม? (Y = ใช่, Enter = ไม่): " OPEN_NOW
if [[ "$OPEN_NOW" =~ ^[Yy]$ ]]; then
    python3 -m streamlit run 0_Main.py --server.headless true &
    sleep 4
    open -a "Google Chrome" "http://localhost:8501" 2>/dev/null || open "http://localhost:8501"
    echo "✅  โปรแกรมเปิดแล้ว!"
    echo "⚠️  อย่าปิดหน้าต่างนี้ขณะใช้งาน"
    wait
else
    read -p "กด Enter เพื่อปิดหน้าต่างนี้..."
fi
