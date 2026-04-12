# LoadPAP Family

**Load Process Automation Pipeline** — ระบบอัตโนมัติสำหรับ workflow การผลิตวิดีโอ

---

## เครื่องมือทั้งหมด

| ชื่อ | หน้าที่ |
|---|---|
| **PyLOAD** | ดาวน์โหลดฟุตเทจจาก Google Doc สคริปต์ |
| **PyRUSH** | ตัดวิดีโออัตโนมัติจาก Google Sheet |
| **PyLOG** | Log ฟุตเทจด้วย Gemini Vision AI |
| **PyLIVE** | ดาวน์โหลดวีดีโอจากไลฟ์สด | อยู่ในขั้นตอนการพัฒนา

---

## ติดตั้ง (ครั้งแรกครั้งเดียว)

### 1. ติดตั้ง Python
ดาวน์โหลดที่ [python.org](https://www.python.org/downloads/) → ติดตั้งตามปกติ

### 2. ดาวน์โหลดโปรแกรม
กดปุ่ม **Code → Download ZIP** แล้วแตกไฟล์ หรือถ้ามี Git:
```bash
git clone https://github.com/supaearth/LoadPAP-Family.git
```

### 3. เตรียมไฟล์ config
- เข้าไปใน folder LoadPAP
- คลิกขวาที่ `vmaster_config.template.json` → **Duplicate**
- เปลี่ยนชื่อเป็น `vmaster_config.json`
- วาง `credentials.json` (รับจากผู้ดูแลโปรแกรม) ลงใน folder เดียวกัน

### 4. รับ Gemini API Key (ของตัวเอง ฟรี)
1. เข้า [aistudio.google.com](https://aistudio.google.com)
2. Sign in ด้วย Google Account
3. กด **Get API Key** → **Create API key**
4. Copy key ที่ได้ไว้ก่อน
5. เปิดโปรแกรมแล้วใส่ key ในหน้า Main → **Gemini API Keys**

### 5. ดับเบิลคลิก `INSTALL.command`
รอจนเสร็จ (ประมาณ 2-5 นาที)

---

## เปิดใช้งาน

**ดับเบิลคลิก `START.command` ทุกครั้งที่ต้องการใช้**

---

## อัพเดทโปรแกรม

**ดับเบิลคลิก `UPDATE.command`**

---

## ต้องการความช่วยเหลือ

ติดต่อผู้ดูแลโปรแกรม