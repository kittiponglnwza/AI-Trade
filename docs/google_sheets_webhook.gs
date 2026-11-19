/**
 * Google Apps Script Web App for MT5 AI Trading Desk (24/7 Live Sync)
 *
 * Setup:
 * 1. Create a new Google Sheet (e.g., "MT5 AI Trade Journal")
 * 2. Extensions -> Apps Script -> paste this entire file -> Save
 * 3. Deploy -> New deployment -> Web app
 *    - Execute as: Me
 *    - Who has access: Anyone
 * 4. Copy the Web App URL (https://script.google.com/macros/s/.../exec)
 *    and paste it into Settings -> Google Sheets 24/7 Sync in the Trading Desk.
 */

var HEADERS = {
  Trades: [
    "id",
    "mt5_deal_ticket",
    "mt5_position_id",
    "symbol",
    "side",
    "volume",
    "entry_price",
    "exit_price",
    "sl",
    "tp",
    "open_time",
    "close_time",
    "gross_profit",
    "commission",
    "swap",
    "net_profit",
    "status",
    "strategy_tag",
    "notes",
    "source"
  ],
  Proposals: [
    "id",
    "created_at",
    "source",
    "symbol",
    "side",
    "entry_price",
    "sl",
    "tp",
    "lots",
    "risk_pct",
    "est_risk_usd",
    "rr_ratio",
    "status",
    "timeframe",
    "rationale",
    "exec_price",
    "exec_comment"
  ],
  WatchdogLogs: [
    "id",
    "created_at",
    "level",
    "category",
    "symbol",
    "message"
  ],
  Stats: [
    "updated_at",
    "total_trades",
    "wins",
    "losses",
    "win_rate_pct",
    "net_profit",
    "profit_factor",
    "expectancy",
    "max_drawdown_usd",
    "max_drawdown_pct"
  ]
};

function ensureSheetTab(ss, name) {
  var sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
  }
  if (sheet.getLastRow() === 0 && HEADERS[name]) {
    sheet.appendRow(HEADERS[name]);
    sheet.setFrozenRows(1);
    sheet.getRange(1, 1, 1, HEADERS[name].length).setFontWeight("bold");
  }
  return sheet;
}

function doPost(e) {
  try {
    var payload = JSON.parse((e && e.postData && e.postData.contents) || "{}");
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var action = payload.action || "append";

    if (action === "ping") {
      ensureSheetTab(ss, "Trades");
      ensureSheetTab(ss, "Proposals");
      ensureSheetTab(ss, "WatchdogLogs");
      ensureSheetTab(ss, "Stats");
      return ContentService.createTextOutput(
        JSON.stringify({ ok: true, spreadsheet: ss.getName(), message: "Connected & initialized tabs" })
      ).setMimeType(ContentService.MimeType.JSON);
    }

    var tabName = payload.sheet || "WatchdogLogs";
    var sheet = ensureSheetTab(ss, tabName);
    var rows = payload.rows || [];

    if (action === "replace" && sheet.getLastRow() > 1) {
      sheet.deleteRows(2, sheet.getLastRow() - 1);
    }

    if (rows.length > 0) {
      var startRow = sheet.getLastRow() + 1;
      sheet.getRange(startRow, 1, rows.length, rows[0].length).setValues(rows);
    }

    return ContentService.createTextOutput(
      JSON.stringify({ ok: true, sheet: tabName, written: rows.length })
    ).setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(
      JSON.stringify({ ok: false, error: String(err) })
    ).setMimeType(ContentService.MimeType.JSON);
  }
}
