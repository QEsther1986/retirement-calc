/**
 * 台東老屋・會員小管家 — Google Apps Script 後端
 * 已對齊試算表「老屋專屬數位管家 - 後台資料庫」的實際欄位結構。
 * 使用方式：整份貼到試算表的「擴充功能 → Apps Script」，部署為網頁應用程式。
 */

const SHEET_ID = '1fLMEEOuqD9xsCVAWC6XDHVEXv7FM1-supUbjIkEzKTI'; // 老屋專屬數位管家 - 後台資料庫

// 空房管理日曆：留空字串 = 使用您 Google 帳號的預設日曆（零設定）。
// 若之後建立專用日曆，把日曆 ID 貼進來即可。
const CALENDAR_ID = '';

/* ═══════════ 路由 ═══════════ */

function doGet(e) {
  try {
    if (e.parameter.action === 'getMember')       return json(getMember(e.parameter.phone));
    if (e.parameter.action === 'getAvailability') return json(getAvailability(e.parameter.from, e.parameter.to));
    return json({ ok: false, message: 'unknown action' });
  } catch (err) {
    return json({ ok: false, message: '系統錯誤：' + err.message });
  }
}

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    if (body.action === 'submitTopup')   return json(submitTopup(body.data));
    if (body.action === 'submitBooking') return json(submitBooking(body.data));
    return json({ ok: false, message: 'unknown action' });
  } catch (err) {
    return json({ ok: false, message: '系統錯誤：' + err.message });
  }
}

function json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/* ═══════════ 工具 ═══════════ */

// 用第一格標題找分頁，不怕分頁改名或順序調動
function findSheet(headerA1) {
  const sheets = SpreadsheetApp.openById(SHEET_ID).getSheets();
  for (const s of sheets) {
    if (String(s.getRange(1, 1).getValue()).trim() === headerA1) return s;
  }
  throw new Error('找不到標題為「' + headerA1 + '」的分頁');
}
const memberSheet  = () => findSheet('會員編號');
const bookingSheet = () => findSheet('申請時間');

// 電話正規化：只留數字，0980-123456 與 0980123456 視為相同
const digits = v => String(v).replace(/\D/g, '');

function fmtDate(v) {
  return v instanceof Date
    ? Utilities.formatDate(v, 'Asia/Taipei', 'yyyy-MM-dd') : String(v);
}

function fmtMonth(v) {
  return v instanceof Date
    ? Utilities.formatDate(v, 'Asia/Taipei', 'yyyy-MM') : String(v);
}

function calendar() {
  return CALENDAR_ID
    ? CalendarApp.getCalendarById(CALENDAR_ID)
    : CalendarApp.getDefaultCalendar();
}

/* ═══════════ 會員查詢 ═══════════ */
// 會員總表欄位（A~K）：
// 會員編號/真實姓名/LINE暱稱/聯絡電話/匯款帳號後五碼/會費核對狀態/儲值餘額/家庭人數與房型偏好/特殊備註/加入月份/到期月份

function getMember(phone) {
  const rows = memberSheet().getDataRange().getValues();
  const target = digits(phone);
  if (!target) return { ok: false, message: '請提供手機號碼' };

  for (let i = 1; i < rows.length; i++) {
    if (digits(rows[i][3]) === target) {
      return { ok: true, member: {
        memberId:    String(rows[i][0]),
        name:        String(rows[i][1]),
        status:      String(rows[i][5]) || '待確認',
        balance:     Number(rows[i][6]) || 0,
        expiryMonth: fmtMonth(rows[i][10]),
        records:     getRecords(String(rows[i][1])),
      }};
    }
  }
  return { ok: false, message: '查無此會員，請確認號碼，或先完成入會匯款回報。' };
}

// 訂房紀錄欄位（A~J）：
// 申請時間/預約會員姓名/預計入住日期/預計退房日期/訂購房型/人數(幾位大人)/人數(幾位小孩)/本次扣款金額/對帳與確認狀態/密碼派發狀態

function getRecords(name) {
  const rows = bookingSheet().getDataRange().getValues();
  return rows.slice(1)
    .filter(r => String(r[1]).trim() === name.trim())
    .slice(-5)                                   // 最近 5 筆
    .map(r => ({
      checkIn:  fmtDate(r[2]),
      checkOut: fmtDate(r[3]),
      party:    `${r[4]}・${r[5]}大${r[6]}小`,
      amount:   Number(r[7]) || 0,
      status:   String(r[8]) || '待確認',
    }));
}

/* ═══════════ 空房查詢（Google 日曆） ═══════════ */

function getAvailability(from, to) {
  const events = calendar().getEvents(new Date(from), new Date(to + 'T23:59:59'));
  const booked = {};
  events.forEach(ev => {
    // 只看標題含【訂房】的事件，避免您日曆上的私人行程被誤判成客滿
    if (ev.getTitle().indexOf('【訂房】') === -1) return;
    // 事件每跨一晚就標成已滿；退房日早上不佔房
    for (let d = new Date(ev.getStartTime()); d < ev.getEndTime(); d.setDate(d.getDate() + 1)) {
      booked[Utilities.formatDate(d, 'Asia/Taipei', 'yyyy-MM-dd')] = true;
    }
  });
  return { ok: true, booked: Object.keys(booked).sort() };
}

/* ═══════════ 送出訂房 ═══════════ */

function submitBooking(d) {
  bookingSheet().appendRow([
    new Date(),                       // 申請時間
    d.name,                           // 預約會員姓名
    d.checkIn,                        // 預計入住日期
    d.checkOut,                       // 預計退房日期
    d.roomType,                       // 訂購房型
    Number(d.adults) || 0,            // 人數(幾位大人)
    Number(d.kids) || 0,              // 人數(幾位小孩)
    Number(d.amount) || 0,            // 本次扣款金額
    '待確認',                          // 對帳與確認狀態
    '未派發',                          // 密碼派發狀態
  ]);
  calendar().createAllDayEvent(
    `【訂房】${d.name} ${d.roomType} ${d.party}`,
    new Date(d.checkIn), new Date(d.checkOut)
  );
  return { ok: true };
}

/* ═══════════ 入會 / 匯款回報 ═══════════ */

function submitTopup(d) {
  const sheet = memberSheet();
  const rows = sheet.getDataRange().getValues();

  // 同一支手機已存在 → 視為續約/補繳回報，不重複建檔
  for (let i = 1; i < rows.length; i++) {
    if (digits(rows[i][3]) === digits(d.phone)) {
      sheet.getRange(i + 1, 9).setValue(
        (rows[i][8] ? rows[i][8] + '\n' : '') +
        `[${Utilities.formatDate(new Date(), 'Asia/Taipei', 'MM/dd')} 匯款回報] 後五碼 ${d.last5}｜${d.note || ''}`
      );
      return { ok: true };
    }
  }

  // 新會員：自動編號 M001, M002, ...
  const nextId = 'M' + String(rows.length).padStart(3, '0');
  const now = new Date();
  const expiry = new Date(now); expiry.setFullYear(expiry.getFullYear() + 1);

  sheet.appendRow([
    nextId,
    d.name,
    d.lineName,
    "'" + d.phone,                    // 前置 ' 保住開頭的 0
    "'" + d.last5,
    '待確認',
    0,                                // 對帳開通後由管家改為 3000
    `${d.adults}大 ${d.kids}小${d.familyNote ? '（' + d.familyNote + '）' : ''}`,
    d.note || '',
    Utilities.formatDate(now, 'Asia/Taipei', 'yyyy-MM'),
    Utilities.formatDate(expiry, 'Asia/Taipei', 'yyyy-MM'),
  ]);
  return { ok: true };
}
