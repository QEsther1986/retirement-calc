# 台東老屋・會員小管家（Member Portal）

手機版優先的單頁式會員入口網站（SPA），放在 LINE 官方帳號圖文選單中開啟。
前端為靜態網頁，後端為 Google 試算表 + Google Apps Script (GAS) Web App。

## 技術棧（零成本、好維護）

| 層級 | 選擇 | 理由 |
|------|------|------|
| 前端 | 單一 `index.html` + Tailwind CSS (CDN) + Vanilla JS | 無建置流程、無 node_modules，改一個檔案就能上線；14–20 個家庭的規模不需要框架 |
| 託管 | GitHub Pages（或 Netlify） | 免費、HTTPS、與此 repo 直接整合 |
| API | Google Apps Script Web App | 免費、直接讀寫 Google 試算表、可呼叫 LINE Messaging API |
| 資料庫 | Google 試算表（已建置） | 管家可直接肉眼對帳、手動修正 |
| 通知 | GAS 時間觸發器 + LINE Messaging API | 對帳開通、入住前一日發送密碼 |

**刻意不用的東西**：React/Vue（規模不需要）、資料庫服務（Sheets 已夠用）、後端伺服器（GAS 免費額度綽綽有餘）。

## 部署步驟

1. 將 GAS 部署為 Web App（執行身分：我、存取權：任何人）。
2. 把部署網址貼進 `index.html` 內的 `CONFIG.API_URL`。
3. `API_URL` 留空時為**展示模式**（假資料），方便先預覽 UI。
4. 把匯款帳戶資訊（銀行、戶名、帳號）改為真實資料（搜尋 `匯款帳戶資訊` 區塊）。
5. 部署到 GitHub Pages，將網址設進 LINE 圖文選單。

## API 規格（前端 ↔ GAS）

### 1. 查詢會員狀態

`GET {API_URL}?action=getMember&phone=0912345678`

回應（對應「創始會員總表」+「訂房與扣款紀錄」分頁）：

```json
{
  "ok": true,
  "member": {
    "memberId": "F-2026-007",
    "name": "陳美惠",
    "status": "已開通",
    "balance": 2200,
    "expiryMonth": "2027-03",
    "records": [
      {
        "checkIn": "2026-08-15",
        "checkOut": "2026-08-17",
        "party": "2大2小",
        "amount": 800,
        "status": "已確認"
      }
    ]
  }
}
```

查無會員時：`{ "ok": false, "message": "查無此會員" }`

### 2. 入會 / 匯款回報

`POST {API_URL}`，**Content-Type 必須是 `text/plain`**（避免 CORS preflight，GAS 不支援 OPTIONS）：

```json
{
  "action": "submitTopup",
  "data": {
    "name": "陳美惠",
    "lineName": "美惠媽咪",
    "phone": "0912345678",
    "last5": "54321",
    "adults": "2 位",
    "kids": "3 位",
    "familyNote": "一家五口，2大3小，1女2男",
    "note": "小孩對花生過敏"
  }
}
```

回應：`{ "ok": true }` — GAS 端將資料寫入「創始會員總表」，會費核對狀態預設「待確認」。

### GAS 端骨架（貼到 Apps Script）

```javascript
const SHEET_ID = '你的試算表 ID';

function doGet(e) {
  if (e.parameter.action === 'getMember') {
    return json(getMember(e.parameter.phone));
  }
  return json({ ok: false, message: 'unknown action' });
}

function doPost(e) {
  const body = JSON.parse(e.postData.contents);
  if (body.action === 'submitTopup') {
    return json(submitTopup(body.data));
  }
  return json({ ok: false, message: 'unknown action' });
}

function json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function getMember(phone) {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const rows = ss.getSheetByName('創始會員總表').getDataRange().getValues();
  // 欄位順序：會員編號/真實姓名/LINE暱稱/聯絡電話/後五碼/核對狀態/餘額/家庭偏好/備註/加入月份/到期月份
  for (let i = 1; i < rows.length; i++) {
    if (String(rows[i][3]) === String(phone)) {
      return { ok: true, member: {
        memberId: rows[i][0], name: rows[i][1], status: rows[i][5],
        balance: Number(rows[i][6]) || 0, expiryMonth: rows[i][10],
        records: getRecords(ss, rows[i][1]),
      }};
    }
  }
  return { ok: false, message: '查無此會員，請確認號碼，或先完成入會匯款回報。' };
}

function getRecords(ss, name) {
  const rows = ss.getSheetByName('訂房與扣款紀錄').getDataRange().getValues();
  // 欄位順序：申請時間/會員姓名/入住日/退房日/房型人數/扣款金額/對帳狀態/密碼派發狀態
  return rows.slice(1)
    .filter(r => r[1] === name)
    .slice(-5)
    .map(r => ({
      checkIn: fmtDate(r[2]), checkOut: fmtDate(r[3]),
      party: r[4], amount: Number(r[5]) || 0, status: r[6],
    }));
}

function submitTopup(d) {
  const sheet = SpreadsheetApp.openById(SHEET_ID).getSheetByName('創始會員總表');
  sheet.appendRow([
    '', d.name, d.lineName, "'" + d.phone, "'" + d.last5,
    '待確認', 0, `${d.adults}大人 ${d.kids}小孩｜${d.familyNote}`, d.note,
    '', '',
  ]);
  return { ok: true };
}

function fmtDate(v) {
  return v instanceof Date
    ? Utilities.formatDate(v, 'Asia/Taipei', 'yyyy-MM-dd') : String(v);
}
```

## 頁面狀態

- ✅ 首頁 / 會員狀態儀表板（登入、會員卡、餘額、效期提醒、近期訂房紀錄）
- ✅ 入會與匯款回報（匯款資訊一鍵複製、回報表單、成功畫面）
- ⏳ 我要訂房（骨架已留，待串接 Google 日曆空房）
- ⏳ 老屋入住指南（骨架已留，待補照片、WiFi、地圖內容）
