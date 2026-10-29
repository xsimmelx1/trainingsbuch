"""Planer fürs Trainingsbuch.

Läuft per GitHub Action. Liest Google- und Uni-Kalender (ICS-Adressen aus Secrets),
legt die nächsten Krafteinheiten in freie Slots, schreibt data/plan.json,
aktualisiert den Kalender-Feed (geheimer Gist) und schickt Push-Erinnerungen.
Gibt bewusst keine Kalender- oder Gesundheitsdaten ins Log aus.
"""
import datetime as dt
import json
import math
import os
import re
import sys
import urllib.request
import zoneinfo

REC_ALIAS = {
    "Chili sin Carne mit Sojagranulat & Reis": "Chili sin Carne mit Sojagranulat, Kidney & Mais",
    "Rote-Linsen-Dal mit Spinat, Reis & Skyr": "Rote Linsen mit Kokos-Spinat & Reis",
    "Indischer Rote-Linsen-Eintopf mit Reis & Skyr": "Rote Linsen mit Kokos-Spinat & Reis",
    "Linsen-Soja-Bolognese mit Vollkornnudeln": "Rote-Linsen-Bolognese mit Spaghetti & Quark-Topping",
    "Gefüllte Senf-Quark-Eier": "Gefüllte Skyr-Senf-Eier",
}

TZ = zoneinfo.ZoneInfo("Europe/Berlin")
ROOT = os.environ.get("DATA_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SITE = "https://xsimmelx1.github.io/trainingsbuch/"

SEQ = ["beineA", "okA", "beineB", "okB"]
BASE = {"beineAk": "beineA", "beineBk": "beineB", "okBhome": "okB"}
TITLE = {"beineA": "Beine A", "okA": "Oberkörper A", "beineB": "Beine B", "okB": "Oberkörper B",
         "notfall": "Notfall-Ganzkörper", "reduziert": "Ganzkörper (reduziert)", "beineAk": "Beine A · Knie-Phase 1", "beineBk": "Beine B · Knie-Phase 1"}
# Öffentlicher Kalender-Feed: neutrale Namen ohne Reha- oder Stress-Status
PUBLIC_TITLE = {"beineA": "Beine A", "okA": "Oberkörper A", "beineB": "Beine B", "okB": "Oberkörper B", "beineAk": "Beine A", "beineBk": "Beine B",
                "notfall": "Kurz-Einheit", "reduziert": "Ganzkörper", "okBhome": "Oberkörper B",
                "notfallK": "Kurz-Einheit", "reduziertK": "Ganzkörper"}
EXERCISES = {  # Namen wie in der App (EX.name)
    "beineA": ["Beinpresse / Hack Squat", "Rumänisches Kreuzheben", "Beinstrecker", "Sitzender Beinbeuger", "Wadenheben stehend", "Dead Bug"],
    "okA": ["Brustgestütztes Rudern", "KH-Schrägbank 15–30°, Neutralgriff", "Latzug Neutralgriff", "Kabel-Seitheben bis 90°", "Face Pull (Ende in Außenrotation)", "Kabel-Shrug, 30° abgespreizt", "Bayesian Curl am Kabel", "Trizeps-Pushdown"],
    "beineB": ["Hip Thrust", "Bulgarian Split Squat", "Liegender Beinbeuger", "Hüftabduktion Maschine", "Step-Downs 10→20 cm", "Wadenheben sitzend", "Pallof Press"],
    "okB": ["Klimmzug Neutralgriff", "Kabelrudern sitzend", "Brustpresse Maschine/Kabel", "Landmine Press halbkniend", "KH-Seitheben", "Reverse Fly Maschine", "Serratus Punch am Kabel", "Kabel-Shrug, 30° abgespreizt", "Skull Crusher", "Ab-Roller kniend, kurzer Weg"],
    "notfall": ["Bulgarian Split Squat", "Rumänisches Kreuzheben", "Latzug Neutralgriff", "Brustpresse Maschine/Kabel", "KH-Seitheben"],
    "reduziert": ["Beinpresse / Hack Squat", "Rumänisches Kreuzheben", "Latzug Neutralgriff", "Brustgestütztes Rudern", "Brustpresse Maschine/Kabel", "Kabel-Seitheben bis 90°", "Kabel-Shrug, 30° abgespreizt"],
}
EXERCISES["beineAk"] = ["Wandsitz", "Beinstrecker 90→45°", "Beinpresse 0→60°", "Rumänisches Kreuzheben", "Hüftabduktion", "Wadenheben stehend", "Seitstütz"]
EXERCISES["beineBk"] = ["Wandsitz", "Beinstrecker 90→45°", "Beinpresse 0→60°", "Hip Thrust", "Hüftabduktion", "Liegender Beinbeuger", "Wadenheben sitzend", "Seitstütz"]

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
    tip = "" if settings.get("mode") == "pause" else FOCUS[pid]  # in der Pause kein Trainings-Fokus
    if not (settings.get("lessons") or {}).get(f"l{c}"):
        tip += f" Lektion der Woche: {LESSON_TITLES[c]}"
    return tip.strip()


TRAIN_MIN = 75         # Dauer einer Einheit inkl. Aufwärmen
SHORT_MIN = 35          # Notfall-Kurzeinheit
BUFFER = 20             # Puffer vor/nach Terminen (Weg zum Gym)
# Bevorzugte Fenster: abends, mittags, spätabends, morgens, sonst irgendwann tagsüber
WINDOWS = [(17, 0, 20, 45), (12, 0, 14, 30), (19, 0, 21, 15), (7, 0, 9, 30), (9, 30, 17, 0)]
HORIZON = 14
# Feste Zeiten der Routinen (in der App unter Einstellungen › Training & Plan einstellbar)
ROUTINE_DEF = {"mob": "07:30", "pain": "21:45"}


def routine_at(settings, k):
    v = (settings.get("routineTimes") or {}).get(k)
    return v if isinstance(v, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v) else ROUTINE_DEF[k]


def mob_min(settings):
    """Dauer der Morgenroutine; die App rechnet sie aus den Übungen und schreibt sie nach settings.mobMin."""
    v = settings.get("mobMin")
    return int(v) if isinstance(v, (int, float)) and 5 <= v <= 60 else 15


def hm_add(hm, minutes):
    h, m = map(int, hm.split(":"))
    t = max(0, min(h * 60 + m + minutes, 23 * 60 + 59))
    return f"{t // 60:02d}:{t % 60:02d}"


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
# Zyklus: Pausentage zählen nicht mit (offene Pause bis heute) – wie cycleDays/weekNo in der App
def _pauses(settings):
    out = []
    for p in settings.get("pauses") or []:
        try:
            a = dt.date.fromisoformat(p["from"])
            b = dt.date.fromisoformat(p["to"]) if p.get("to") else None
            out.append((a, b))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return out


def paused_day(settings, d):
    today = dt.datetime.now(TZ).date()
    return any(a <= d <= (b or today) for a, b in _pauses(settings))


def cycle_days(settings, d):
    st = dt.date.fromisoformat(settings["startDate"])
    today = dt.datetime.now(TZ).date()
    n = 0
    for a, b in _pauses(settings):
        a = max(a, st)
        e = min(b or today, d - dt.timedelta(days=1))
        if e >= a:
            n += (e - a).days + 1
    return (d - st).days - n


def cycle_date(settings, off):
    x = dt.date.fromisoformat(settings["startDate"]) + dt.timedelta(days=off)
    for _ in range(4000):
        if cycle_days(settings, x) >= off and not paused_day(settings, x):
            break
        x += dt.timedelta(days=1)
    return x


def week_no(settings, d):
    st = settings.get("startDate")
    if not st:
        return 0
    s0 = dt.date.fromisoformat(st)
    mon = lambda x: x - dt.timedelta(days=x.weekday())
    if (mon(d) - mon(s0)).days < 0:
        return 0
    return max(0, cycle_days(settings, d) + (s0 - mon(s0)).days) // 7 + 1


def cal_week_no(settings, d):
    """Kalenderwoche seit Start ohne Pausen-Abzug: der Essensplan bleibt an Montage gebunden (wie calWeek in der App)."""
    st = settings.get("startDate")
    if not st:
        return 0
    st = dt.date.fromisoformat(st)
    mon = lambda x: x - dt.timedelta(days=x.weekday())
    diff = (mon(d) - mon(st)).days
    return 0 if diff < 0 else diff // 7 + 1


def variant(base, settings, d):
    k = "K" if settings.get("knee1") else ""  # Knie-Phase 1 hat Vorrang vor jedem Modus (wie variantOf)
    if base == "notfall" or settings.get("mode") == "notfall":
        return "notfall" + k
    if settings.get("mode") == "reduziert":
        return "reduziert" + k
    if k:
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
    max_week = {"normal": 4, "reduziert": 2, "notfall": 2, "pause": 0}.get(settings.get("mode", "normal"), 4)
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
    last = None  # letzte Krafteinheit (für den Abstand bei Ganzkörper-Modi)
    for k in sorted(days, reverse=True):
        if k < start.isoformat() and is_strength(days[k]):
            last = dt.date.fromisoformat(k)
            break
    for i in range(HORIZON):
        d = start + dt.timedelta(days=i)
        wk = d.isocalendar()[:2]
        if d.weekday() == 6 or consec >= 2 or count.get(wk, 0) >= max_week:
            consec = 0
            continue
        bo = lambda x: bool(((days.get(x.isoformat()) or {}).get("boulder") or {}).get("done"))
        if (bo(d) or bo(d - dt.timedelta(days=1))) and SEQ[nxt] in ("okA", "okB"):
            consec = 0
            continue  # am Bouldertag und am Tag danach kein Oberkörper (Zugmuskulatur)
        if settings.get("mode") in ("reduziert", "notfall") and last and (d - last).days < 3:
            continue  # Ganzkörper: mindestens 72 h Abstand
        not_before = now + dt.timedelta(minutes=30) if d == today else dt.datetime.combine(d, dt.time(0), TZ)
        slot = find_slot(d, busy, TRAIN_MIN + (15 if SEQ[nxt] == "okB" else 0), not_before)  # okB ist die längste Einheit
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
        if not short:  # Kurz-Einheit zählt im Rückblick nicht für die Reihenfolge (BASE), also auch hier nicht weiterrücken
            nxt = (nxt + 1) % 4
        consec += 1
        last = d
        count[wk] = count.get(wk, 0) + 1
    # Sonntag: Check-in & Meal Prep (2 h), wenn möglich; ohne Meal Prep nur der Check-in (30 min)
    extras = []
    prep = (settings.get("food") or {}).get("mealPrep") is not False
    for i in range(HORIZON):
        d = today + dt.timedelta(days=i)
        if d.weekday() == 6:
            nb = now + dt.timedelta(minutes=30) if d == today else dt.datetime.combine(d, dt.time(0), TZ)
            sl = find_slot(d, busy, 120 if prep else 30, nb) or (dt.datetime.combine(d, dt.time(17), TZ), dt.datetime.combine(d, dt.time(19 if prep else 17, 0 if prep else 30), TZ))
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


def cal_pref(settings, k):
    """Kalender-Einstellung je Eintragsart: (im Kalender?, Erinnerung in Minuten vorher oder None). Ohne Einstellung wie bisher."""
    p = (settings.get("calPrefs") or {}).get(k) or {}
    pp = settings.get("pushPrefs") or {}
    default = {"train": 30, "mob": 0 if pp.get("morning") is not False else None, "pain": 0 if pp.get("pain") is not False else None,
               "checkin": 15 if pp.get("checkin") is not False else None, "marker": None}[k]
    rem = p["rem"] if "rem" in p else default
    ok = isinstance(rem, (int, float)) and not isinstance(rem, bool) and 0 <= rem <= 1440
    return p.get("on") is not False, int(rem) if ok else None


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
        if alarm is not None:
            L.extend(["BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:-PT{alarm}M", "DESCRIPTION:" + ics_escape(summary), "END:VALARM"])
        L.append("END:VEVENT")

    (on_train, rem_train), (on_mob, rem_mob), (on_pain, rem_pain), (on_check, rem_check), (on_mark, _) = (
        cal_pref(settings, k) for k in ("train", "mob", "pain", "checkin", "marker"))
    for p in (past + plan) if on_train else []:
        d = dt.date.fromisoformat(p["date"])
        if not p.get("done") and paused_day(settings, d):
            continue  # in der Pause entfallen (App: „entfallen (Pause)“)
        s = variant(p["session"], settings, d)
        title = PUBLIC_TITLE.get(s, s)
        desc = ("Nur ein kurzer Slot frei: 30-Minuten-Einheit.\n" if p.get("short") else "") + "Übungen und Sätze stehen in der App."
        past_day = d < now.date()
        ev(f"train-{p['date']}", f"Training: {title}", desc, f"{SITE}#w={p['date']}",
           utc(d, p["start"]), utc(d, p["end"]), alarm=None if past_day else rem_train)
    today = now.date()
    mob, pain = routine_at(settings, "mob"), routine_at(settings, "pain")
    for i in range(HORIZON):
        d = today + dt.timedelta(days=i)
        if on_mob:
            ev(f"morning-{d}", f"Morgenroutine {mob_min(settings)} min", "Routine in der App abhaken und Schlaf eintragen (Gewicht nur am Gym-Wiegetag).",
               f"{SITE}#m={d}", utc(d, mob), utc(d, hm_add(mob, mob_min(settings))), alarm=rem_mob)
        if on_pain:
            ev(f"pain-{d}", "Abendcheck (30 s)", "Kurzer Abendcheck in der App.", f"{SITE}#p={d}", utc(d, pain), utc(d, hm_add(pain, 5)), alarm=rem_pain)
    for x in extras if on_check else []:
        d = dt.date.fromisoformat(x["date"])
        prep = (settings.get("food") or {}).get("mealPrep") is not False
        ev(f"checkin-{x['date']}", "Check-in & Meal Prep" if prep else "Wochen-Check-in", "Wochen-Check-in in der App, danach Meal Prep (2 Töpfe, 1 Blech, 3 Gläser)." if prep else "Wochen-Check-in in der App (10 min).",
           f"{SITE}#c={(d - dt.timedelta(days=d.weekday())).isoformat()}", utc(d, x["start"]), utc(d, x["end"]), alarm=rem_check)
    st = settings.get("startDate")
    if st and on_mark:  # Zyklustage ohne Pausen, wie calMarkers in der App
        cyc = max(0, cycle_days(settings, today) // 84)
        for name, off, length in [("Messtag Woche 0: Fotos, Umfänge, Tests", -1, 1), ("Deload-Woche (Sätze halbieren, RIR 3–4)", 35, 7),
                                  ("Messtag: Fotos, Umfänge, Re-Test", 41, 1), ("Deload-Woche (Sätze halbieren, RIR 3–4)", 77, 7),
                                  ("Messtag: Fotos, Umfänge, Re-Test", 83, 1)]:
            if cyc and off < 0:
                continue
            a, e = cycle_date(settings, 84 * cyc + off), cycle_date(settings, 84 * cyc + off + length)
            if e >= today - dt.timedelta(days=7):
                ev(f"marker-{a}-{length}", name, "Siehe Plan & Regeln in der App.", f"{SITE}#t=messen" if length == 1 else SITE,
                   allday=(a, e))
    L.append("END:VCALENDAR")
    return "\r\n".join(L) + "\r\n"


# ---------- Essensplan ----------
SITE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


ALLERGENS = {"nuesse": "walnu|cashew|haselnu|mandel|pistazie|nüsse|nusskern|studentenfutter|nussmus", "erdnuss": "erdnuss", "soja": "soja|tofu|edamame|tempeh",
             "ei": r"\beier?\b|eiklar|eigelb|rührei|spiegelei|omelett|ei-", "milch": "(?<!kokos)milch|skyr|quark|käse|joghurt|sahne|butter|feta|harzer|mozzarella|halloumi|camembert|gouda|emmentaler|schmand|crème fraîche|creme fraiche",
             "gluten": "weizen|mehl|nudel|pasta|spaghetti|brot|brötchen|couscous|tortilla|wrap|hafer|knäcke|bulgur|biskuit|dürüm|seitan|dinkel|grünkern|gerste|panko|semmel", "sesam": "sesam|tahin", "senf": "senf"}


# wie VEGAN_RE in der App: tierische Zutaten; Pflanzendrinks, Soja-/Kokosjoghurt, Erdnuss-/Mandelbutter zählen nicht
VEGAN_RE = r"\beier?\b|eiklar|eigelb|rührei|spiegelei|omelett|\bei-|(?<!kokos)(?<!hafer)(?<!soja)(?<!mandel)(?<!reis)(?<!erbsen)milch|skyr|(?<!soja)quark|käse|(?<!soja)(?<!kokos)joghurt|(?<!hafer)(?<!soja)(?<!kokos)sahne|(?<!erdnuss)(?<!nuss)(?<!mandel)(?<!cashew)(?<!kakao)butter|feta|harzer|mozzarella|halloumi|camembert|gouda|emmentaler|parmesan|ricotta|mascarpone|schmand|crème fraîche|creme fraiche|kefir|molke|whey|honig|gelatine|ghee"


def avoid_re(settings):
    import re
    f = settings.get("food") or {}
    parts = [ALLERGENS[k] for k in f.get("allergens") or [] if k in ALLERGENS]
    if f.get("vegan"):
        parts.append(VEGAN_RE)
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
    have = set(f.get("devices") or ["herd", "ofen", "mixer", "mikrowelle"])  # Küchengeräte wie devParts in der App
    if "herd" not in have:
        parts.append("§herd§")
    if "ofen" not in have:
        parts.append("§ofen§")
        if "airfryer" not in have:
            parts.append("§ofenk§")
    if "mixer" not in have:
        parts.append("§mixer§")
    return re.compile("|".join(parts), re.I) if parts else None


def dev_tok(r):
    return "".join(" §%s§" % d for d in r.get("dev") or [])


def uniq(rec):
    """Jedes Rezept einmal: Alias-Namen (REC_ALIAS) zeigen auf dasselbe Rezept und dürfen in Auswahllisten nicht mehrfach zählen."""
    return [r for n, r in rec.items() if r["name"] == n]


def substitute(mp, rec, o, rx):
    """Gemiedene Gerichte durch das ähnlichste erlaubte derselben Mahlzeit ersetzen (wie altMeals in der App)."""
    if not rx:
        return o
    text = lambda r: (r.get("_text") or (r["name"] + " " + " ".join(r.get("ingredients", []))).lower()) + dev_tok(r)
    slots = {s["k"]: s for s in mp["slots"]}
    for k, n in list(o.items()):
        r = rec.get(n)
        if not r or not rx.search(text(r)):
            continue
        minp = 13 if k in ("sn", "ex") else 25
        cands = [x for x in uniq(rec) if x["category"] in slots[k]["cats"] and x["name"] != n and x["protein"] >= minp and not rx.search(text(x))]
        cands.sort(key=lambda x: abs(x["kcal"] - r["kcal"]) / 8 + abs(x["protein"] - r["protein"]))
        used = set(v for v in o.values() if isinstance(v, str))  # möglichst kein Gericht zweimal am Tag (wie mealDefaults)
        if cands:
            o[k] = next((x for x in cands if x["name"] not in used), cands[0])["name"]
    return o


# ---------- Preise und Budget (wie parseIng, recipeCost, altMeals, budgetSubs in der App) ----------
SUBST_OK = {"milch": {"sojadrink": ["sojadrink"], "haferdrink": ["haferdrink"], "mix": ["pflanzendrink"]},
            "kochsahne": {"cuisine": ["cuisine"]}, "butter": {"margarine": ["margarine"]}}
ING_RE = None


SUBST_D = {"milch": {"sojadrink": (-8, -0.1), "haferdrink": (-1, -2.7), "mix": (-4.5, -1.4)},
           "kochsahne": {"cuisine": (-20, -2.2)}, "butter": {"margarine": (-20, -0.7)}}


def adjust_recipes(rec, P, subst):
    """Kopie der Rezepte mit angepassten kcal/Protein und Text mit Ersatzprodukten statt ersetzter Zeilen (wie recipeNutri/recIngText)."""
    if not P or not subst:
        return rec
    out = {}
    for n, r in rec.items():
        k = p = 0.0
        lines = []
        for line in r.get("ingredients") or []:
            orig = parse_ing(line, P, {})
            subd = parse_ing(line, P, subst)
            if orig and subd and orig[0][0]["id"] != subd[0][0]["id"]:
                d = SUBST_D[orig[0][0]["id"]][subst[orig[0][0]["id"]]]
                amt = orig[0][1]
                k += amt / 100 * d[0]
                p += amt / 100 * d[1]
                lines.append(" ".join(x[0]["name"] for x in subd))  # ersetzte Zeile zählt als Ersatzprodukt (wie recIngText)
            else:
                lines.append(line)
        sv = r.get("servings") or 1
        rnd = lambda x: math.floor(x + 0.5)  # wie Math.round in der App
        out[n] = dict(r, kcal=rnd(r["kcal"] + k / sv), protein=rnd(r["protein"] + p / sv), _text=(r["name"] + " " + " ".join(lines)).lower())
    return out


def load_prices():
    import re
    try:
        with open(os.path.join(SITE_ROOT, "prices.json"), encoding="utf-8") as f:
            P = json.load(f)
    except OSError:
        return None
    for pr in P["products"]:
        pr["re"] = re.compile(pr["match"], re.I)
    P["stores"] = [st for st in ("rewe", "lidl", "aldi", "kaufland", "netto", "penny", "edeka") if any(st in (pr.get("prices") or {}) for pr in P["products"])]
    return P


def parse_ing(line, P, subst):
    import re
    global ING_RE
    ING_RE = ING_RE or re.compile(r"^(\d+(?:[.,]\d+)?|\d+/\d+|½)(?:\s*[–-]\s*\d+(?:[.,]\d+)?)?\s*(g|kg|ml|l|EL|TL|Stück|Dosen?|Gläser|Glas|Bund|Handvoll|Pck\.?|Becher|Scheiben?|Prisen?)?\s+(.+)$")
    line = re.sub(r"^(ca\.|etwas|etwa|optional:?)\s+", "", line, flags=re.I)
    m = ING_RE.match(line)
    q = None
    if m:
        a = m.group(1)
        q = 0.5 if a == "½" else (float(a.split("/")[0]) / float(a.split("/")[1]) if "/" in a else float(a.replace(",", ".")))
    unit = (m.group(2) or "") if m else ""
    name = re.sub(r"\(.*?\)", "", m.group(3) if m else line).split(", ")[0].strip()
    pr = next((x for x in P["products"] if x["re"].search(name)), None)
    if not pr:
        return []
    if q is None:
        amt = 0
    elif unit in ("g", "ml"):
        amt = q
    elif unit in ("kg", "l"):
        amt = q * 1000
    elif unit == "EL":
        amt = q * 15
    elif unit == "TL":
        amt = q * 5
    elif unit == "Handvoll":
        amt = q * 30
    elif unit.startswith(("Dose", "Glas", "Gläser")):
        amt = q * (pr["pack"] if pr.get("dose") or pr.get("jar") else 400)
    elif unit.startswith("Prise"):
        amt = q
    elif unit == "Bund":
        amt = q if pr["unit"] == "Stück" else q * pr["pack"]
    elif unit == "Becher":
        amt = q * 250
    elif unit.startswith("Pck"):
        amt = q * pr["pack"]
    elif pr["unit"] == "Stück":
        amt = q
    else:
        amt = q * (pr.get("piece") or 100)
    if pr["unit"] == "Stück" and unit in ("g", "ml"):
        amt = q / (pr.get("piece") or 60)
    elif pr["unit"] == "Stück" and unit in ("EL", "TL", "Handvoll", "Prise", "Prisen"):  # 2 EL Petersilie ≈ 1 Bund, nicht 30 (wie parseIng in der App)
        amt = (q * 15 if unit == "EL" else q * 5 if unit == "TL" else q * 30 if unit == "Handvoll" else q) / (pr.get("piece") or 60)
    ids = SUBST_OK.get(pr["id"], {}).get((subst or {}).get(pr["id"]))
    if ids:
        ps = [x for x in P["products"] if x["id"] in ids]
        if ps:
            return [(x, amt / len(ps)) for x in ps]
    return [(pr, amt)]


def price_of(pr, store, P):
    ps = pr.get("prices") or {}
    if store != "min" and store not in P["stores"]:
        store = "min"
    if store == "min":
        v = [x for x in ps.values() if x is not None]
        return min(v) if v else None
    return ps.get(store)


# Gewürze, Kräuter und Kleinkram ohne Preis zählen nicht als „fehlender Preis“ (wie SPICE_RE in der App)
SPICE_RE = __import__("re").compile(r"rosenpaprika|edelsüß|pulver|gewürz|kümmel|kurkuma|curry(?!paste)|zimt|muskat|oregano|thymian|rosmarin|basilikum|petersilie|koriander|schnittlauch|dill|minze|kräuter|lorbeer|salz|pfeffer|chili|wasser|garam|essig|backpulver|vanill|nelke|kardamom|sumach|ras el|cayenne|zitronensaft|zitronenschale|hefe|sesam|liebstöckel|majoran|bohnenkraut|estragon|kresse", __import__("re").I)


def portion_cost(r, P, store, subst, memo):
    """Kosten pro Portion; memo[name + '#miss'] = Zutaten mit Menge ohne Preis (wie recipeCost().miss)."""
    import re
    if r["name"] in memo:
        return memo[r["name"]]
    c, miss = 0.0, 0
    for line in r.get("ingredients") or []:
        parts = parse_ing(line, P, subst)
        if not parts:
            if ING_RE.match(re.sub(r"^(ca\.|etwas|etwa|optional:?)\s+", "", line, flags=re.I)) and not SPICE_RE.search(line):
                miss += 1
            continue
        for pr, amt in parts:
            v = price_of(pr, store, P)
            if v is None:
                miss += 1
            else:
                c += amt / pr["pack"] * v
    memo[r["name"]] = c / (r.get("servings") or 1)
    memo[r["name"] + "#miss"] = miss
    return memo[r["name"]]


def def_amt(pr):
    return 0.5 if pr["unit"] == "Stück" else (pr["piece"] / 2 if pr.get("piece") else 20)


def recipe_vec(r, P, subst, memo):
    """Mengen je Produkt für ein ganzes Rezept (wie recipeVec in der App)."""
    key = "vec#" + r["name"]
    if key not in memo:
        v = {}
        for line in r.get("ingredients") or []:
            for pr, amt in parse_ing(line, P, subst):
                v[pr["id"]] = v.get(pr["id"], 0) + (amt or def_amt(pr))
        memo[key] = v
    return memo[key]


BASIS = set(["haferflocken", "reis", "nudeln", "vollkornnudeln", "linsennudeln", "couscous", "quinoa", "bulgur", "roteLinsen", "linsenBraun", "kichererbsen", "kidney", "weissebohnen", "schwarzeBohnen", "linsendose", "mais", "tomatenGehackt", "tomatenPassiert", "tomatenmark", "kokosmilch", "sojagranulat", "tkSpinat", "erbsen", "bohnenGruen", "edamame", "tkbeeren", "mehl", "zucker", "staerke", "oel", "sojasauce", "bruehe", "honig", "kakao", "chia", "leinsamen", "kerne", "walnuesse", "cashews", "mandeln", "pinienkerne", "erdnussmus", "tahin", "knaeckebrot", "magermilchpulver", "milch", "sojadrink", "haferdrink", "pflanzendrink", "currypaste", "currypulver", "senf", "essig", "agave", "oliven", "jalapenos", "loeffelbiskuits", "schokolade", "kartoffeln", "zwiebeln", "knoblauch", "margarine", "eiweissbrot", "tortillas"])  # wie BASIS in der App


def budget_share(pr, amt):  # wie budgetShare in der App: Lagerware anteilig
    if pr.get("pantry") or pr.get("dose") or pr["id"] in BASIS or pr["id"].lower().startswith("tk") or pr["name"].startswith("TK-"):
        return amt / pr["pack"]
    return pack_share(pr, amt)


def pack_share(pr, amt):
    if pr.get("pantry"):
        return amt / pr["pack"]
    if pr.get("loose") and pr.get("piece"):
        return max(1, math.ceil(amt / pr["piece"] - 0.1)) * pr["piece"] / pr["pack"]
    return max(1, math.ceil(amt / pr["pack"] - 0.05))


def shop_cost(counts, rec, P, store, subst, memo):
    """Wocheneinkauf in € wie shopCostCounts in der App: halbe/ganze Rezepte, Packungen, Vorrat anteilig."""
    tot = {}
    for n, cnt in counts.items():
        r = rec.get(n)
        if not r or not cnt:
            continue
        f = math.ceil(cnt / (r.get("servings") or 1) * 2) / 2
        for pid, a in recipe_vec(r, P, subst, memo).items():
            tot[pid] = tot.get(pid, 0) + a * f
    byid = {p["id"]: p for p in P["products"]}
    c = 0.0
    for pid, amt in tot.items():
        pr = byid.get(pid)
        v = price_of(pr, store, P) if pr else None
        if v is not None:
            c += budget_share(pr, amt) * v
    return c


def alt_meals(mp, rec, k, cur, rx):
    slot = next(x for x in mp["slots"] if x["k"] == k)
    ref = rec.get(cur) or {"kcal": 0, "protein": 0}
    minp = 13 if k in ("sn", "ex") else 25
    text = lambda r: (r.get("_text") or (r["name"] + " " + " ".join(r.get("ingredients", []))).lower()) + dev_tok(r)
    c = [r for r in uniq(rec) if r["category"] in slot["cats"] and r["name"] != cur and r["protein"] >= minp and not (rx and rx.search(text(r)))]
    c.sort(key=lambda r: abs(r["kcal"] - ref["kcal"]) / 8 + abs(r["protein"] - ref["protein"]))
    return c[:8]


DIFF_RANK = {"leicht": 0, "mittel": 1, "aufwendig": 2}


def effort_on(settings):
    e = (settings.get("food") or {}).get("effort") or {}
    return bool(e.get("lvl") or num(e.get("active")))


def effort_ok(settings, r):
    """Wie effortOk in der App."""
    e = (settings.get("food") or {}).get("effort") or {}
    rk = DIFF_RANK.get(r.get("difficulty"), 0)
    act = r.get("activeMin") if r.get("activeMin") is not None else r.get("timeMin")
    if e.get("lvl") == 1 and rk > 1:
        return False
    if e.get("lvl") == 2 and rk > 0:
        return False
    a = num(e.get("active"))
    if a and a > 0 and act is not None and act > a:
        return False
    return True


def effort_subst(mp, rec, settings, o, rx, W):
    """Zu aufwendige frische Gerichte tauschen, Batch-Gerichte bleiben (wie mealDefaults in der App)."""
    if not effort_on(settings):
        return o
    bt = set() if (settings.get("food") or {}).get("mealPrep") is False else {W["batchA"], W["batchB"]}
    o = dict(o)
    for k in list(o):
        r = rec.get(o[k])
        if r and o[k] not in bt and not effort_ok(settings, r):
            alt = next((c for c in alt_meals(mp, rec, k, o[k], rx) if effort_ok(settings, c)), None)
            if alt:
                o[k] = alt["name"]
    return o


def budget_subs(mp, rec, settings, raws, rx, P, W=None):
    f = settings.get("food") or {}
    budget = num(f.get("budget"))
    if not P or not budget or budget <= 0 or f.get("budgetIgnore"):
        return {}
    batch = {W["batchA"], W["batchB"]} if W and f.get("mealPrep") is not False else set()
    store, subst, memo = f.get("store") or "aldi", f.get("subst") or {}, {}
    cost = lambda n: portion_cost(rec[n], P, store, subst, memo) if n in rec else 0
    occ = {}
    for o in raws:
        for k, n in o.items():
            occ.setdefault(n, {"n": n, "slot": k, "cnt": 0})["cnt"] += 1
    subs = {}

    def total(sb):
        c = {}
        for x in occ.values():
            n = sb.get(x["n"], x["n"])
            c[n] = c.get(n, 0) + x["cnt"]
        return shop_cost(c, rec, P, store, subst, memo)
    cur_cost = total(subs)

    def day_v(sb, f):  # Tageswerte wie dayP/dayK in der App
        return [sum(rec[sb.get(n, n)][f] if sb.get(n, n) in rec else 0 for n in o.values()) for o in raws]
    fd = settings.get("food") or {}
    tp = num(fd.get("protein")) or (mp.get("target") or {}).get("protein") or 140
    tk = (num(fd.get("kcal")) or (mp.get("target") or {}).get("kcal") or 2650) - 250
    p0 = [min(tp, v) for v in day_v({}, "protein")]
    k0 = [min(tk, v) for v in day_v({}, "kcal")]

    def floors_ok(sb):  # jeder Tag einzeln
        return all(v >= p0[i] for i, v in enumerate(day_v(sb, "protein"))) and all(v >= k0[i] for i, v in enumerate(day_v(sb, "kcal")))
    minp = lambda k: 13 if k in ("sn", "ex") else 25
    text = lambda r: (r.get("_text") or (r["name"] + " " + " ".join(r.get("ingredients", []))).lower()) + dev_tok(r)

    cand_memo = {}

    def cands(k, cur):
        """altMeals plus die 15 günstigsten passenden Gerichte des Slots (wie budgetCands in der App)."""
        if (k, cur) in cand_memo:
            return cand_memo[(k, cur)]
        al = alt_meals(mp, rec, k, cur, rx)
        slot = next(x for x in mp["slots"] if x["k"] == k)
        cheap = [r for r in uniq(rec) if r["category"] in slot["cats"] and r["name"] != cur and r["protein"] >= minp(k) and not (rx and rx.search(text(r)))]
        cheap = sorted(cheap, key=lambda r: math.floor(cost(r["name"]) * 1e4 + 0.5) / 1e4)[:15]
        names = {r["name"] for r in al}
        cand_memo[(k, cur)] = al + [r for r in cheap if r["name"] not in names]
        return cand_memo[(k, cur)]
    for _ in range(40):
        if cur_cost <= budget:
            break
        best = None
        for x in occ.values():
            if x["n"] in subs or x["n"] not in rec:
                continue
            c0, ref = cost(x["n"]), rec[x["n"]]
            for c in cands(x["slot"], x["n"]):
                c1 = cost(c["name"])
                if (x["n"] in batch and not (c.get("mealPrep") and (c.get("servings") or 1) >= 4)) or memo.get(c["name"] + "#miss", 0) > 0 or (x["n"] not in batch and effort_on(settings) and not effort_ok(settings, c)):
                    continue
                if c1 >= c0 or c["protein"] < min(ref["protein"] * 0.8, 18 if x["slot"] in ("sn", "ex") else 30) or abs(c["kcal"] - ref["kcal"]) > 300 or c["name"] in occ or c["name"] in subs.values():
                    continue
                sb = dict(subs, **{x["n"]: c["name"]})
                save = cur_cost - total(sb)
                if save > 0.01 and (not best or save > best[2]) and floors_ok(sb):
                    best = (x["n"], c["name"], save)
        if not best:
            break
        subs[best[0]] = best[1]
        cur_cost = total(subs)
    return subs


def meal_defaults(mp, settings, d, train, is_train=None, boulder=False, rec=None, rx=None):
    w = cal_week_no(settings, d)
    W = mp["weeks"][(w - 1) % len(mp["weeks"]) if w > 0 else len(mp["weeks"]) - 1]
    i = d.weekday()
    o = {"fr": W["fr"][i]}
    if i <= 3:
        o["mi"], o["ab"] = (W["batchA"], W["batchB"]) if i % 2 == 0 else (W["batchB"], W["batchA"])
        if rec is not None and (settings.get("food") or {}).get("mealPrep") is False:  # Meal Prep aus: frische, ähnliche Gerichte (wie in der App)
            for k in ("mi", "ab"):
                sm = alt_meals(mp, rec, k, o[k], rx)
                if sm:
                    o[k] = sm[(i * 2 + (1 if k == "ab" else 0)) % len(sm)]["name"]
    elif i == 4:
        o["mi"], o["ab"] = W["frMittag"], W["frAbend"]
    elif i == 5:
        o["mi"], o["ab"] = W["frAbend"], W["saAbend"]
    else:
        o["mi"], o["ab"] = W["saAbend"], W["soAbend"]
    # Snacks rotieren über die Ruhetage der Woche (wie in der App)
    ri = sum(1 for k in range(i) if not is_train(d - dt.timedelta(days=i - k))) if is_train else i
    sn = W.get("snacks", mp["snacks"])
    o["sn"] = W.get("trainingSnack", mp["trainingSnack"]) if train else sn[(ri + 3 * w) % len(sn)]
    if not train:
        o["ex"] = W.get("trainingSnack", mp["trainingSnack"]) if boulder else mp["restExtra"][ri % 2]  # Shake nach dem Bouldern
    return o


def main_label(slot, r):
    """Hauptmahlzeiten heißen nach dem Gericht (wie mainLabel in der App)."""
    if slot["k"] not in ("mi", "ab"):
        return slot["label"]
    t = (r or {}).get("temp")
    return "Kalt" if t == "kalt" else "Warm oder kalt" if t == "beides" else "Warm" if r else "Hauptgericht"


def build_meal_ics(now, settings, plan, days, past=None):
    with open(os.path.join(SITE_ROOT, "mealplan.json"), encoding="utf-8") as f:
        mp = json.load(f)
    with open(os.path.join(SITE_ROOT, "recipes.json"), encoding="utf-8") as f:
        rec = {r["name"]: r for r in json.load(f)}
    # zusammengelegte Rezepte: alte Namen in gespeicherten Tagen zeigen auf das behaltene (gleiche Tabelle wie REC_ALIAS in index.html)
    for old, new in REC_ALIAS.items():
        if new in rec and old not in rec:
            rec[old] = rec[new]
    by_date = {p["date"]: p for p in plan}
    past_dates = {p["date"] for p in (past or [])}
    rx = avoid_re(settings)
    P = load_prices()
    fd = settings.get("food") or {}
    if P and (fd.get("bio") or fd.get("bioItems")):  # Bio für alle oder einzeln gewählte Produkte (wie bioUse in der App)
        for pr in P["products"]:
            if pr.get("bio") and (fd.get("bio") or pr["id"] in (fd.get("bioItems") or [])):
                pr.setdefault("prices", {}).update(pr["bio"])
    if P:  # eigene Preise aus Kassenbons vor den Richtpreisen (wie priceOf in der App)
        own = (settings.get("food") or {}).get("ownPrices") or {}
        for pr in P["products"]:
            for st, o in (own.get(pr["id"]) or {}).items():
                if o and o.get("price") is not None:
                    pr.setdefault("prices", {})[st] = o["price"]
    rec = adjust_recipes(rec, P, (settings.get("food") or {}).get("subst") or {})

    def is_train(dd):
        day = days.get(dd.isoformat()) or {}
        return is_strength(day) or bool(by_date.get(dd.isoformat())) or dd.isoformat() in past_dates  # Bouldern zählt fürs Essen nicht (wie isTrainDay)

    def bo(dd):
        return bool(((days.get(dd.isoformat()) or {}).get("boulder") or {}).get("done"))

    week_subs = {}

    def subs_for(dd):
        mo = dd - dt.timedelta(days=dd.weekday())
        if mo not in week_subs:
            w0 = cal_week_no(settings, mo)
            W0 = mp["weeks"][(w0 - 1) % len(mp["weeks"]) if w0 > 0 else len(mp["weeks"]) - 1]
            raws = [effort_subst(mp, rec, settings, substitute(mp, rec, meal_defaults(mp, settings, mo + dt.timedelta(days=i), is_train(mo + dt.timedelta(days=i)), is_train, rec=rec, rx=rx), rx), rx, W0) for i in range(7)]
            week_subs[mo] = budget_subs(mp, rec, settings, raws, rx, P, W0)
        return week_subs[mo]
    stamp = now.strftime("%Y%m%dT000000Z")
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//trainingsbuch//essen//DE", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
         "X-WR-CALNAME:Trainingsbuch Essen", "X-WR-TIMEZONE:Europe/Berlin", "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]
    for n in range(HORIZON):
        d = now.date() + dt.timedelta(days=n)
        iso = d.isoformat()
        day = days.get(iso) or {}
        pl = by_date.get(iso)
        wd = cal_week_no(settings, d)
        names = effort_subst(mp, rec, settings, substitute(mp, rec, meal_defaults(mp, settings, d, is_train(d), is_train, bo(d), rec=rec, rx=rx), rx), rx, mp["weeks"][(wd - 1) % len(mp["weeks"]) if wd > 0 else len(mp["weeks"]) - 1])
        bs = subs_for(d)
        names = {k: bs.get(v, v) for k, v in names.items()}
        names.update({k: v for k, v in (day.get("meals") or {}).items() if v})
        times = (settings.get("food") or {}).get("times") or {}
        off = set((settings.get("food") or {}).get("slotsOff") or [])
        for slot in mp["slots"]:
            k, name = slot["k"], names.get(slot["k"])
            if k in off and not (day.get("meals") or {}).get(k):  # in den Einstellungen ausgeschaltet
                continue
            t = times.get(k) or slot["time"]
            if t and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):  # ungültige eigene Zeit → Standard
                t = slot["time"]
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
            dur_m = 15 if k == "sn" else 30
            if h * 60 + m > 23 * 60 + 59 - dur_m:  # Ende muss nach dem Start liegen (RFC 5545)
                h, m = divmod(23 * 60 + 59 - dur_m, 60)
                t = f"{h:02d}:{m:02d}"
            end = h * 60 + m + dur_m
            url = f"{SITE}#e={iso}"
            desc = f"In der App öffnen: {url}" + (f"\n\n{r['kcal']} kcal · {r['protein']} g Protein" if r else f"\n\n{mp['away']['hint']}" if name == "away" else "")
            L += ["BEGIN:VEVENT", f"UID:meal-{iso}-{k}@tb2.trainingsbuch", f"DTSTAMP:{stamp}",
                  f"DTSTART:{utc(d, t)}", f"DTEND:{utc(d, f'{end // 60:02d}:{end % 60:02d}')}",
                  fold("SUMMARY:" + ics_escape(f"{main_label(slot, rec.get(name) if isinstance(name, str) else None)}: {title}")), fold("DESCRIPTION:" + ics_escape(desc)),
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
    try:
        vapid = Vapid.from_pem(pem.encode())
    except Exception as ex:  # ungültiger Schlüssel: nichts senden, nicht abstürzen
        print("Push-Schlüssel ungültig:", type(ex).__name__)
        return []
    keep = []
    for s in subs:
        if s["endpoint"] in dead:
            continue
        try:
            webpush({"endpoint": s["endpoint"], "keys": s["keys"]}, json.dumps(payload), vapid_private_key=vapid,
                    vapid_claims={"sub": "mailto:trainingsbuch@users.noreply.github.com"}, ttl=6 * 3600, timeout=15)
            keep.append(s)
        except WebPushException as ex:
            code = ex.response.status_code if ex.response is not None else None
            print("Push fehlgeschlagen:", code)
            if code in (404, 410):
                dead[s["endpoint"]] = dt.date.today().isoformat()
            # sonst (z. B. 5xx): nicht als zugestellt zählen, im nächsten Lauf erneut
        except Exception as ex:  # Netzwerk, Timeout …: nur dieses Abo überspringen
            print("Push fehlgeschlagen:", type(ex).__name__)
    print("Push-Lauf beendet")  # keine Zahlen: öffentliche Logs sollen kein Verhalten verraten
    return keep


def main():
    now = dt.datetime.now(TZ)
    today = now.date()
    settings = load("settings.json", {})
    try:  # ein kaputtes Startdatum darf den ganzen Lauf (Pushes, Feeds) nicht stoppen
        dt.date.fromisoformat(settings.get("startDate") or "2000-01-01")
    except (ValueError, TypeError):
        settings.pop("startDate", None)
        print("Startdatum ungültig – ignoriert")
    for k in ("routineTimes", "pushPrefs", "lessons", "food"):  # falscher Typ soll nicht den ganzen Lauf stoppen
        if k in settings and not isinstance(settings[k], dict):
            settings.pop(k)
    days = load_days()
    state = load("state.json", {"sent": {}})
    push = load("push.json", {"subs": []})
    old_plan = load("plan.json", {"days": []})

    busy, cal_ok, cal_total = fetch_busy(dt.datetime.combine(today, dt.time(0), TZ), dt.datetime.combine(today + dt.timedelta(days=HORIZON + 1), dt.time(0), TZ))
    # Morgenroutine als feste Zeit: kein Training darüber legen (Abendcheck dauert 30 s und blockiert nichts)
    mh, mm = map(int, routine_at(settings, "mob").split(":"))
    for i in range(HORIZON + 1):
        a = dt.datetime.combine(today + dt.timedelta(days=i), dt.time(mh, mm), TZ)
        busy.append((a, a + dt.timedelta(minutes=mob_min(settings))))
    # Heute: bereits erledigte oder laufende Einheit behalten statt umzuplanen
    old_today = next((p for p in old_plan.get("days", []) if p["date"] == today.isoformat()), None)
    # behalten nur, wenn heute wirklich trainiert wurde oder das Training läuft – eine verpasste Einheit rutscht sonst nicht nach
    td = days.get(today.isoformat()) or {}
    keep = old_today if old_today and (is_strength(td) or td.get("startedAt")) else None
    plan, extras = build_plan(now, settings, days, busy, keep)
    cal_failed = cal_ok < cal_total
    if cal_failed and old_plan.get("days"):
        # Ohne vollständige Kalender nicht über Termine hinweg neu planen: alten Plan behalten
        plan = [p for p in old_plan["days"] if p["date"] >= today.isoformat()]
        extras = old_plan.get("extras", extras)
        print("Kalender unvollständig: alter Plan bleibt")
    pause = settings.get("mode") == "pause"
    if pause:  # Trainingspause: keine Krafteinheiten, auch nicht aus dem alten Plan
        plan = [p for p in plan if p is keep]

    if keep and not any(p["date"] == today.isoformat() for p in plan):
        plan.insert(0, keep)
    # Vergangenes plus heutige Einheiten, die jetzt nicht mehr unterzubringen sind (sonst fehlen sie im Feed, im Abend-Push und morgen als „ausgefallen“)
    in_plan = {p["date"] for p in plan}
    past = [dict(p, done=is_strength(days.get(p["date"]))) for p in old_plan.get("past", []) + old_plan.get("days", [])
            if p["date"] <= today.isoformat() and p["date"] not in in_plan and p["date"] >= (today - dt.timedelta(days=21)).isoformat()]
    past = list({p["date"]: p for p in past}.values())
    # ausgefallene Einheiten zählen (für die Morgen-Nachricht)
    missed_yday = None if pause else next((p for p in past if p["date"] == (today - dt.timedelta(days=1)).isoformat() and not p["done"]), None)

    feed_failed = False
    save("plan.json", {"generated": now.isoformat(timespec="minutes"), "days": plan, "extras": extras, "past": past})
    try:
        update_gist(build_ics(now, settings, plan, extras, past))
    except Exception as ex:
        print("Kalender-Feed Fehler:", type(ex).__name__)
        feed_failed = True
    try:
        write_meal_feed(build_meal_ics(now, settings, plan, days, past))
    except Exception as ex:
        print("Essens-Feed Fehler:", type(ex).__name__)
        feed_failed = True

    # ---- Push-Entscheidungen nach lokaler Uhrzeit ----
    hm = now.strftime("%H:%M")
    tday = today.isoformat()
    day = days.get(tday, {})
    p_today = next((p for p in plan if p["date"] == tday), None)
    msgs = []

    prefs = settings.get("pushPrefs") or {}

    def once(key, payload):
        if prefs.get(key.split("-")[0]) is False:  # vom Nutzer abgeschaltet
            return
        if not state["sent"].get(key):
            msgs.append((key, payload))

    mob, pain = routine_at(settings, "mob"), routine_at(settings, "pain")
    if hm_add(mob, -30) <= hm < hm_add(mob, 180):
        if p_today:
            s = variant(p_today["session"], settings, today) if p_today["session"] != "notfall" else "notfall"
            body = f"{TITLE.get(s, s)} · freier Slot {p_today['start']}–{p_today['end']}." if not cal_failed else f"{TITLE.get(s, s)} um {p_today['start']} (Kalender gerade nicht erreichbar, Plan unverändert)."
            if missed_yday:
                body = "Gestern ausgefallen, deshalb heute dran: " + body
        else:
            body = "Trainingspause: keine Krafteinheit, Routine ohne Plank und Shrug." if pause else "Heute keine Krafteinheit geplant."
            if missed_yday:
                body = "Gestern ausgefallen. Die Einheit liegt jetzt auf dem nächsten freien Tag."
        once(f"morning-{tday}", {"title": f"Guten Morgen: {mob_min(settings)} min Routine", "body": (body + " " + coaching(settings, today)).strip(),
                                 "url": f"{SITE}#m={tday}", "tag": f"m-{tday}", "action": "Öffnen"})
    p_eve = p_today or (None if pause else next((p for p in past if p["date"] == tday), None))  # auch eine heute herausgefallene Einheit nachfragen
    if "20:15" <= hm < "23:30" and p_eve and hm >= p_eve.get("end", "00:00") and not is_strength(day):
        once(f"evening-{tday}", {"title": "Noch keine Einheit eingetragen",
                                 "body": "Hast du trainiert? Dann jetzt eintragen. Sonst rutscht die Einheit automatisch auf den nächsten freien Tag.",
                                 "url": f"{SITE}#w={tday}", "tag": f"e-{tday}", "action": "Eintragen"})
    if hm_add(pain, -5) <= hm <= "23:59" and not has_pain_log(day):
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
            save("state.json", state)  # sofort sichern, damit nach einem Absturz nichts doppelt kommt
    # alte Einträge aufräumen
    cutoff = (today - dt.timedelta(days=14)).isoformat()
    state["sent"] = {k: v for k, v in state["sent"].items() if v[:10] >= cutoff}
    save("state.json", state)
    print("Fertig.")
    return 1 if feed_failed else 0


if __name__ == "__main__":
    sys.exit(main())
