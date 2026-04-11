# LoadPAP Family

**Load Process Automation Pipeline** — ระบบอัตโนมัติสำหรับ workflow การผลิตวิดีโอ

---

## เครื่องมือทั้งหมด

| ชื่อ | หน้าที่ |
|---|---|
| **PyS.A.R.N.** | ดาวน์โหลดฟุตเทจจาก Google Doc สคริปต์ |
| **PyL.A.D.** | ตัดวิดีโออัตโนมัติจาก Google Sheet |
| **PyJ.I.T.** | Log ฟุตเทจด้วย Gemini Vision AI |
| **PyL.I.V.E.** | ดาวน์โหลดฟีดสด |

---

## ติดตั้ง (ครั้งแรกครั้งเดียว)

### 1. ติดตั้ง Python
ดาวน์โหลดที่ [python.org](https://www.python.org/downloads/) → ติดตั้งตามปกติ

### 2. Clone repo นี้
```bash
git clone [repo-url]
cd loadpap
```

### 3. เตรียมไฟล์ config
```bash
cp vmaster_config.template.json vmaster_config.json
```
แล้ววาง `credentials.json` (รับจากผู้ดูแลโปรแกรม) ลงใน folder เดียวกัน

### 4. ดับเบิลคลิก `INSTALL.command`
รอจนเสร็จ (ประมาณ 2-5 นาที)

---

## เปิดใช้งาน

**ดับเบิลคลิก `START.command` ทุกครั้งที่ต้องการใช้**

---

## อัพเดทโปรแกรม

**ดับเบิลคลิก `UPDATE.command`**

หรือรันเองใน Terminal:
```bash
git pull
```

---

## โครงสร้าง Branch

| Branch | ใช้สำหรับ |
|---|---|
| `main` | โค้ดเสถียร สำหรับผู้ใช้งาน |
| `dev` | พัฒนาและทดสอบ feature ใหม่ |

---

## ต้องการความช่วยเหลือ

ติดต่อผู้ดูแลโปรแกรม
