import subprocess
import time

print("🚀 กำลังสตาร์ทเครื่องยนต์บอท...")

# 1. สั่งรันบอทแบบเงียบๆ
subprocess.Popen(["python3", "-m", "streamlit", "run", "0_Main.py"])

# 2. รอ 3 วินาทีให้เซิร์ฟเวอร์พร้อม
time.sleep(3)

# 3. บังคับ Mac เปิด Chrome
subprocess.run(['open', '-a', 'Google Chrome', 'http://localhost:8501'])