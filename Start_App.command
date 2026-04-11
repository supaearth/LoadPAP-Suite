#!/bin/bash
cd "$(dirname "$0")"

echo "========================================="
echo "🧹 กำลังเคลียร์ระบบที่ค้างอยู่..."
pkill -f streamlit
sleep 1

echo "🏆 กำลังสตาร์ท LoadPAP Family..."
echo "⚠️ ห้ามปิดหน้าต่างนี้จนกว่าจะเลิกใช้งานนะครับ"
echo "========================================="

# ตั้งเวลาไขลานเปิด Google Chrome
(sleep 3 && open -a "Google Chrome" http://localhost:8501) &

# รันไฟล์หน้าแรก — --server.headless true บล็อก streamlit ไม่ให้เปิด browser เอง
python3 -m streamlit run 0_Main.py --server.headless true