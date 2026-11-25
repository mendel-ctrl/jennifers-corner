/**
 * Jennifer's Hospitality Corner: automatic donation tracker
 * ---------------------------------------------------------
 * Lives inside the "Jennifer's Hospitality Corner: Donations" Google Sheet
 * (Extensions > Apps Script). Every 5 minutes it reads new
 * "Form Submission Notification - Donate" emails from CMS Cloud, picks out
 * gifts for Jennifer, and adds them to the "Donations" tab.
 *
 *   Clear gift for Jennifer  -> "Yes"    (shows on the website)
 *   Unclear gift             -> "Review" (you get an email; change it to Yes or No)
 *   Not for Jennifer         -> skipped
 *
 * ONE-TIME SETUP: choose "setup" in the menu at the top and press Run, then allow access.
 * Privacy: only name, amount, date and the note fields are saved. Card numbers,
 * addresses, phone numbers and emails are never written to the sheet.
 */

var CONFIG = {
  sheetName: 'Donations',
  search: 'from:forms_no_reply@chabadms.com subject:"Form Submission Notification - Donate" newer_than:7d',
  timeZone: 'America/New_York',
  // A note that contains any of these (ignoring capitals, spaces and punctuation) is for Jennifer
  phrases: ['Jennifer Hunter', 'Jennifer Nicole Hunter', 'Jenn Hunter', 'Jen Hunter',
            'Jennifer VanLandingham', "Jennifer's Hospitality", 'Hospitality Corner',
            'El Etta', 'Eletta', 'Yael Etta'],
  // A Jennifer gift that mentions any of these goes to Review instead of the website
  reviewWords: ['funeral', 'burial', 'levaya', 'levaye', 'shiva', 'meis mitzvah', 'met mitzvah', 'mes mitzvah']
};

/** Run this once. It creates the 5-minute timer and does a first check. */
function setup() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'checkDonations') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('checkDonations').timeBased().everyMinutes(5).create();
  ensureEmailIdColumn_();
  checkDonations();
  SpreadsheetApp.getActive().toast('Done! New donation emails will be checked every 5 minutes.');
}

/** The main job (runs every 5 minutes). */
function checkDonations() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) return;           // another run is still going
  try {
    var sheet = SpreadsheetApp.getActive().getSheetByName(CONFIG.sheetName);
    ensureEmailIdColumn_();
    var existing = readExisting_(sheet);
    var added = [], review = [];

    GmailApp.search(CONFIG.search, 0, 50).forEach(function (thread) {
      thread.getMessages().forEach(function (msg) {
        var id = msg.getId();
        if (existing.ids[id]) return;                       // already handled
        var gift = parseDonationEmail(msg.getPlainBody());
        if (!gift || !(gift.amount > 0)) return;
        gift.date = Utilities.formatDate(msg.getDate(), CONFIG.timeZone, 'yyyy-MM-dd');
        var decision = decide(gift);
        if (!decision) return;                              // not for Jennifer
        var key = gift.date + '|' + gift.name.toLowerCase() + '|' + gift.amount.toFixed(2);
        if (existing.keys[key]) { existing.ids[id] = true; return; } // added earlier by hand or by Claude

        var row = [gift.date, gift.name, gift.amount, gift.note, '',
                   decision.status, decision.reason, decision.status === 'Yes' ? 'Yes' : 'No', id];
        sheet.appendRow(row);
        existing.ids[id] = true; existing.keys[key] = true;
        (decision.status === 'Yes' ? added : review).push(gift.name + ' $' + gift.amount + ' (' + decision.reason + ')');
      });
    });

    if (review.length) {
      MailApp.sendEmail(Session.getEffectiveUser().getEmail(),
        "Jennifer's Corner: " + review.length + ' gift(s) need your OK',
        'These gifts were added to the sheet as "Review" and are NOT on the website yet:\n\n' +
        review.join('\n') + '\n\nOpen the sheet and change "Counts toward corner" to Yes or No:\n' +
        SpreadsheetApp.getActive().getUrl());
    }
    if (added.length) console.log('Added to website: ' + added.join('; '));
  } finally {
    lock.releaseLock();
  }
}

/* ---------------- helpers (no need to edit) ---------------- */

var LABELS = ['Total Amount', 'Payment Amount', 'Payment Purpose', 'Recurring Period', 'Recurring Number',
  'Contact Title', 'First Name', 'Last Name', 'Contact Address', 'Contact City', 'Contact State',
  'Contact Zip', 'Contact Phone', 'Contact Email', 'Other Comments', 'Other Honor', 'Other Memory',
  'Card Type', 'Card Number', 'Card Exp Month', 'Card Exp Year', 'Name On Card', 'Card Address',
  'Card Zip', 'Client IP', 'Captcha Score'];

/** Reads a CMS Cloud "Donate" email into {name, amount, purpose, comments, honor, memory, note}. */
function parseDonationEmail(body) {
  if (!body || body.indexOf('Donate form') < 0) return null;
  var lines = body.split(/\r?\n/).map(function (l) { return l.trim(); });
  var f = {};
  for (var i = 0; i < lines.length; i++) {
    if (LABELS.indexOf(lines[i]) < 0) continue;
    var j = i + 1;
    while (j < lines.length && lines[j] === '') j++;
    f[lines[i]] = (j < lines.length && LABELS.indexOf(lines[j]) < 0) ? lines[j] : '';
  }
  var amount = parseFloat(String(f['Payment Amount'] || f['Total Amount'] || '').replace(/[^0-9.]/g, ''));
  var name = tidyName_(((f['First Name'] || '') + ' ' + (f['Last Name'] || '')).trim());
  var parts = [];
  if (f['Other Comments']) parts.push(f['Other Comments']);
  if (f['Other Honor']) parts.push('Honor: ' + f['Other Honor']);
  if (f['Other Memory']) parts.push('Memory: ' + f['Other Memory']);
  return { name: name, amount: amount, purpose: f['Payment Purpose'] || '',
           note: parts.join(' | ') };
}

/** Returns {status:'Yes'|'Review', reason} or null if the gift isn't for Jennifer. */
function decide(gift) {
  var flat = squash_(gift.note);
  var forJen = CONFIG.phrases.some(function (p) { return flat.indexOf(squash_(p)) >= 0; }) ||
               (flat.indexOf('jennifer') >= 0 && flat.indexOf('hunter') >= 0);
  var lower = gift.note.toLowerCase();
  var funeral = CONFIG.reviewWords.some(function (w) { return lower.indexOf(w) >= 0; });
  var scrambled = /\?{3,}/.test(gift.note);
  var memorial = /memorial/i.test(gift.purpose);
  if (forJen && !funeral) return { status: 'Yes', reason: 'Mentions Jennifer' };
  if (forJen && funeral) return { status: 'Review', reason: 'Funeral or burial? Check' };
  if (memorial && (scrambled || /jen/i.test(gift.note))) return { status: 'Review', reason: 'Memorial gift, unclear note' };
  return null;
}

function squash_(s) { return String(s || '').toLowerCase().replace(/[^a-z0-9]/g, ''); }

function tidyName_(n) {
  return n.split(/\s+/).map(function (w) {
    return (w.length > 2 && w === w.toUpperCase()) || w === w.toLowerCase()
      ? w.charAt(0).toUpperCase() + w.slice(1).toLowerCase() : w;
  }).join(' ');
}

/** Adds an "Email ID" header in column I (used to never add the same email twice). */
function ensureEmailIdColumn_() {
  var sheet = SpreadsheetApp.getActive().getSheetByName(CONFIG.sheetName);
  if (sheet.getRange('I1').getValue() !== 'Email ID') sheet.getRange('I1').setValue('Email ID');
}

function readExisting_(sheet) {
  var values = sheet.getDataRange().getValues();
  var ids = {}, keys = {};
  for (var r = 1; r < values.length; r++) {
    var v = values[r];
    if (!v[1]) continue;
    var d = v[0] instanceof Date ? Utilities.formatDate(v[0], CONFIG.timeZone, 'yyyy-MM-dd') : String(v[0]);
    var amt = parseFloat(String(v[2]).replace(/[^0-9.]/g, '')) || 0;
    keys[d + '|' + String(v[1]).toLowerCase() + '|' + amt.toFixed(2)] = true;
    if (v[8]) ids[String(v[8])] = true;
  }
  return { ids: ids, keys: keys };
}

// Lets the test file load these functions outside Google (ignored inside Google)
if (typeof module !== 'undefined') module.exports = { parseDonationEmail: parseDonationEmail, decide: decide };
