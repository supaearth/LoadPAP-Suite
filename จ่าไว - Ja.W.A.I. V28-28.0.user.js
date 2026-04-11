// ==UserScript==
// @name         จ่าไว - Ja.W.A.I. V28
// @namespace    http://tampermonkey.net/
// @version      28.0
// @description  V28: เลื่อนหน้าจอไปโชว์ช่อง Note ให้เห็นกับตาว่าพิมพ์แล้ว ก่อนกดโหลด
// @match        *://*.gettyimages.com/*
// @match        *://gettyimages.com/*
// @grant        window.close
// ==/UserScript==

(function() {
    'use strict';

    if (!window.location.href.toLowerCase().includes('gettyimages')) return;

    // ==========================================
    // ⚙️ ตั้งค่า URL Mimir
    // ==========================================
    const MIMIR_BASE = "https://apac.mjoll.no/?searchString=";
    const MIMIR_TAIL = "%20type%3Avideo,image,audio,file,clipList,timeline&timeZone=Asia%2FBangkok&itemsPerPage=15&from=0&isFuzzy=false&atSameTime=false&defaultDateRangeField=mediaCreatedOn&includeTypeCounts=true&includeDateCounts=true&useCustomSearchHook=false&includeFolders=true&sortProperty=item_created_date&sortOrder=desc&viewType=list&reload=false&tab=metadata";

    // ==========================================
    // 🛠️ 1. สร้าง UI
    // ==========================================
    const container = document.createElement('div');
    container.id = 'project-note-widget';
    const savedPos = JSON.parse(localStorage.getItem('widget_pos') || '{"top":"100px","left":"20px"}');
    let currentMode = localStorage.getItem('jawai_mode') || 'HD';
    let isManualOverride = false;

    container.style = `
        position: fixed; top: ${savedPos.top}; left: ${savedPos.left}; z-index: 2147483647;
        background: #1a1a1a; color: white; padding: 0; border-radius: 12px;
        box-shadow: 0 10px 40px rgba(0,0,0,0.8); border: 2px solid #00B862;
        font-family: 'Segoe UI', Tahoma, sans-serif; min-width: 250px; user-select: none;
    `;

    container.innerHTML = `
        <div id="widget-header" style="padding: 12px; background: #00B862; border-radius: 10px 10px 0 0; cursor: move; display: flex; justify-content: space-between; align-items: center;">
            <span style="font-size: 14px; font-weight: bold; color: #fff;">จ่าไว - JaW.A.I. V28</span>
            <button id="toggle-btn" style="background: none; border: none; color: #fff; cursor: pointer; font-size: 16px; font-weight: bold;">_</button>
        </div>
        <div id="widget-content" style="padding: 15px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; background: #000; padding: 5px 10px; border-radius: 8px; border: 1px solid #333;">
                <span style="font-size: 11px; color: #888;">MODE:</span>
                <div id="mode-display" style="font-weight: bold; color: ${currentMode === 'HD' ? '#00ff88' : '#ffea00'}; font-size: 14px;">${currentMode} MODE</div>
                <button id="mode-toggle-btn" style="background: #333; color: #fff; border: 1px solid #555; border-radius: 4px; padding: 2px 8px; font-size: 10px; cursor: pointer;">[Shift+S]</button>
            </div>

            <div style="margin-bottom: 10px;">
                <select id="widget-p-type" style="width: 100%; background: #000; color: #fff; border: 1px solid #444; border-radius: 5px; padding: 8px; outline: none; font-size: 13px;">
                    <option>Decoding the World</option>
                    <option>Global Focus</option>
                    <option>Key Messages</option>
                    <option>News Digest</option>
                    <option>The World Dialogue</option>
                    <option>Special</option>
                </select>
            </div>
            <div style="margin-bottom: 15px;">
                <input type="text" id="widget-ep-name" placeholder="ระบุตอน / EP..." style="width: 92%; background: #000; color: white; border: 1px solid #444; border-radius: 5px; padding: 8px; outline: none;">
            </div>

            <button id="footagebot-god-btn" style="width: 100%; background: #00B862; color: #fff; border: 2px solid white; border-radius: 50px; padding: 12px; font-size: 14px; font-weight: bold; cursor: pointer; margin-bottom: 8px;">
                🎯 จิ้มโหลด! [Shift+A]
            </button>

            <button id="search-mimir-btn" style="width: 100%; background: #9333EA; color: #fff; border: 2px solid white; border-radius: 50px; padding: 10px; font-size: 13px; font-weight: bold; cursor: pointer; margin-bottom: 8px;">
                🟣 ค้นใน Mimir [Shift+F]
            </button>

            <button id="search-drive-btn" style="width: 100%; background: #1A73E8; color: #fff; border: 2px solid white; border-radius: 50px; padding: 10px; font-size: 13px; font-weight: bold; cursor: pointer;">
                🔍 ค้นใน Drive [Shift+D]
            </button>

            <div style="text-align: center; margin-top: 10px; font-size: 10px; color: #555;">
                ❌ ปิดแท็บ [Shift+C]
            </div>
        </div>
    `;
    document.body.appendChild(container);

    const header = document.getElementById('widget-header');
    const content = document.getElementById('widget-content');
    const toggleBtn = document.getElementById('toggle-btn');
    const modeBtn = document.getElementById('mode-toggle-btn');
    const modeDisplay = document.getElementById('mode-display');
    const typeInput = document.getElementById('widget-p-type');
    const epInput = document.getElementById('widget-ep-name');
    const godBtn = document.getElementById('footagebot-god-btn');
    const driveBtn = document.getElementById('search-drive-btn');
    const mimirBtn = document.getElementById('search-mimir-btn');

    // ==========================================
    // ⚙️ 2. ระบบช่วยเหลือ (Helpers)
    // ==========================================
    const sleep = ms => new Promise(r => setTimeout(r, ms));

    function clearHighlights() {
        const labels = Array.from(document.querySelectorAll('label, div[role="radio"], li[class*="resolution"]'));
        labels.forEach(el => el.style.outline = "none");
    }

    function forceFocusReset() {
        if (document.activeElement) document.activeElement.blur();
        window.focus();
    }

    function setNativeValue(element, value) {
        const valueSetter = Object.getOwnPropertyDescriptor(element, 'value').set;
        const prototype = Object.getPrototypeOf(element);
        const prototypeValueSetter = Object.getOwnPropertyDescriptor(prototype, 'value').set;
        if (valueSetter && valueSetter !== prototypeValueSetter) prototypeValueSetter.call(element, value);
        else valueSetter.call(element, value);
        element.dispatchEvent(new Event('input', { bubbles: true }));
        element.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function findNoteField() {
        let field = document.querySelector('input[placeholder*="note" i], textarea[placeholder*="note" i], input[name*="note" i], textarea[name*="note" i], input[name="releaseRef" i], input[name="projectCode" i]');
        if (field) return field;
        let allTexts = Array.from(document.querySelectorAll('label, span, p'));
        let noteLabel = allTexts.find(el => el.textContent && el.textContent.trim().toLowerCase() === 'notes');
        if (noteLabel) {
            let parent = noteLabel.parentElement;
            for(let i=0; i<4; i++) {
                if(!parent) break;
                let input = parent.querySelector('input[type="text"], textarea');
                if(input) return input;
                parent = parent.parentElement;
            }
        }
        return null;
    }

    async function selectResolution() {
        isManualOverride = false;
        clearHighlights();

        const hdPriorities = [
            { inc: ['1920', 'H.264'], exc: ['WEB'] },
            { inc: ['1080', 'H.264'], exc: ['WEB'] },
            { inc: ['HD', 'H.264'], exc: ['WEB'] },
            { inc: ['HD', 'JPEG'], exc: ['WEB'] },
            { inc: ['HD'], exc: ['WEB', 'PRORES', '4K'] },
            { inc: ['SD'], exc: ['PRORES'] }
        ];
        const fkPriorities = [
            { inc: ['4K', 'H.264'], exc: [] },
            { inc: ['4K'], exc: [] },
            { inc: ['1920', 'H.264'], exc: ['WEB'] }
        ];

        const rules = (currentMode === '4K') ? fkPriorities : hdPriorities;
        const labels = Array.from(document.querySelectorAll('label, div[role="radio"], li[class*="resolution"]'));

        for (let rule of rules) {
            let match = labels.find(el => {
                const text = el.innerText.toUpperCase();
                const hasInc = rule.inc.every(k => text.includes(k));
                const hasExc = rule.exc.some(k => text.includes(k));
                return hasInc && !hasExc && text.length < 80;
            });
            if (match) {
                match.click();
                match.style.outline = "3px solid #00ff88";
                match.style.outlineOffset = "2px";
                setTimeout(forceFocusReset, 100);
                return match.innerText.trim();
            }
        }
        return null;
    }

    // ==========================================
    // 🔄 3. ระบบควบคุม UI
    // ==========================================
    function toggleMode() {
        currentMode = (currentMode === 'HD' ? '4K' : 'HD');
        localStorage.setItem('jawai_mode', currentMode);
        modeDisplay.innerText = `${currentMode} MODE`;
        modeDisplay.style.color = (currentMode === 'HD' ? '#00ff88' : '#ffea00');
        forceFocusReset();
        selectResolution();
    }
    modeBtn.onclick = toggleMode;

    let isDragging = false, offset = { x: 0, y: 0 };
    header.onmousedown = (e) => { isDragging = true; offset.x = e.clientX - container.getBoundingClientRect().left; offset.y = e.clientY - container.getBoundingClientRect().top; };
    document.onmousemove = (e) => { if (!isDragging) return; container.style.left = (e.clientX - offset.x) + 'px'; container.style.top = (e.clientY - offset.y) + 'px'; };
    document.onmouseup = () => { if (isDragging) { isDragging = false; localStorage.setItem('widget_pos', JSON.stringify({ top: container.style.top, left: container.style.left })); } };
    toggleBtn.onclick = () => { content.style.display = (content.style.display === 'none' ? 'block' : 'none'); toggleBtn.innerText = (content.style.display === 'none' ? '□' : '_'); forceFocusReset(); };

    function saveData() { localStorage.setItem('vmaster_p_type', typeInput.value); localStorage.setItem('vmaster_ep_name', epInput.value); }
    typeInput.onchange = saveData; epInput.oninput = saveData;
    epInput.onkeydown = (e) => { if (e.key === 'Enter') { e.preventDefault(); epInput.blur(); forceFocusReset(); selectResolution(); } };
    typeInput.value = localStorage.getItem('vmaster_p_type') || 'Decoding the World';
    epInput.value = localStorage.getItem('vmaster_ep_name') || '';

    // ==========================================
    // 🚀 4. ฟังก์ชันหลัก (Load / Mimir / Drive)
    // ==========================================
    function getID() {
        const urlMatch = window.location.pathname.match(/\/(\d{8,12})/);
        if (urlMatch) return urlMatch[1];
        const el = Array.from(document.querySelectorAll('span, p, div')).find(e => e.innerText.match(/(Creative #|Item ID|Video ID)\s*(\d{8,12})/i));
        return el ? el.innerText.match(/(\d{8,12})/)[1] : "";
    }

    async function runLoad() {
        let text = `${typeInput.value} - ${epInput.value}`.trim();
        if (!epInput.value) { alert("⚠️ ใส่ชื่อตอนก่อนครับ!"); return; }

        if (!isManualOverride) {
            godBtn.innerHTML = '⚙️ คัดกรองออโต้...';
            await selectResolution();
        }

        let field = findNoteField();
        if (field) {
            // 💡 1. สั่งให้เบราว์เซอร์เลื่อนหน้าจอไปที่ช่อง Note แบบนุ่มนวล
            field.scrollIntoView({ behavior: 'smooth', block: 'center' });

            // 2. กรอกข้อความ และทำไฮไลต์ให้เห็นชัดๆ (สีเขียวสว่าง ตัวหนังสือสีดำเข้ม)
            setNativeValue(field, text);
            field.style.transition = 'all 0.3s ease';
            field.style.border = '3px solid #00B862';
            field.style.backgroundColor = '#E8F8F5';
            field.style.color = '#000000';
            field.style.fontWeight = 'bold';

            godBtn.innerHTML = '👀 เช็ก Note (0.8s)...';

            // 💡 3. หยุดโชว์ผลงาน 0.8 วินาที ให้พี่เห็นกับตาว่า "พิมพ์แล้วนะลูกพี่!"
            await sleep(800);

        } else {
            console.log("❌ จ่าไวหาช่อง Notes ไม่เจอ");
        }

        let target = text.toLowerCase().match(/global focus|decoding|dialogue/) ? "world jan-jun 2026" : "feature jan-jun 2026";
        godBtn.innerHTML = '🚀 ลงบอร์ด...';

        let saveBtn = document.querySelector('[data-testid*="save" i]') || Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Save'));
        if (saveBtn) {
            saveBtn.click();
            let board = await sleep(600).then(() => Array.from(document.querySelectorAll('span, li')).find(el => el.innerText.toLowerCase().includes(target)));
            if (board) board.click();
        }

        await sleep(600);
        let dl = Array.from(document.querySelectorAll('button, a')).find(b => b.innerText.includes('DOWNLOAD'));
        if (dl) dl.click();

        forceFocusReset();
        setTimeout(() => { godBtn.innerHTML = '🎯 จิ้มโหลด! [Shift+A]'; }, 2000);
    }

    godBtn.onclick = runLoad;
    mimirBtn.onclick = () => { let id = getID(); if (id) window.open(`${MIMIR_BASE}${id}${MIMIR_TAIL}`, '_blank'); forceFocusReset(); };
    driveBtn.onclick = () => { let id = getID(); if (id) window.open(`https://drive.google.com/drive/search?q=${id}`, '_blank'); forceFocusReset(); };

    // ==========================================
    // ⌨️ 5. ระบบดักฟัง Event
    // ==========================================
    document.addEventListener('click', (e) => {
        if (e.target.closest('label, div[role="radio"], li[class*="resolution"]')) {
            clearHighlights();
            isManualOverride = true;
            setTimeout(forceFocusReset, 100);
        }
    }, true);

    window.addEventListener('keydown', (e) => {
        const activeEl = document.activeElement;
        if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA' || activeEl.isContentEditable)) return;

        if (e.shiftKey) {
            const code = e.code, key = e.key.toUpperCase();
            if (code === 'KeyA' || key === 'A') { e.preventDefault(); e.stopImmediatePropagation(); godBtn.click(); }
            if (code === 'KeyD' || key === 'D') { e.preventDefault(); e.stopImmediatePropagation(); driveBtn.click(); }
            if (code === 'KeyF' || key === 'F') { e.preventDefault(); e.stopImmediatePropagation(); mimirBtn.click(); }
            if (code === 'KeyS' || key === 'S') { e.preventDefault(); e.stopImmediatePropagation(); toggleMode(); }
            if (code === 'KeyC' || key === 'C') { e.preventDefault(); e.stopImmediatePropagation(); window.close(); }
        }
    }, true);

    setTimeout(selectResolution, 2000);
})();