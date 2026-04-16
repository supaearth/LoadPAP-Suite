#!/usr/bin/env python3
"""
LoadPAP Suite — setup.py
========================
รันครั้งเดียวหลัง clone จาก GitHub:
    python3 setup.py

สิ่งที่ script นี้ทำ:
  1. เช็ค Python version
  2. เช็ค credentials.json
  3. สร้าง vmaster_config.json ถ้ายังไม่มี
  4. สร้าง venv + ติดตั้ง dependencies
  5. สร้าง START.command บนเครื่องนี้ (path ถูกต้อง 100%)
"""

import os
import sys
import json
import shutil
import subprocess

# ──────────────────────────────────────────
# สีสำหรับ Terminal output
# ──────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):    print(f"{GREEN}  ✅ {msg}{RESET}")
def warn(msg):  print(f"{YELLOW}  ⚠️  {msg}{RESET}")
def err(msg):   print(f"{RED}  ❌ {msg}{RESET}")
def info(msg):  print(f"{BLUE}  ℹ️  {msg}{RESET}")
def header(msg):print(f"\n{BOLD}{msg}{RESET}")

# ──────────────────────────────────────────
# Paths
# ──────────────────────────────────────────
PROJECT_DIR  = os.path.dirname(os.path.abspath(__file__))
VENV_DIR     = os.path.join(PROJECT_DIR, "venv")
VENV_PYTHON  = os.path.join(VENV_DIR, "bin", "python")
VENV_PIP     = os.path.join(VENV_DIR, "bin", "pip")
VENV_ST      = os.path.join(VENV_DIR, "bin", "streamlit")
REQ_FILE     = os.path.join(PROJECT_DIR, "requirements.txt")
CONFIG_FILE  = os.path.join(PROJECT_DIR, "vmaster_config.json")
CREDS_FILE   = os.path.join(PROJECT_DIR, "credentials.json")
START_CMD    = os.path.join(PROJECT_DIR, "START.command")

# Default config — key ครบตาม utils.py
DEFAULT_CONFIG = {
    "gemini_key1":    "",
    "gemini_key2":    "",
    "archive_url":    "",
    "local_archive":  "",
    "dest_folder":    "",
    "p_type":         "Special",
    "last_yt_dlp_update": ""
}

# ──────────────────────────────────────────
# Step 0 — เช็ค git
# ──────────────────────────────────────────
def check_git():
    header("0/5  เช็ค git")
    if shutil.which("git") is not None:
        result = subprocess.run(["git", "--version"], capture_output=True, text=True)
        ok(result.stdout.strip())
    else:
        err("ไม่พบ git ในเครื่องนี้")
        err("กรุณาติดตั้ง git ก่อน แล้วรัน setup.py ใหม่อีกครั้ง")
        info("ดาวน์โหลด git ได้ที่ → https://git-scm.com/download/mac")
        info("(เลือก 'macOS' แล้วกด Download)")
        print()
        sys.exit(1)

# ──────────────────────────────────────────
# Step 1 — เช็ค Python version
# ──────────────────────────────────────────
def check_python():
    header("1/5  เช็ค Python version")
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        err(f"Python {v.major}.{v.minor} — ต้องการ Python 3.10 ขึ้นไป")
        err("ดาวน์โหลดได้ที่ https://www.python.org/downloads/")
        sys.exit(1)
    ok(f"Python {v.major}.{v.minor}.{v.micro}")

# ──────────────────────────────────────────
# Step 2 — เช็ค credentials.json
# ──────────────────────────────────────────
def check_credentials():
    header("2/5  เช็ค credentials.json")
    if os.path.exists(CREDS_FILE):
        ok("พบ credentials.json")
    else:
        warn("ไม่พบ credentials.json")
        warn("วาง credentials.json (รับจากผู้ดูแลโปรแกรม) ลงในโฟลเดอร์นี้ก่อนเปิดใช้งาน")
        warn(f"  → {PROJECT_DIR}")
        # ไม่ exit — ให้ setup ต่อได้ก่อน user จะใส่ทีหลังก็ได้

# ──────────────────────────────────────────
# Step 3 — สร้าง vmaster_config.json
# ──────────────────────────────────────────
def create_config():
    header("3/5  ตรวจสอบ config")
    if os.path.exists(CONFIG_FILE):
        ok("vmaster_config.json มีอยู่แล้ว — ข้ามไป (ไม่ overwrite)")
        return

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=4)
        ok("สร้าง vmaster_config.json แล้ว")
    except Exception as e:
        err(f"สร้าง config ไม่ได้: {e}")
        sys.exit(1)

# ──────────────────────────────────────────
# Step 4 — สร้าง venv + ติดตั้ง dependencies
# ──────────────────────────────────────────
def setup_venv():
    header("4/5  ติดตั้ง dependencies")

    # สร้าง venv ถ้ายังไม่มี
    if not os.path.exists(VENV_PYTHON):
        info("กำลังสร้าง virtual environment...")
        result = subprocess.run([sys.executable, "-m", "venv", VENV_DIR])
        if result.returncode != 0:
            err("สร้าง venv ไม่ได้")
            sys.exit(1)
        ok("สร้าง venv แล้ว")
    else:
        ok("venv มีอยู่แล้ว")

    # upgrade pip ก่อน
    info("Upgrading pip...")
    subprocess.run([VENV_PIP, "install", "--upgrade", "pip", "-q"])

    # ติดตั้ง requirements
    if not os.path.exists(REQ_FILE):
        err("ไม่พบ requirements.txt")
        sys.exit(1)

    info("กำลังติดตั้ง packages (อาจใช้เวลา 3-5 นาที)...")
    result = subprocess.run([VENV_PIP, "install", "-r", REQ_FILE])
    if result.returncode != 0:
        err("ติดตั้ง packages ไม่สำเร็จ")
        sys.exit(1)
    ok("ติดตั้ง packages เสร็จแล้ว")

# ──────────────────────────────────────────
# Step 5 — สร้าง START.command
# ──────────────────────────────────────────
def create_start_command():
    header("5/5  สร้าง START.command")

    # เนื้อหาของ START.command — ใช้ path จริงของเครื่องนี้
    script_content = f"""#!/bin/bash
# LoadPAP Suite — START.command
# สร้างโดย setup.py — ห้ามแก้ไข path ด้วยมือ

PROJECT_DIR="{PROJECT_DIR}"
STREAMLIT="{VENV_ST}"
MAIN_PY="{os.path.join(PROJECT_DIR, '0_Main.py')}"

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
        CHANGED=$(git -C "$PROJECT_DIR" diff HEAD@{{1}} HEAD --name-only 2>/dev/null | grep requirements.txt)
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
"""

    try:
        with open(START_CMD, "w", encoding="utf-8") as f:
            f.write(script_content)
        # ให้ execute permission
        os.chmod(START_CMD, 0o755)
        ok(f"สร้าง START.command แล้ว")
        ok(f"  → {START_CMD}")
    except Exception as e:
        err(f"สร้าง START.command ไม่ได้: {e}")
        sys.exit(1)

# ──────────────────────────────────────────
# Summary
# ──────────────────────────────────────────
def print_summary():
    has_creds = os.path.exists(CREDS_FILE)

    print(f"\n{BOLD}{'═'*50}{RESET}")
    print(f"{BOLD}{GREEN}  🎉 Setup เสร็จแล้ว!{RESET}")
    print(f"{BOLD}{'═'*50}{RESET}\n")

    if not has_creds:
        print(f"{YELLOW}  ⚠️  ยังขาด credentials.json{RESET}")
        print(f"{YELLOW}     ขอไฟล์นี้จากผู้ดูแลโปรแกรม{RESET}")
        print(f"{YELLOW}     แล้ววางไว้ใน: {PROJECT_DIR}{RESET}\n")

    print(f"  วิธีเปิดโปรแกรม (ทุกครั้ง):\n")
    print(f"{BOLD}  ดับเบิลคลิก START.command{RESET}\n")
    print(f"  ครั้งแรกที่เปิด macOS จะถามความปลอดภัย:")
    print(f"  → คลิกขวาที่ START.command → เลือก Open → กด Open\n")

# ──────────────────────────────────────────
# Main
# ──────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{BOLD}{'═'*50}")
    print(f"  LoadPAP Suite — Setup")
    print(f"{'═'*50}{RESET}")

    check_git()
    check_python()
    check_credentials()
    create_config()
    setup_venv()
    create_start_command()
    print_summary()