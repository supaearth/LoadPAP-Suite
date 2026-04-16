# LoadPAP Suite

**Load Process Automation Pipeline** — ระบบอัตโนมัติสำหรับ workflow การผลิตวิดีโอ

---

## เครื่องมือทั้งหมด

| ชื่อ | หน้าที่ |
|---|---|
| **PyLOAD** | ดาวน์โหลดฟุตเทจอัตโนมัติจาก Google Doc สคริปต์ |
| **PyRUSH** | ตัดวิดีโออัตโนมัติจาก cut list ใน Google Sheet |
| **PyLOG** | Log และค้นหาฟุตเทจด้วย Gemini Vision AI |
| **PyLIVE** | คลิปวิดีโอจาก Live Stream *(กำลังพัฒนา)* |

---

## ติดตั้ง (ครั้งแรกครั้งเดียว)

### สิ่งที่ต้องเตรียมก่อน

**1. ติดตั้ง Git**
ตรวจสอบโดยเปิด Terminal แล้วพิมพ์ `git --version`
ถ้าขึ้น `command not found` → ดาวน์โหลดที่ [git-scm.com/download/mac](https://git-scm.com/download/mac)

**2. ติดตั้ง Python 3.10 ขึ้นไป**
ตรวจสอบโดยพิมพ์ `python3 --version`
ถ้าไม่มีหรือเวอร์ชันต่ำกว่า 3.10 → ดาวน์โหลดที่ [python.org/downloads](https://www.python.org/downloads/)

---

### ขั้นตอนติดตั้ง

**1. ดาวน์โหลดโปรแกรม**

**ทางเลือก A — ใช้ Git (แนะนำ อัพเดทง่ายกว่า)**

เปิด Terminal แล้วรัน:
```bash
git clone https://github.com/supaearth/LoadPAP-Suit.git
```
> ถ้าไม่คุ้นกับ Terminal — กด `Cmd+Space` พิมพ์ **Terminal** แล้วกด Enter

**ทางเลือก B — Download ZIP (ไม่ต้องมี Git)**

กดปุ่ม **Code → Download ZIP** ที่ [github.com/supaearth/LoadPAP-Suit](https://github.com/supaearth/LoadPAP-Suit)
แล้วแตกไฟล์ ZIP ที่ได้

> ⚠️ ถ้าใช้วิธีนี้ START.command จะ **ไม่อัพเดทอัตโนมัติ** — ต้อง Download ZIP ใหม่ทุกครั้งที่มีอัพเดท

---

**2. วาง credentials.json**

รับไฟล์ `credentials.json` จากผู้ดูแลโปรแกรม แล้ววางลงในโฟลเดอร์ `LoadPAP-Suite`

```
LoadPAP-Suite/
├── credentials.json   ← วางตรงนี้
├── 0_Main.py
├── setup.py
└── ...
```

---

**3. รัน setup.py**

เปิด Terminal → ลาก `setup.py` เข้าไปในหน้าต่าง Terminal → กด Enter

```
python3 /path/to/LoadPAP-Suite/setup.py
```

รอประมาณ **3–5 นาที** — script จะติดตั้งทุกอย่างให้อัตโนมัติ

เมื่อเสร็จจะเห็น:
```
══════════════════════════════════════════════════
  🎉 Setup เสร็จแล้ว!
══════════════════════════════════════════════════
  ดับเบิลคลิก START.command
```

---

**4. รับ Gemini API Key (ฟรี)**

1. เข้า [aistudio.google.com](https://aistudio.google.com)
2. Sign in ด้วย Google Account
3. กด **Get API Key → Create API key**
4. Copy key ที่ได้ไว้
5. เปิดโปรแกรม → หน้า **Main** → ใส่ key ในช่อง **Gemini API Keys** → กด บันทึก

---

## เปิดใช้งาน

**ดับเบิลคลิก `START.command` ทุกครั้งที่ต้องการใช้**

> **ครั้งแรก** macOS จะถามความปลอดภัย → คลิกขวา → **Open** → **Open**
> ครั้งถัดไปดับเบิลคลิกได้เลย

โปรแกรมจะ **อัพเดทอัตโนมัติ** ทุกครั้งที่เปิด (ต้องมี internet)

---

## หมายเหตุ

- อย่าปิดหน้าต่าง Terminal ระหว่างใช้งาน — กด `Ctrl+C` เพื่อปิดโปรแกรม
- `vmaster_config.json` และ `token.pickle` เก็บอยู่ในเครื่องเท่านั้น ไม่ได้ sync ขึ้น GitHub
- Google OAuth จะให้ login ครั้งแรกครั้งเดียว หลังจากนั้นจำไว้ให้อัตโนมัติ

---

## ต้องการความช่วยเหลือ

ติดต่อผู้ดูแลโปรแกรม