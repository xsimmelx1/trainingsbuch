"""Planer fürs Trainingsbuch.

Läuft per GitHub Action. Liest Google- und Uni-Kalender (ICS-Adressen aus Secrets),
legt die nächsten Krafteinheiten in freie Slots, schreibt data/plan.json,
aktualisiert den Kalender-Feed (geheimer Gist) und schickt Push-Erinnerungen.
Gibt bewusst keine Kalender- oder Gesundheitsdaten ins Log aus.
"""
import datetime as dt
import json
import os
import sys
import urllib.request
import zoneinfo

TZ = zoneinfo.ZoneInfo("Europe/Berlin")
ROOT = os.environ.get("DATA_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SITE = "https://xsimmelx1.github.io/trainingsbuch/"

SEQ = ["beineA", "okA", "beineB", "okB"]
BASE = {"beineAk": "beineA", "beineBk": "beineB", "okBhome": "okB"}
TITLE = {"beineA": "Beine A", "okA": "Oberkörper A", "beineB": "Beine B", "okB": "Oberkörper B",
         "notfall": "Notfall-Ganzkörper", "reduziert": "Ganzkörper (reduziert)", "beineAk": "Beine A (Knie-Phase 1)", "beineBk": "Beine B (Knie-Phase 1)"}
# Öffentlicher Kalender-Feed: neutrale Namen ohne Reha- oder Stress-Status
PUBLIC_TITLE = {"beineA": "Beine A", "okA": "Oberkörper A", "beineB": "Beine B", "okB": "Oberkörper B", "beineAk": "Beine A", "beineBk": "Beine B",
                "notfall": "Kurz-Einheit", "reduziert": "Ganzkörper", "okBhome": "Oberkörper B"}
EXERCISES = {
    "beineA": ["Beinpresse/Hack Squat", "Rumänisches Kreuzheben", "Beinstrecker", "Sitzender Beinbeuger", "Wadenheben stehend", "Dead Bug"],
    "okA": ["Brustgestütztes Rudern", "KH-Schrägbank Neutralgriff", "Latzug Neutralgriff", "Kabel-Seitheben", "Face Pull", "Kabel-Shrug 30°", "Bayesian Curl", "Trizeps-Pushdown"],
    "beineB": ["Hip Thrust", "Bulgarian Split Squat", "Liegender Beinbeuger", "Hüftabduktion", "Step-Downs", "Wadenheben sitzend", "Pallof Press"],
    "okB": ["Klimmzug Neutralgriff", "Kabelrudern", "Brustpresse", "Landmine Press", "KH-Seitheben", "Reverse Fly", "Serratus Punch", "Schrägbank-Curl", "Skull Crusher", "Ab-Roller kurz"],
    "notfall": ["Bulgarian Split Squat", "Rumänisches Kreuzheben", "Latzug", "Brustpresse", "Seitheben"],
    "reduziert": ["Beinpresse", "Rumänisches Kreuzheben", "Latzug Neutralgriff", "Brustgestütztes Rudern", "Brustpresse", "Kabel-Seitheben", "Kabel-Shrug 30°"],
}
EXERCISES["beineAk"] = ["Wandsitz 60°", "Beinstrecker 90→45°", "Beinpresse 0→60°", "Rumänisches Kreuzheben", "Hüftabduktion", "Wadenheben stehend", "Seitstütz"]
EXERCISES["beineBk"] = ["Wandsitz 60°", "Beinstrecker 90→45°", "Beinpresse 0→60°", "Hip Thrust", "Hüftabduktion", "Liegender Beinbeuger", "Wadenheben sitzend", "Seitstütz"]

# Coaching im Morgen-Push: Fokus der Etappe und Lektion der Woche (wie in der App)
FOCUS = {"w0": "Woche 0: Ausgangswerte sammeln.", "einstieg": "Fokus: Technik und RIR 3.", "aufbau": "Fokus: ↑-Vorschläge umsetzen, RIR 2→1.",
         "deload1": "Deload: halbe Sätze, locker, Re-Test.", "block2": "Fokus: mehr Volumen, RIR 2→1.", "deload2": "Deload und Abschlusstest."}
PHASE_RANGES = [("w0", 0, 0), ("einstieg", 1, 2), ("aufbau", 3, 5), ("deload1", 6, 6), ("block2", 7, 11), ("deload2", 12, 12)]
LESSON_TITLES = {0: "Warum zuerst messen?", 1: "RIR: Wie hart ist hart genug?", 2: "Doppelte Progression", 3: "Hängende Schultern verstehen",
                 4: "Beckenkipp: was normal ist", 5: "Dein Knie: Belastung steuern", 6: "Deload: Pause, die stärker macht",
                 7: "Schlüsselbein: Teil-Schonung statt Pause", 8: "Protein vegetarisch, ohne Pulver", 9: "Schlaf und Stress",
                 10: "Nie zweimal auslassen", 11: "Bouldern und Krafttraining", 12: "Wie geht es nach Woche 12 weiter?"}


def coaching(settings, d):
    w = week_no(settings, d)
    c = 0 if w <= 0 else ((w - 1) % 12) + 1
    pid = next((p for p, a, b in PHASE_RANGES if a <= c <= b), "w0")
    tip = FOCUS[pid]
    if not (settings.get("lessons") or {}).get(f"l{c}"):
        tip += f" Lektion der Woche: {LESSON_TITLES[c]}"
    return tip


TRAIN_MIN = 75         # Dauer einer Einheit inkl. Aufwärmen
SHORT_MIN = 35          # Notfall-Kurzeinheit
BUFFER = 20             # Puffer vor/nach Terminen (Weg zum Gym)
# Bevorzugte Fenster: abends, mittags, spätabends, morgens, sonst irgendwann tagsüber
WINDOWS = [(17, 0, 20, 45), (12, 0, 14, 30), (19, 0, 21, 15), (7, 0, 9, 30), (9, 30, 17, 0)]
HORIZON = 14


def load(name, default):
    p = os.path.join(DATA, name)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(name, obj):
    p = os.path.join(DATA, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def load_days():
    days = {}
    d = os.path.join(DATA, "days")
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".json"):
                days.update(load(os.path.join("days", fn), {}))
    return days


def num(v):
    """Wie num() in der App: Zahl oder None."""
    try:
        x = float(str(v).strip().replace(",", "."))
        return x if x == x and abs(x) != float("inf") else None
    except (TypeError, ValueError):
        return None


def logged_sets(day):
    n = 0
    for sets in (day.get("sets") or {}).values():
        for s in sets or []:
            if s and (num(s.get("reps")) is not None or num(s.get("kg")) is not None):  # wie loggedSets() in der App
                n += 1
    return n


def is_strength(day):
    return bool(day) and logged_sets(day) >= 3 and bool(day.get("session")) and day.get("session") != "frei"


def has_pain_log(day):
    p = (day or {}).get("pain") or {}
    return p.get("sc") is not None or p.get("knee") is not None


# ---------- Kalender ----------
def fetch_busy(start, end):
    """Belegte Zeiten aus allen Kalender-URLs (Secrets GCAL_ICS_URL, UNI_ICS_URL; mehrere per Komma)."""
    import icalendar
    import recurring_ical_events
    urls = []
    for key in ("GCAL_ICS_URL", "UNI_ICS_URL"):
        urls += [(u.strip().replace("webcal://", "https://", 1), "uni" if key == "UNI_ICS_URL" else "privat") for u in os.environ.get(key, "").split(",") if u.strip()]
    busy, ok = [], 0
    for url, src in urls:
        mine = []
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "trainingsbuch-planner"})
            with urllib.request.urlopen(req, timeout=30) as r:
                cal = icalendar.Calendar.from_ical(r.read())
            for ev in recurring_ical_events.of(cal).between(start, end):
                if str(ev.get("TRANSP", "OPAQUE")).upper() == "TRANSPARENT":
                    continue
                if str(ev.get("STATUS", "")).upper() == "CANCELLED":
                    continue
                s, e = ev.get("DTSTART").dt, ev.get("DTEND").dt if ev.get("DTEND") else None
                if isinstance(s, dt.datetime):
                    s = s.astimezone(TZ) if s.tzinfo else s.replace(tzinfo=TZ)
                    e = (e.astimezone(TZ) if e.tzinfo else e.replace(tzinfo=TZ)) if isinstance(e, dt.datetime) else s + dt.timedelta(hours=1)
                else:  # ganztägig und als "beschäftigt" markiert
                    s = dt.datetime.combine(s, dt.time(0), TZ)
                    e = dt.datetime.combine(e if e else s.date() + dt.timedelta(days=1), dt.time(0), TZ)
                mine.append((s, e))
            busy.extend(mine)
            ok += 1
        except Exception as ex:  # nur Typ ausgeben, keine URL/Inhalte
            print(f"Kalender {src} nicht lesbar: {type(ex).__name__}")
    print(f"Kalender gelesen: {ok}/{len(urls)}")
    return busy, ok, len(urls)


def find_slot(day, busy, minutes, not_before):
    for (h1, m1, h2, m2) in WINDOWS:
        t = dt.datetime.combine(day, dt.time(h1, m1), TZ)
        stop = dt.datetime.combine(day, dt.time(h2, m2), TZ)
        while t + dt.timedelta(minutes=minutes) <= stop:
            if t >= not_before:
                a, b = t - dt.timedelta(minutes=BUFFER), t + dt.timedelta(minutes=minutes + BUFFER)
                if not any(s < b and e > a for s, e in busy):
                    return t, t + dt.timedelta(minutes=minutes)
            t += dt.timedelta(minutes=15)
    return None


# ---------- Planung ----------
def week_no(settings, d):
    st = settings.get("startDate")
    if not st:
        return 0
    st = dt.date.fromisoformat(st)
    mon = lambda x: x - dt.timedelta(days=x.weekday())
    diff = (mon(d) - mon(st)).days
    return 0 if diff < 0 else diff // 7 + 1


def variant(base, settings, d):
    if settings.get("mode") == "notfall":
        return "notfall"
    if settings.get("mode") == "reduziert":
        return "reduziert"
    if settings.get("knee1"):
        return {"beineA": "beineAk", "beineB": "beineBk"}.get(base, base)
    return base


def build_plan(now, settings, days, busy, keep=None):
    today = now.date()
    start = today
    st = settings.get("startDate")
    if st and dt.date.fromisoformat(st) > start:
        start = dt.date.fromisoformat(st)
    if (is_strength(days.get(today.isoformat())) or keep) and start == today:
        start = today + dt.timedelta(days=1)
    # nächste Einheit = die nach der letzten erledigten
    nxt = 0
    for k in sorted(days, reverse=True):
        if k < start.isoformat() and is_strength(days[k]):
            b = BASE.get(days[k].get("session"), days[k].get("session"))
            if b in SEQ:
                nxt = (SEQ.index(b) + 1) % 4
                break
    max_week = {"normal": 4, "reduziert": 2, "notfall": 2}.get(settings.get("mode", "normal"), 4)
    count, consec = {}, 0
    # bereits erledigte Einheiten dieser Woche und die Serie bis gestern mitzählen
    for i in range(1, 8):
        d = start - dt.timedelta(days=i)
        if d.isocalendar()[:2] == start.isocalendar()[:2] and is_strength(days.get(d.isoformat())):
            count[d.isocalendar()[:2]] = count.get(d.isocalendar()[:2], 0) + 1
    d = start - dt.timedelta(days=1)
    while is_strength(days.get(d.isoformat())) or (keep and d == today):
        consec += 1
        d -= dt.timedelta(days=1)
    if keep and not is_strength(days.get(today.isoformat())):
        b = BASE.get(keep["session"], keep["session"])
        if b in SEQ:
            nxt = (SEQ.index(b) + 1) % 4
        wk = today.isocalendar()[:2]
        if wk == start.isocalendar()[:2]:
            count[wk] = count.get(wk, 0) + 1
    plan = []
    for i in range(HORIZON):
        d = start + dt.timedelta(days=i)
        wk = d.isocalendar()[:2]
        if d.weekday() == 6 or consec >= 2 or count.get(wk, 0) >= max_week:
            consec = 0
            continue
        prev = days.get((d - dt.timedelta(days=1)).isoformat()) or {}
        if (prev.get("boulder") or {}).get("done") and SEQ[nxt] in ("okA", "okB"):
            continue  # Tag nach dem Bouldern: kein schweres Zugtraining
        not_before = now + dt.timedelta(minutes=30) if d == today else dt.datetime.combine(d, dt.time(0), TZ)
        slot = find_slot(d, busy, TRAIN_MIN, not_before)
        short = False
        if not slot:
            slot = find_slot(d, busy, SHORT_MIN, not_before)
            short = bool(slot)
        if not slot:
            consec = 0
            continue
        base = SEQ[nxt]
        plan.append({"date": d.isoformat(), "session": "notfall" if short else base,
                     "start": slot[0].strftime("%H:%M"), "end": slot[1].strftime("%H:%M"), "short": short})
        nxt = (nxt + 1) % 4
        consec += 1
        count[wk] = count.get(wk, 0) + 1
    # Sonntag: Check-in & Meal Prep (2 h), wenn möglich
    extras = []
    for i in range(HORIZON):
        d = today + dt.timedelta(days=i)
        if d.weekday() == 6:
            nb = now + dt.timedelta(minutes=30) if d == today else dt.datetime.combine(d, dt.time(0), TZ)
            sl = find_slot(d, busy, 120, nb) or (dt.datetime.combine(d, dt.time(17), TZ), dt.datetime.combine(d, dt.time(19), TZ))
            extras.append({"date": d.isoformat(), "kind": "checkin", "start": sl[0].strftime("%H:%M"), "end": sl[1].strftime("%H:%M")})
    return plan, extras


# ---------- Kalender-Feed ----------
def ics_escape(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    out, b = [], line.encode("utf-8")
    while len(b) > 74:
        cut = 74
        while (b[cut] & 0xC0) == 0x80:
            cut -= 1
        out.append(b[:cut].decode("utf-8"))
        b = b" " + b[cut:]
    out.append(b.decode("utf-8"))
    return "\r\n".join(out)


def utc(d, hm):
    h, m = map(int, hm.split(":"))
    return dt.datetime.combine(d, dt.time(h, m), TZ).astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(now, settings, plan, extras, past):
    stamp = now.strftime("%Y%m%dT000000Z")  # tagesgenau, damit der Feed nur bei echten Änderungen neu committet wird
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//trainingsbuch//planner//DE", "CALSCALE:GREGORIAN",
         "METHOD:PUBLISH", "X-WR-CALNAME:Trainingsbuch", "X-WR-TIMEZONE:Europe/Berlin",
         "REFRESH-INTERVAL;VALUE=DURATION:PT2H", "X-PUBLISHED-TTL:PT2H"]

    def ev(uid, summary, desc, url, start=None, end=None, allday=None, alarm=None):
        L.append("BEGIN:VEVENT")
        L.append(f"UID:{uid}@tb2.trainingsbuch")
        L.append(f"DTSTAMP:{stamp}")
        if allday:
            L.append(f"DTSTART;VALUE=DATE:{allday[0].strftime('%Y%m%d')}")
            L.append(f"DTEND;VALUE=DATE:{allday[1].strftime('%Y%m%d')}")
            L.append("TRANSP:TRANSPARENT")
        else:
            L.append(f"DTSTART:{start}")
            L.append(f"DTEND:{end}")
        L.append(fold("SUMMARY:" + ics_escape(summary)))
        L.append(fold("DESCRIPTION:" + ics_escape("In der App öffnen: " + url + "\n\n" + desc)))
        L.append(fold("URL:" + url))
        if alarm:
            L.extend(["BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:-PT{alarm}M", "DESCRIPTION:" + ics_escape(summary), "END:VALARM"])
        L.append("END:VEVENT")

    for p in past + plan:
        d = dt.date.fromisoformat(p["date"])
        s = variant(p["session"], settings, d) if p["session"] != "notfall" else "notfall"
        title = PUBLIC_TITLE.get(s, s)
        desc = ("Nur ein kurzer Slot frei: 30-Minuten-Einheit.\n" if p.get("short") else "") + "Übungen und Sätze stehen in der App."
        past_day = d < now.date()
        ev(f"train-{p['date']}", f"Training: {title}", desc, f"{SITE}#w={p['date']}",
           utc(d, p["start"]), utc(d, p["end"]), alarm=None if past_day else 30)
    today = now.date()
    for i in range(HORIZON):
        d = today + dt.timedelta(days=i)
        ev(f"morning-{d}", "Morgenroutine 7 min", "Routine in der App abhaken und Schlaf eintragen (Gewicht nur am Gym-Wiegetag).",
           f"{SITE}#m={d}", utc(d, "07:30"), utc(d, "07:40"), alarm=0)
        ev(f"pain-{d}", "Abendcheck (30 s)", "Kurzer Abendcheck in der App.", f"{SITE}#p={d}", utc(d, "21:45"), utc(d, "21:50"), alarm=0)
    for x in extras:
        d = dt.date.fromisoformat(x["date"])
        ev(f"checkin-{x['date']}", "Check-in & Meal Prep", "Wochen-Check-in in der App, danach Meal Prep (2 Töpfe, 1 Blech, 3 Gläser).",
           f"{SITE}#c={(d - dt.timedelta(days=d.weekday())).isoformat()}", utc(d, x["start"]), utc(d, x["end"]), alarm=15)
    st = settings.get("startDate")
    if st:
        s0 = dt.date.fromisoformat(st)
        cyc = max(0, (today - s0).days // 84)
        s0 = s0 + dt.timedelta(days=84 * cyc)
        for name, off, length in [("Messtag Woche 0: Fotos, Umfänge, Tests", -1, 1), ("Deload-Woche (Sätze halbieren, RIR 3–4)", 35, 7),
                                  ("Messtag: Fotos, Umfänge, Re-Test", 41, 1), ("Deload-Woche (Sätze halbieren, RIR 3–4)", 77, 7),
                                  ("Messtag: Fotos, Umfänge, Re-Test", 83, 1)]:
            a = s0 + dt.timedelta(days=off)
            if cyc and off < 0:
                continue
            if a + dt.timedelta(days=length) >= today - dt.timedelta(days=7):
                ev(f"marker-{a}-{length}", name, "Siehe Plan & Regeln in der App.", f"{SITE}#t=messen" if length == 1 else SITE,
                   allday=(a, a + dt.timedelta(days=length)))
    L.append("END:VCALENDAR")
    return "\r\n".join(L) + "\r\n"


# ---------- Essensplan ----------
SITE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


ALLERGENS = {"nuesse": "walnu|cashew|haselnu|mandel|pistazie|nüsse|nusskern", "erdnuss": "erdnuss", "soja": "soja|tofu|edamame|tempeh",
             "ei": r"\beier?\b|eiklar|rührei|ei-", "milch": "milch|skyr|quark|käse|joghurt|sahne|butter|feta|harzer|mozzarella",
             "gluten": "weizen|mehl|nudel|pasta|spaghetti|brot|couscous|tortilla|wrap|hafer|knäcke|bulgur|biskuit|dürüm", "sesam": "sesam|tahin", "senf": "senf"}


def avoid_re(settings):
    import re
    f = settings.get("food") or {}
    parts = [ALLERGENS[k] for k in f.get("allergens") or [] if k in ALLERGENS]
    for w in re.split(r"[,;\n]", f.get("avoid") or ""):
        w = w.strip().lower()
        if len(w) < 3:
            continue
        for suf in ("en", "n", "e", "s"):  # nur Pluralendungen, und nur wenn genug übrig bleibt
            if w.endswith(suf) and len(w) - len(suf) >= 4:
                w = w[:-len(suf)]
                break
        w = re.escape(w)
        for x, y in (("[aä]", "[aä]"), ("[oö]", "[oö]"), ("[uü]", "[uü]")):
            w = re.sub(x, y, w)
        parts.append(w)
    return re.compile("|".join(parts), re.I) if parts else None


def substitute(mp, rec, o, rx):
    """Gemiedene Gerichte durch das ähnlichste erlaubte derselben Mahlzeit ersetzen (wie altMeals in der App)."""
    if not rx:
        return o
    text = lambda r: (r["name"] + " " + " ".join(r.get("ingredients", []))).lower()
    slots = {s["k"]: s for s in mp["slots"]}
    for k, n in list(o.items()):
        r = rec.get(n)
        if not r or not rx.search(text(r)):
            continue
        minp = 13 if k in ("sn", "ex") else 25
        cands = [x for x in rec.values() if x["category"] in slots[k]["cats"] and x["name"] != n and x["protein"] >= minp and not rx.search(text(x))]
        cands.sort(key=lambda x: abs(x["kcal"] - r["kcal"]) / 8 + abs(x["protein"] - r["protein"]))
        if cands:
            o[k] = cands[0]["name"]
    return o


def meal_defaults(mp, settings, d, train):
    w = week_no(settings, d)
    W = mp["weeks"][(w - 1) % len(mp["weeks"]) if w > 0 else len(mp["weeks"]) - 1]
    i = d.weekday()
    o = {"fr": W["fr"][i]}
    if i <= 3:
        o["mi"], o["ab"] = (W["batchA"], W["batchB"]) if i % 2 == 0 else (W["batchB"], W["batchA"])
    elif i == 4:
        o["mi"], o["ab"] = W["frMittag"], W["frAbend"]
    elif i == 5:
        o["mi"], o["ab"] = W["frAbend"], W["saAbend"]
    else:
        o["mi"], o["ab"] = W["saAbend"], W["soAbend"]
    o["sn"] = mp["trainingSnack"] if train else mp["snacks"][i]
    if not train:
        o["ex"] = mp["restExtra"][i % 2]
    return o


def build_meal_ics(now, settings, plan, days):
    with open(os.path.join(SITE_ROOT, "mealplan.json"), encoding="utf-8") as f:
        mp = json.load(f)
    with open(os.path.join(SITE_ROOT, "recipes.json"), encoding="utf-8") as f:
        rec = {r["name"]: r for r in json.load(f)}
    by_date = {p["date"]: p for p in plan}
    rx = avoid_re(settings)
    stamp = now.strftime("%Y%m%dT000000Z")
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//trainingsbuch//essen//DE", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
         "X-WR-CALNAME:Trainingsbuch Essen", "X-WR-TIMEZONE:Europe/Berlin", "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]
    for n in range(HORIZON):
        d = now.date() + dt.timedelta(days=n)
        iso = d.isoformat()
        day = days.get(iso) or {}
        pl = by_date.get(iso)
        train = is_strength(day) or bool(pl) or bool((day.get("boulder") or {}).get("done"))
        names = substitute(mp, rec, meal_defaults(mp, settings, d, train), rx)
        names.update({k: v for k, v in (day.get("meals") or {}).items() if v})
        times = (settings.get("food") or {}).get("times") or {}
        for slot in mp["slots"]:
            k, name = slot["k"], names.get(slot["k"])
            t = times.get(k) or slot["time"]
            if pl and pl.get("end") and k == "sn":
                t = pl["end"]
            elif pl and pl.get("end") and k == "ab" and pl["end"] > "18:15":
                h, m = map(int, pl["end"].split(":"))
                oh, om = map(int, t.split(":"))
                t = max(min(h * 60 + m + 45, 22 * 60), oh * 60 + om)
                t = f"{t // 60:02d}:{t % 60:02d}"
            if not name or not t or name == "skip":
                continue
            own = isinstance(name, dict)
            r = {} if own else rec.get(name, {})
            # öffentlicher Feed: eigene Einträge ohne Freitext
            title = "Eigenes Essen" if own else mp["away"]["name"] if name == "away" else name
            h, m = map(int, t.split(":"))
            end = min(h * 60 + m + (15 if k == "sn" else 30), 23 * 60 + 59)
            url = f"{SITE}#e={iso}"
            desc = f"In der App öffnen: {url}" + (f"\n\n{r['kcal']} kcal · {r['protein']} g Protein" if r else f"\n\n{mp['away']['hint']}" if name == "away" else "")
            L += ["BEGIN:VEVENT", f"UID:meal-{iso}-{k}@tb2.trainingsbuch", f"DTSTAMP:{stamp}",
                  f"DTSTART:{utc(d, t)}", f"DTEND:{utc(d, f'{end // 60:02d}:{end % 60:02d}')}",
                  fold("SUMMARY:" + ics_escape(f"{slot['label']}: {title}")), fold("DESCRIPTION:" + ics_escape(desc)),
                  fold("URL:" + url), "TRANSP:TRANSPARENT", "END:VEVENT"]
    L.append("END:VCALENDAR")
    return "\r\n".join(L) + "\r\n"


def write_meal_feed(content):
    out = os.environ.get("MEAL_ICS_OUT")
    if not out:
        return
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    print("Essens-Feed geschrieben")


def update_gist(content):
    out = os.environ.get("ICS_OUT")
    if out:  # Feed als Datei im öffentlichen Pages-Repo (nur Trainingszeiten, keine anderen Termine)
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        print("Kalender-Feed geschrieben")
        return
    gid, tok = os.environ.get("GIST_ID"), os.environ.get("GIST_TOKEN")
    if not gid or not tok:
        print("Gist nicht konfiguriert, Kalender-Feed übersprungen")
        return
    body = json.dumps({"files": {"trainingsbuch.ics": {"content": content}}}).encode()
    req = urllib.request.Request(f"https://api.github.com/gists/{gid}", data=body, method="PATCH",
                                 headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        print("Kalender-Feed aktualisiert:", r.status)


# ---------- Push ----------
def send_push(subs, payload, dead):
    from pywebpush import WebPushException, webpush
    from py_vapid import Vapid
    pem = os.environ.get("VAPID_PRIVATE_PEM", "")
    if not pem or not subs:
        print("Push übersprungen (kein Schlüssel oder kein Gerät)")
        return []
    vapid = Vapid.from_pem(pem.encode())
    keep = []
    for s in subs:
        if s["endpoint"] in dead:
            continue
        try:
            webpush({"endpoint": s["endpoint"], "keys": s["keys"]}, json.dumps(payload), vapid_private_key=vapid,
                    vapid_claims={"sub": "mailto:trainingsbuch@users.noreply.github.com"}, ttl=6 * 3600)
            keep.append(s)
        except WebPushException as ex:
            code = ex.response.status_code if ex.response is not None else None
            print("Push fehlgeschlagen:", code)
            if code in (404, 410):
                dead[s["endpoint"]] = dt.date.today().isoformat()
            else:
                keep.append(s)
    print(f"Push gesendet an {len(keep)} Gerät(e)")
    return keep


def main():
    now = dt.datetime.now(TZ)
    today = now.date()
    settings = load("settings.json", {})
    days = load_days()
    state = load("state.json", {"sent": {}})
    push = load("push.json", {"subs": []})
    old_plan = load("plan.json", {"days": []})

    busy, cal_ok, cal_total = fetch_busy(dt.datetime.combine(today, dt.time(0), TZ), dt.datetime.combine(today + dt.timedelta(days=HORIZON + 1), dt.time(0), TZ))
    # Heute: bereits erledigte oder laufende Einheit behalten statt umzuplanen
    old_today = next((p for p in old_plan.get("days", []) if p["date"] == today.isoformat()), None)
    keep = old_today if old_today and (is_strength(days.get(today.isoformat())) or now.strftime("%H:%M") >= old_today.get("start", "99")) else None
    plan, extras = build_plan(now, settings, days, busy, keep)
    cal_failed = cal_ok < cal_total
    if cal_failed and old_plan.get("days"):
        # Ohne vollständige Kalender nicht über Termine hinweg neu planen: alten Plan behalten
        plan = [p for p in old_plan["days"] if p["date"] >= today.isoformat()]
        extras = old_plan.get("extras", extras)
        print("Kalender unvollständig: alter Plan bleibt")

    if keep and not any(p["date"] == today.isoformat() for p in plan):
        plan.insert(0, keep)
    past = [dict(p, done=is_strength(days.get(p["date"]))) for p in old_plan.get("past", []) + old_plan.get("days", [])
            if p["date"] < today.isoformat() and p["date"] >= (today - dt.timedelta(days=21)).isoformat()]
    past = list({p["date"]: p for p in past}.values())
    # ausgefallene Einheiten zählen (für die Morgen-Nachricht)
    missed_yday = next((p for p in past if p["date"] == (today - dt.timedelta(days=1)).isoformat() and not p["done"]), None)

    save("plan.json", {"generated": now.isoformat(timespec="minutes"), "days": plan, "extras": extras, "past": past})
    try:
        update_gist(build_ics(now, settings, plan, extras, past))
    except Exception as ex:
        print("Kalender-Feed Fehler:", type(ex).__name__)
    try:
        write_meal_feed(build_meal_ics(now, settings, plan, days))
    except Exception as ex:
        print("Essens-Feed Fehler:", type(ex).__name__)

    # ---- Push-Entscheidungen nach lokaler Uhrzeit ----
    hm = now.strftime("%H:%M")
    tday = today.isoformat()
    day = days.get(tday, {})
    p_today = next((p for p in plan if p["date"] == tday), None)
    msgs = []

    def once(key, payload):
        if not state["sent"].get(key):
            msgs.append((key, payload))

    if "07:00" <= hm < "10:30":
        if p_today:
            s = variant(p_today["session"], settings, today) if p_today["session"] != "notfall" else "notfall"
            body = f"{TITLE.get(s, s)} · freier Slot {p_today['start']}–{p_today['end']}." if not cal_failed else f"{TITLE.get(s, s)} um {p_today['start']} (Kalender gerade nicht erreichbar, Plan unverändert)."
            if missed_yday:
                body = "Gestern ausgefallen, deshalb heute dran: " + body
        else:
            body = "Heute keine Krafteinheit geplant."
            if missed_yday:
                body = "Gestern ausgefallen. Die Einheit liegt jetzt auf dem nächsten freien Tag."
        once(f"morning-{tday}", {"title": "Guten Morgen: 7 min Routine", "body": body + " " + coaching(settings, today),
                                 "url": f"{SITE}#m={tday}", "tag": f"m-{tday}", "action": "Öffnen"})
    if "20:15" <= hm < "23:30" and p_today and hm >= p_today.get("end", "00:00") and not is_strength(day):
        once(f"evening-{tday}", {"title": "Noch keine Einheit eingetragen",
                                 "body": "Hast du trainiert? Dann jetzt eintragen. Sonst rutscht die Einheit automatisch auf den nächsten freien Tag.",
                                 "url": f"{SITE}#w={tday}", "tag": f"e-{tday}", "action": "Eintragen"})
    if "21:40" <= hm <= "23:59" and not has_pain_log(day):
        once(f"pain-{tday}", {"title": "Abendcheck fehlt (30 s)", "body": "Schmerz-Log in der App eintragen.",
                              "url": f"{SITE}#p={tday}", "tag": f"p-{tday}", "action": "Eintragen"})
    mon = (today - dt.timedelta(days=today.weekday())).isoformat()
    if today.weekday() == 6 and "18:30" <= hm <= "23:30" and mon not in load("checkins.json", {}):
        once(f"checkin-{mon}", {"title": "Wochen-Check-in", "body": "10 Minuten: Bilanz der Woche und Modus für die nächste.",
                                "url": f"{SITE}#c={mon}", "tag": f"c-{mon}", "action": "Öffnen"})

    dead = state.setdefault("dead", {})
    for key, m in msgs:
        if send_push(push.get("subs", []), m, dead):
            state["sent"][key] = now.isoformat(timespec="minutes")
    # alte Einträge aufräumen
    cutoff = (today - dt.timedelta(days=14)).isoformat()
    state["sent"] = {k: v for k, v in state["sent"].items() if v[:10] >= cutoff}
    save("state.json", state)
    print(f"Fertig. Nachrichten: {len(msgs)}")


if __name__ == "__main__":
    sys.exit(main())
