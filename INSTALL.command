#!/bin/bash

# ────────────────────────────────────────────────
#  LoadPAP Family — INSTALL.command
#  ดับเบิลคลิกไฟล์นี้เพื่อติดตั้งครั้งแรก
# ────────────────────────────────────────────────

# ไปที่ folder ของโปรแกรม
cd "$(dirname "$0")"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   LoadPAP Family — ติดตั้งโปรแกรม   ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 1. เช็ค Python ──────────────────────────────
echo "🔍 กำลังตรวจสอบ Python..."

if ! command -v python3 &>/dev/null; then
    echo ""
    echo "❌  ไม่พบ Python!"
    echo "    กรุณาดาวน์โหลดที่ https://www.python.org/downloads/"
    echo "    แล้วรัน INSTALL.command อีกครั้ง"
    echo ""
    read -p "กด Enter เพื่อปิดหน้าต่างนี้..."
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1)
echo "✅  พบ $PYTHON_VERSION"

# ── 2. เช็ค pip ─────────────────────────────────
echo ""
echo "🔍 กำลังตรวจสอบ pip..."
python3 -m ensurepip --upgrade &>/dev/null
echo "✅  pip พร้อมใช้งาน"

# ── 3. ติดตั้ง Library ──────────────────────────
echo ""
echo "📦 กำลังติดตั้ง Library ทั้งหมด..."
echo "    (อาจใช้เวลา 2-5 นาที กรุณารอ)"
echo ""

python3 -m pip install -r requirements.txt --quiet --upgrade

if [ $? -ne 0 ]; then
    echo ""
    echo "❌  ติดตั้ง Library ไม่สำเร็จ"
    echo "    กรุณาแจ้งผู้ดูแลโปรแกรม"
    echo ""
    read -p "กด Enter เพื่อปิดหน้าต่างนี้..."
    exit 1
fi

echo "✅  ติดตั้ง Library สำเร็จ"

# ── 4. เช็ค FFmpeg (ไฟล์ใน folder) ─────────────
echo ""
echo "🔍 กำลังตรวจสอบ FFmpeg..."

if [ -f "ffmpeg" ]; then
    chmod +x ffmpeg
    echo "✅  พบ ffmpeg ใน folder"
elif [ -f "ffmpeg/ffmpeg" ]; then
    chmod +x ffmpeg/ffmpeg
    echo "✅  พบ ffmpeg ใน folder"
else
    echo ""
    echo "⚠️  ไม่พบไฟล์ ffmpeg ใน folder โปรแกรม!"
    echo "    กรุณาแจ้งผู้ดูแลโปรแกรมให้ส่งไฟล์ ffmpeg มาด้วย"
fi

# ── 5. เช็คไฟล์ config ──────────────────────────
echo ""
echo "🔍 กำลังตรวจสอบไฟล์ตั้งค่า..."

if [ ! -f "vmaster_config.json" ]; then
    echo "⚠️  ไม่พบ vmaster_config.json"
    echo "    กรุณาแจ้งผู้ดูแลโปรแกรม"
else
    echo "✅  พบไฟล์ตั้งค่า"
fi

if [ ! -f "credentials.json" ]; then
    echo "⚠️  ไม่พบ credentials.json (จำเป็นสำหรับ Google)"
    echo "    กรุณาแจ้งผู้ดูแลโปรแกรม"
else
    echo "✅  พบ Google credentials"
fi

# ── เสร็จสิ้น ────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════╗"
echo "║   ✅  ติดตั้งเสร็จสมบูรณ์!           ║"
echo "║                                      ║"
echo "║   ต่อไปใช้ START.command             ║"
echo "║   เพื่อเปิดโปรแกรมทุกครั้ง           ║"
echo "╚══════════════════════════════════════╝"
echo ""
read -p "กด Enter เพื่อปิดหน้าต่างนี้..."
