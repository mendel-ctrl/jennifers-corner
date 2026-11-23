#!/usr/bin/env python3
"""
update_donations.py: add Jennifer's Hospitality Corner gifts from a CMS Cloud export.

HOW TO USE
  1. Export donations from CMS Cloud as a CSV file.
  2. Put the file in the  exports/  folder (this folder is PRIVATE, never uploaded).
  3. Run:   python3 update_donations.py
  4. Review the matching gifts, choose which to add and which are anonymous.

The script:
  * reads the newest CSV in exports/ (or the file you name)
  * finds the amount, donor name, date, note and transaction ID columns
    (and asks you if it can't tell which is which)
  * keeps only gifts whose note/comment mentions Jennifer Hunter, Jenn Hunter,
    Jennifer's Hospitality, Hospitality Corner, or El Etta
  * never adds the same gift twice (it remembers each transaction ID, scrambled)
  * saves ONLY name, amount and date to data/donations.json, never the note.
    Anonymous gifts are saved with no name at all.

Options (optional; mostly used when Claude runs this for you):
  --preview               just show the matches, change nothing
  --accept all|1,3,5      which listed gifts to add (or "none")
  --anonymous 2,4|none    which listed gifts are anonymous
  --amount/--name/--first-name/--last-name/--date/--id "Column Header"   (--id none = file has no ID column)
  --note "Header" (can repeat)       tell it which column is which
Only Python 3 is needed, nothing to install.
"""
import argparse
import csv
import hashlib
import io
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXPORTS = ROOT / "exports"
DATA_FILE = ROOT / "data" / "donations.json"
COLUMN_MEMORY = ROOT / "column-map.json"   # remembers your column choices (headers only, no donor data)

# Phrases that mark a gift for this campaign. Capitals, punctuation and spaces are ignored,
# so "El-Etta", "Eletta", "JENNIFER'S  hospitality" etc. all match.
PHRASES = ["Jennifer Hunter", "Jenn Hunter", "Jennifer's Hospitality", "Hospitality Corner", "El Etta", "Yael Etta", "Jennifer VanLandingham", "Jennifer Vanlandingham Hunter"]


def squash(text):
    """lowercase, keep only letters and numbers: "El-Etta!" -> "eletta" """
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


KEYS = [squash(p) for p in PHRASES]


def mentions_jen(text):
    t = squash(text)
    return any(k in t for k in KEYS) or ("jennifer" in t and "hunter" in t)

# ----------------------------------------------------------------- column detection
# Each field: list of (header words to look for, score). Higher score = better match.
HINTS = {
    "amount": [("donationamount", 10), ("giftamount", 10), ("paymentamount", 9), ("transactionamount", 9),
               ("chargeamount", 8), ("grossamount", 8), ("totalamount", 8), ("amount", 7), ("total", 5),
               ("sum", 3)],
    "name": [("donorname", 10), ("fullname", 9), ("contactname", 8), ("billingname", 8), ("customername", 7),
             ("payername", 7), ("cardholdername", 6), ("nameoncard", 6), ("donor", 6), ("name", 5)],
    "first_name": [("firstname", 10), ("fname", 8), ("givenname", 8), ("first", 5)],
    "last_name": [("lastname", 10), ("lname", 8), ("surname", 8), ("familyname", 8), ("last", 4)],
    "date": [("transactiondate", 10), ("donationdate", 10), ("paymentdate", 10), ("giftdate", 10),
             ("datereceived", 9), ("chargedate", 9), ("datecreated", 8), ("createddate", 8),
             ("date", 7), ("created", 5), ("timestamp", 5)],
    "id": [("transactionid", 10), ("transid", 9), ("transactionnumber", 9), ("paymentid", 9),
           ("donationid", 9), ("chargeid", 8), ("confirmationnumber", 8), ("confirmation", 7),
           ("referencenumber", 7), ("reference", 6), ("orderid", 6), ("receiptnumber", 6), ("id", 4)],
    "note": [("note", 10), ("comment", 10), ("memo", 9), ("message", 8), ("dedication", 8),
             ("inhonor", 7), ("inmemory", 7), ("honor", 7), ("memory", 7), ("tribute", 7), ("designation", 6), ("instructions", 6), ("purpose", 5),
             ("description", 4), ("remark", 6)],
}
# Headers that contain a hint word but are NOT what we want
AVOID = {
    "amount": ["fee", "tax", "deductible", "refund", "net", "recurring", "goal", "discount", "count"],
    "name": ["campaign", "fund", "company", "organization", "org", "event", "product", "file", "user",
             "first", "last", "card", "honoree", "tribute", "solicitor", "page", "memory", "honor"],
    "date": ["update", "modified", "expir", "birth", "refund", "next", "start", "end"],
    "id": ["donor", "contact", "customer", "campaign", "fund", "user", "batch", "account", "page"],
    "first_name": [], "last_name": [],
    "note": ["internal", "staff"],
}
LABELS = {"amount": "gift amount", "name": "donor name", "date": "gift date",
          "id": "transaction ID", "note": "note / comment"}


def header_score(field, header):
    h = squash(header)
    low = header.lower()
    if any(bad.replace(" ", "") in h or bad in low for bad in AVOID[field]):
        return 0
    best = 0
    for word, score in HINTS[field]:
        if h == word:
            best = max(best, score + 2)          # exact header match wins
        elif word in h:
            best = max(best, score)
    return best


def parse_amount(value):
    s = str(value or "").strip()
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")") or s.startswith("-")
    s = re.sub(r"[^0-9.]", "", s)
    if not s or s.count(".") > 1:
        return None
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if neg else n


DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%d-%b-%Y", "%d %b %Y",
                "%b %d %Y", "%B %d %Y", "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d", "%m.%d.%Y"]


def parse_date(value):
    s = str(value or "").strip()
    if not s:
        return None
    s = re.sub(r"T.*$", "", s)                         # 2026-11-23T10:00:00 -> 2026-11-23
    s = re.sub(r"\s+\d{1,2}:\d{2}.*$", "", s)          # drop a time like " 3:15 PM"
    s = s.replace(",", ", ").replace("  ", " ").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s.replace(", ", " ") if "," not in fmt else s, fmt).date()
        except ValueError:
            continue
    return None


def column_fit(field, values):
    """What share of non-empty values look right for this field (0..1)."""
    vals = [v for v in values if str(v).strip()]
    if not vals:
        return 0.0
    if field == "amount":
        ok = sum(1 for v in vals if parse_amount(v) is not None)
    elif field == "date":
        ok = sum(1 for v in vals if parse_date(v) is not None)
    elif field == "id":
        ok = len(set(vals)) if len(set(vals)) == len(vals) else len(set(vals)) * 0.5
    else:
        ok = len(vals)
    return ok / len(vals)


def detect(headers, rows):
    """Return {field: header or None} and a list of fields we're unsure about."""
    sample = rows[:200]
    found, unsure = {}, []
    for field in ["amount", "date", "id", "name", "first_name", "last_name"]:
        scored = []
        for h in headers:
            s = header_score(field, h)
            if s:
                fit = column_fit(field, [r.get(h, "") for r in sample])
                if field in ("amount", "date") and fit < 0.8:
                    continue
                scored.append((s + fit * 3, h))
        scored.sort(reverse=True)
        if not scored:
            found[field] = None
        else:
            found[field] = scored[0][1]
            if len(scored) > 1 and scored[0][0] - scored[1][0] < 1.0 and field not in ("first_name", "last_name"):
                unsure.append(field)
    # Notes: every column that looks like a note or comment gets searched
    found["note"] = [h for h in headers if header_score("note", h) >= 6]
    return found, unsure


def show_headers(headers, rows):
    print("\nColumns in this file (with an example value):")
    for i, h in enumerate(headers, 1):
        ex = next((str(r.get(h, "")).strip() for r in rows if str(r.get(h, "")).strip()), "")
        print(f"  {i:>2}. {h}" + (f"   e.g. {ex[:40]}" if ex else ""))


def ask_column(field, headers, rows, guess=None, allow_none=False, multi=False):
    show_headers(headers, rows)
    label = LABELS[field]
    tip = f" [Enter = {guess}]" if guess else ""
    extra = " (several allowed, like 3,7)" if multi else ""
    extra += " (or 0 if there isn't one)" if allow_none else ""
    while True:
        ans = input(f"\nWhich column is the {label}?{extra}{tip} ").strip()
        if not ans and guess:
            return [guess] if multi else guess
        if allow_none and ans == "0":
            return [] if multi else None
        try:
            picks = [headers[int(x) - 1] for x in re.split(r"[,\s]+", ans) if x]
            if picks and all(picks):
                return picks if multi else picks[0]
        except (ValueError, IndexError):
            pass
        print("  Please type the number from the list.")


# ----------------------------------------------------------------- helpers
def read_csv(path):
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [h for h in (reader.fieldnames or []) if h is not None]
    rows = [r for r in reader if any(str(v or "").strip() for v in r.values())]
    return headers, rows


SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "md", "phd", "esq"}


def tidy_name(name):
    n = re.sub(r"\s+", " ", str(name or "")).strip()
    # "Hunter, Jennifer" -> "Jennifer Hunter"
    if n.count(",") == 1:
        last, first = [p.strip() for p in n.split(",")]
        if first and last and squash(first) not in SUFFIXES:
            n = f"{first} {last}"
    # "Elaine SCHREIBER" -> "Elaine Schreiber" (keep short initials like "AD")
    n = " ".join(w.capitalize() if w.isupper() and len(w) > 2 else w for w in n.split())
    if n.isupper() or n.islower():
        n = " ".join(w.capitalize() if not re.match(r"^(mc|mac)", w.lower()) else w.capitalize() for w in n.split())
    return n


def hashed_id(raw):
    return "t_" + hashlib.sha256(str(raw).strip().encode()).hexdigest()[:16]


def parse_picks(text, count):
    t = (text or "").strip().lower()
    if t in ("", "none", "no", "n", "0"):
        return set()
    if t in ("all", "a", "yes", "y"):
        return set(range(1, count + 1))
    picks = set()
    for part in re.split(r"[,\s]+", t):
        if "-" in part:
            a, b = part.split("-", 1)
            picks.update(range(int(a), int(b) + 1))
        elif part:
            picks.add(int(part))
    bad = [p for p in picks if p < 1 or p > count]
    if bad:
        raise ValueError(f"No gift numbered {bad[0]} in the list (1 to {count}).")
    return picks


BAD_STATUS = ("fail", "declin", "refund", "void", "cancel", "reject", "error", "chargeback", "reversed")


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?", help="CSV file (default: newest .csv in exports/)")
    ap.add_argument("--preview", action="store_true", help="show matches only, change nothing")
    ap.add_argument("--accept", help='which listed gifts to add: "all", "none" or numbers like 1,3,5')
    ap.add_argument("--anonymous", help='which listed gifts are anonymous: numbers like 2,4 or "none"')
    for f in ("amount", "name", "first-name", "last-name", "date", "id"):
        ap.add_argument(f"--{f}", help=f"column header for {f.replace('-', ' ')}")
    ap.add_argument("--note", action="append", help="column header for the note/comment (repeatable)")
    args = ap.parse_args()
    interactive = sys.stdin.isatty() and args.accept is None and not args.preview

    # 1. Find the CSV file
    if args.csv:
        path = Path(args.csv)
    else:
        csvs = sorted(EXPORTS.glob("*.csv"), key=lambda p: p.stat().st_mtime) if EXPORTS.exists() else []
        if not csvs:
            sys.exit("No CSV file found in exports/. Export from CMS Cloud, put the file in exports/, and run again.")
        path = csvs[-1]
    if not path.exists():
        sys.exit(f"Can't find {path}")
    headers, rows = read_csv(path)
    print(f"Reading {path.name}: {len(rows)} rows, {len(headers)} columns.")
    if not rows:
        sys.exit("That file has no rows.")

    # 2. Work out the columns (command-line choices > remembered choices > automatic guess)
    found, unsure = detect(headers, rows)
    memory = json.loads(COLUMN_MEMORY.read_text()) if COLUMN_MEMORY.exists() else {}
    remembered = memory.get("|".join(headers))
    if remembered:
        found.update({k: v for k, v in remembered.items()})
        unsure = []
    given = {"amount": args.amount, "name": args.name, "first_name": args.first_name,
             "last_name": args.last_name, "date": args.date, "id": args.id}
    no_id = (args.id or "").lower() == "none"
    if no_id:
        given["id"] = None
        found["id"] = None
    for k, v in given.items():
        if v:
            if v not in headers:
                sys.exit(f'There is no column called "{v}". Columns are: {", ".join(headers)}')
            found[k] = v
            if k in unsure:
                unsure.remove(k)
    if args.note:
        for v in args.note:
            if v not in headers:
                sys.exit(f'There is no column called "{v}". Columns are: {", ".join(headers)}')
        found["note"] = args.note
    if args.name:
        found["first_name"] = found["last_name"] = None
    elif args.first_name or args.last_name:
        found["name"] = None

    # Prefer a single full-name column; otherwise first + last
    has_name = bool(found.get("name")) or bool(found.get("first_name") or found.get("last_name"))
    if found.get("name") and found.get("first_name") and header_score("name", found["name"]) < 8 and not args.name:
        found["name"] = None

    problems = []
    for field in ("amount", "date", "id"):
        if field == "id" and no_id:
            continue
        if not found.get(field) or field in unsure:
            problems.append(field)
    if not has_name:
        problems.append("name")
    if not found.get("note"):
        problems.append("note")

    if problems:
        if not sys.stdin.isatty():
            show_headers(headers, rows)
            print("\nI couldn't tell for sure which column is the: " + ", ".join(LABELS[p] for p in problems))
            print("Run again naming them, e.g.  --amount \"Amount\" --date \"Date\" --id \"Transaction ID\" "
                  "--name \"Donor Name\" --note \"Comments\"")
            sys.exit(2)
        for field in problems:
            if field == "note":
                found["note"] = ask_column("note", headers, rows, multi=True)
            elif field == "id":
                found["id"] = ask_column("id", headers, rows, guess=found.get("id"), allow_none=True)
            else:
                found[field] = ask_column(field, headers, rows, guess=found.get(field))
                if field == "name":
                    found["first_name"] = found["last_name"] = None

    print("\nUsing these columns:")
    if found.get("name"):
        print(f"  donor name     : {found['name']}")
    else:
        print(f"  donor name     : {found.get('first_name')} + {found.get('last_name')}")
    for f in ("amount", "date", "id"):
        print(f"  {LABELS[f]:<15}: {found.get(f) or '(none: will use name+amount+date instead)'}")
    print(f"  note / comment : {', '.join(found['note'])}")
    if not found.get("id"):
        print("  WARNING: no transaction ID column, so duplicates are spotted by name + amount + date.")

    status_col = next((h for h in headers if squash(h) in ("status", "paymentstatus", "transactionstatus")), None)
    charged_col = next((h for h in headers if squash(h) in ("charged", "paid", "approved")), None)
    anon_col = next((h for h in headers if "anonym" in h.lower()), None)

    # 3. Pick out matching gifts
    data = json.loads(DATA_FILE.read_text()) if DATA_FILE.exists() else {
        "goal": 25000, "donateUrl": "https://www.chabadsp.com/donate", "updatedAt": "", "donations": []}
    existing = {d["id"] for d in data.get("donations", [])}

    def full_name(r):
        if found.get("name"):
            return tidy_name(r.get(found["name"], ""))
        return tidy_name(" ".join(str(r.get(found[k], "") or "").strip()
                                  for k in ("first_name", "last_name") if found.get(k)))

    matches, already, skipped = [], 0, []
    seen = set()
    for r in rows:
        note_text = " ".join(str(r.get(h, "") or "") for h in found["note"])
        if not mentions_jen(note_text):
            continue
        amount = parse_amount(r.get(found["amount"]))
        when = parse_date(r.get(found["date"]))
        name = full_name(r)
        if status_col and any(b in str(r.get(status_col, "")).lower() for b in BAD_STATUS):
            skipped.append(f"{name or '?'} {r.get(found['amount'])}: status is '{r.get(status_col)}'")
            continue
        if charged_col and str(r.get(charged_col, "")).strip().lower() in ("false", "no", "0", "n"):
            skipped.append(f"{name or '?'} {r.get(found['amount'])}: card was not charged")
            continue
        if amount is None or amount <= 0:
            skipped.append(f"{name or '?'}: amount '{r.get(found['amount'])}' isn't a positive number")
            continue
        if when is None:
            skipped.append(f"{name or '?'} ${amount:,.2f}: can't read date '{r.get(found['date'])}'")
            continue
        raw_id = r.get(found["id"]) if found.get("id") else None
        tid = hashed_id(raw_id) if raw_id and str(raw_id).strip() else hashed_id(f"{name}|{amount:.2f}|{when}")
        if tid in existing:
            already += 1
            continue
        if tid in seen:
            continue
        seen.add(tid)
        suggest_anon = (not name) or "anonym" in note_text.lower() or (
            anon_col and str(r.get(anon_col, "")).strip().lower() in ("yes", "y", "true", "1", "x"))
        matches.append({"id": tid, "name": name, "amount": round(amount, 2), "date": when.isoformat(),
                        "note": note_text.strip(), "suggest_anon": bool(suggest_anon)})

    matches.sort(key=lambda m: m["date"])
    print(f"\nFound {len(matches)} new matching gift(s)."
          + (f" {already} already on the page (skipped)." if already else ""))
    for s in skipped:
        print("  Not counted -> " + s)
    if not matches:
        print("Nothing new to add.")
        return

    print("\n  #   Date         Amount       Name                        Note (shown here only, never saved)")
    for i, m in enumerate(matches, 1):
        flag = "  <- maybe anonymous" if m["suggest_anon"] else ""
        note = re.sub(r"\s+", " ", m["note"])[:50]
        print(f"  {i:<3} {m['date']}   ${m['amount']:>10,.2f}  {(m['name'] or '(no name)')[:26]:<26}  {note}{flag}")
    print(f"\n  Total of these: ${sum(m['amount'] for m in matches):,.2f}")

    if args.preview:
        print("\n(Preview only, nothing was saved.)")
        return

    # 4. Confirm which to add and which are anonymous
    suggested = ",".join(str(i) for i, m in enumerate(matches, 1) if m["suggest_anon"]) or "none"
    try:
        if interactive:
            accept = parse_picks(input("\nAdd which gifts? Type all, none, or numbers like 1,3,5 [all]: ") or "all",
                                 len(matches))
            anon = parse_picks(input(f"Which should show as Anonymous? Numbers, or none [{suggested}]: ")
                               or suggested, len(matches))
        else:
            if args.accept is None or args.anonymous is None:
                print("\nNothing saved yet. Run again with --accept (all / numbers) and --anonymous (numbers / none).")
                sys.exit(3)
            accept = parse_picks(args.accept, len(matches))
            anon = parse_picks(args.anonymous, len(matches))
    except ValueError as e:
        sys.exit(f"Sorry, {e}")

    added = []
    for i, m in enumerate(matches, 1):
        if i not in accept:
            continue
        is_anon = i in anon or not m["name"]
        added.append({"id": m["id"], "name": None if is_anon else m["name"],
                      "amount": m["amount"], "date": m["date"], "anonymous": is_anon})
    if not added:
        print("No gifts added.")
        return

    # 5. Save: only id, name, amount, date, anonymous. No notes.
    data.setdefault("donations", []).extend(added)
    data["donations"].sort(key=lambda d: d["date"])
    data["updatedAt"] = date.today().isoformat()
    DATA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    # Remember the column choices for next time (header names only)
    memory["|".join(headers)] = {k: found.get(k) for k in ("amount", "name", "first_name", "last_name",
                                                           "date", "id", "note")}
    COLUMN_MEMORY.write_text(json.dumps(memory, indent=2) + "\n")

    total = sum(d["amount"] for d in data["donations"])
    print(f"\nAdded {len(added)} gift(s) (${sum(d['amount'] for d in added):,.2f}). "
          f"{sum(1 for d in added if d['anonymous'])} anonymous.")
    print(f"New total: ${total:,.2f} from {len(data['donations'])} gifts, goal ${data.get('goal', 25000):,.0f}.")


if __name__ == "__main__":
    main()
