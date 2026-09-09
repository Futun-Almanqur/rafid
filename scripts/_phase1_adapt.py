"""Phase 1 — the domain-constant adaptation of the vendored gateway.

Run once. Every replacement is asserted, so a rename that silently matched
nothing fails loudly instead of leaving Murshid's vocabulary in the file.

    python scripts/_phase1_adapt.py

This script is the record of what was changed and is committed alongside the
result, so the adaptation is reviewable as a diff rather than as a claim.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRAIN = ROOT / "gateway" / "app" / "brain.py"
MAIN = ROOT / "gateway" / "app" / "main.py"

# (file, old, new, expected_count)  -- expected_count None means "at least one"
EDITS: list[tuple[Path, str, str, int | None]] = []


def edit(path: Path, old: str, new: str, count: int | None = None) -> None:
    EDITS.append((path, old, new, count))


# --- 1. Location list: Saudi cities -> Wadi University campuses -------------
edit(
    BRAIN,
    '''CITIES = {
    "Riyadh": ["riyadh", "الرياض"],
    "Jeddah": ["jeddah", "jedda", "جدة"],
    "Makkah": ["makkah", "mecca", "مكة"],
    "Dammam": ["dammam", "الدمام"],
    "Madinah": ["madinah", "medina", "المدينة"],
    "Abha": ["abha", "أبها", "ابها"],
    "Tabuk": ["tabuk", "تبوك"],
    "Buraidah": ["buraidah", "بريدة"],
}''',
    '''CAMPUSES = {
    "Main": ["main campus", "main", "المقر الرئيسي", "الحرم الرئيسي"],
    "North": ["north campus", "north", "الحرم الشمالي", "الشمالي"],
    "Medical": ["medical campus", "medical", "الحرم الطبي", "الطبي"],
    "Online": ["online", "remote", "distance", "عن بعد", "الانتساب"],
}''',
    1,
)
edit(BRAIN, "def detect_city(text: str) -> str:", "def detect_campus(text: str) -> str:", 1)
edit(
    BRAIN,
    """    low = text.lower()
    for canonical, forms in CITIES.items():""",
    """    low = text.lower()
    for canonical, forms in CAMPUSES.items():""",
    1,
)
edit(BRAIN, "city = detect_city(message)", "campus = detect_campus(message)", 2)

# --- 2. Identifier patterns -------------------------------------------------
# The reference implementation matches realistic Saudi national-ID, mobile and
# IBAN patterns. We do not reproduce those: every identifier here is
# unmistakably fictional, and the privacy problem this project demonstrates is
# session ownership, which works identically either way.
edit(
    BRAIN,
    '''REFERENCE = re.compile(r"\\b[A-Z]{2}\\d{8}\\b")
NATIONAL_ID = re.compile(r"\\b[12]\\d{9}\\b")
PHONE = re.compile(r"(?:\\+?966|0)5\\d{8}\\b")''',
    '''REFERENCE = re.compile(r"\\bWU-REQ-\\d{6}\\b")
STUDENT_ID = re.compile(r"\\bWU-STU-\\d{6}\\b")
STUDENT_EMAIL = re.compile(r"\\bWU-STU-\\d{6}@students\\.wadi\\.example\\b")''',
    1,
)

# --- 3. Service-type taxonomy ----------------------------------------------
edit(
    BRAIN,
    '''SERVICE_TYPE_HINTS = {
    "commercial_licence": ["commercial", "cr", "business", "trade", "سجل تجاري", "رخصة تجارية", "مؤسسة"],
    "civil_records": ["identity", "id card", "birth", "civil", "family", "هوية", "ميلاد", "أحوال", "الأحوال المدنية"],
    "traffic_services": ["driving", "vehicle", "car", "traffic", "قيادة", "مركبة", "سيارة", "مرور"],
    "municipal_permits": ["building permit", "municipal", "shop", "restaurant", "بناء", "بلدية", "محل", "مطعم"],
}''',
    '''SERVICE_TYPE_HINTS = {
    "records": ["transcript", "certificate", "enrolment letter", "record",
                "سجل أكاديمي", "شهادة", "إفادة", "تعريف"],
    "enrolment": ["register", "registration", "withdraw", "withdrawal", "defer",
                  "deferral", "add", "drop", "course",
                  "تسجيل", "انسحاب", "تأجيل", "حذف", "إضافة", "مقرر"],
    "finance": ["tuition", "fee", "instalment", "installment", "payment", "fine",
                "رسوم", "قسط", "تقسيط", "سداد", "غرامة"],
    "campus_services": ["id card", "parking", "housing", "library", "permit",
                        "بطاقة جامعية", "مواقف", "سكن", "مكتبة", "تصريح"],
}''',
    1,
)
edit(
    BRAIN,
    '''    if entry is not None and entry.service_type in {
        "commercial_licence",
        "civil_records",
        "traffic_services",
        "municipal_permits",
    }:''',
    '''    if entry is not None and entry.service_type in {
        "records",
        "enrolment",
        "finance",
        "campus_services",
    }:''',
    1,
)

# --- 4. Fallback contact ----------------------------------------------------
edit(BRAIN, 'r"service_centre:\\s*(.+)"', 'r"registrar_contact:\\s*(.+)"', 1)
edit(
    BRAIN,
    '''    return "199" if language == "ar" else "the service centre (199)"''',
    '''    return "قبول وتسجيل" if language == "ar" else "Admissions & Registration"''',
    1,
)
edit(
    BRAIN,
    '''DONT_KNOW = {
    "en": (
        "I don't have that information in the service directory, so I won't guess. "
        "Please check with the service centre: {centre}"
    ),
    "ar": (
        "لا تتوفر لدي هذه المعلومة في دليل الخدمات، ولن أخمّن. "
        "يرجى مراجعة مركز الخدمة: {centre}"
    ),
}''',
    '''DONT_KNOW = {
    "en": (
        "I don't have that information in the service directory, so I won't guess. "
        "Please check with {centre}"
    ),
    "ar": (
        "لا تتوفر لدي هذه المعلومة في دليل الخدمات، ولن أخمّن. "
        "يرجى مراجعة {centre}"
    ),
}''',
    1,
)

# --- 5. Prompt tag ----------------------------------------------------------
edit(BRAIN, '"citizen_message"', '"student_message"', None)

# --- 6. Extraction fields ---------------------------------------------------
edit(
    BRAIN,
    """    national_id = NATIONAL_ID.search(message)
    phone = PHONE.search(message)""",
    """    student_id = STUDENT_ID.search(message)
    email = STUDENT_EMAIL.search(message)""",
    1,
)
edit(
    BRAIN,
    '''    summary = (
        f"Citizen asks about {entry.title.lower()}" if entry else "Citizen asks about a government service"
    )
    if city != "unknown":
        summary += f" in {city}"
    summary += "."''',
    '''    summary = (
        f"Student asks about {entry.title.lower()}" if entry else "Student asks about a campus service"
    )
    if campus != "unknown":
        summary += f" at the {campus} campus"
    summary += "."''',
    1,
)
edit(
    BRAIN,
    '''    ticket: dict[str, Any] = {
        "service_type": service_type,
        "summary_en": summary,
        "city": city,
        "urgency": urgency,
        "language": language,
        "applicant": {
            "full_name": name or ("Unnamed citizen" if language == "en" else "مواطن لم يذكر اسمه"),
            "national_id": national_id.group() if national_id else None,
            "phone": phone.group() if phone else None,
        },
        "needs_human": needs_human,
    }''',
    '''    ticket: dict[str, Any] = {
        "service_type": service_type,
        "summary_en": summary,
        "campus": campus,
        "urgency": urgency,
        "language": language,
        "student": {
            "full_name": name or ("Unnamed student" if language == "en" else "طالب لم يذكر اسمه"),
            "student_id": student_id.group() if student_id else None,
            "email": email.group() if email else None,
        },
        "needs_human": needs_human,
    }''',
    1,
)
edit(
    BRAIN,
    '''            if mode == 0:
                ticket["city"] = "Al Khobar"  # not in the enum
            elif mode == 1:
                ticket["applicant"]["national_id"] = "9" + "12345678"  # wrong leading digit
            else:
                ticket["urgency"] = "high"  # not in the enum''',
    '''            if mode == 0:
                ticket["campus"] = "South"  # not in the enum
            elif mode == 1:
                ticket["student"]["student_id"] = "WU-STU-12"  # malformed identifier
            else:
                ticket["urgency"] = "high"  # not in the enum''',
    1,
)
edit(
    BRAIN,
    '''            if ticket["city"] == "unknown":
                ticket["city"] = "Riyadh"''',
    '''            if ticket["campus"] == "unknown":
                ticket["campus"] = "Main"''',
    1,
)

# --- 7. Model tier name -----------------------------------------------------
# Not in the original ADR log. Found during phase 1: the open-weight tier is
# named after the reference implementation, so it is a domain constant too.
edit(BRAIN, "murshid-onprem", "wadi-onprem", None)
edit(MAIN, "murshid-onprem", "wadi-onprem", None)

# --- 8. Invented fees -------------------------------------------------------
# These must be amounts that appear nowhere in OUR directory, or the
# out-of-directory guess would accidentally be grounded.
edit(
    BRAIN,
    '''INVENTED_FEES_EN = ["SAR 150", "SAR 250", "SAR 75"]
INVENTED_FEES_AR = ["١٥٠ ريالاً", "٢٥٠ ريالاً", "٧٥ ريالاً"]''',
    '''INVENTED_FEES_EN = ["SAR 310", "SAR 145", "SAR 890"]
INVENTED_FEES_AR = ["٣١٠ ريالاً", "١٤٥ ريالاً", "٨٩٠ ريالاً"]''',
    1,
)

# --- 9. Tool contracts the simulator answers against ------------------------
# ADR 004 log row "tool-result payload keys". The gateway decides which tool to
# call by name, so the names it knows must be ours. This does NOT build the
# tools — that is phase 10. It only teaches the simulator our vocabulary.
edit(
    MAIN,
    """    # On a repair turn the LAST user message is the validation feedback, not the
    # citizen. Extracting from it produces a ticket about the error message —
    # complete with a city lifted out of the enum listed in the error. Repair""",
    """    # On a repair turn the LAST user message is the validation feedback, not the
    # student. Extracting from it produces a request about the error message —
    # complete with a campus lifted out of the enum listed in the error. Repair""",
    1,
)
edit(BRAIN, "escalate_to_agent", "escalate_to_registrar", None)
edit(BRAIN, "check_application_status", "check_my_request_status", None)
edit(BRAIN, "book_appointment", "book_advisor_appointment", None)
edit(BRAIN, '"citizen asked for a human agent"', '"student asked for a human"', 1)
edit(BRAIN, '"citizen may be in distress"', '"student may be in distress"', 1)
edit(
    BRAIN,
    'else "Happy to check — what is the reference number? It is two letters and eight digits, e.g. CR12345678."',
    'else "Happy to check — what is the request reference? It looks like WU-REQ-123456."',
    1,
)
edit(
    BRAIN,
    '''            service_type = _service_type(message, None)
            if service_type == "other":
                service_type = "civil_records"
            args = {"service_type": service_type, "city": city, "date": date.group()}''',
    '''            service_type = _service_type(message, None)
            if service_type == "other":
                service_type = "enrolment"
            args = {"service_type": service_type, "campus": campus, "date": date.group()}''',
    1,
)
edit(
    BRAIN,
    '''        missing = []
        if city == "unknown":
            missing.append("المدينة" if language == "ar" else "the city")''',
    '''        missing = []
        if campus == "unknown":
            missing.append("الحرم الجامعي" if language == "ar" else "the campus")''',
    1,
)
edit(
    BRAIN,
    '''        if date and city != "unknown" and confirmed:''',
    '''        if date and campus != "unknown" and confirmed:''',
    1,
)
edit(
    BRAIN,
    '''                f"سأحجز موعداً في {city} بتاريخ {date.group()}. هل تؤكد؟"
                if language == "ar"
                else f"I'll book an appointment in {city} on {date.group()}. Shall I confirm?"''',
    '''                f"سأحجز موعداً في {campus} بتاريخ {date.group()}. هل تؤكد؟"
                if language == "ar"
                else f"I'll book an appointment at the {campus} campus on {date.group()}. Shall I confirm?"''',
    1,
)


def main() -> int:
    texts: dict[Path, str] = {}
    failures: list[str] = []
    for path, old, new, expected in EDITS:
        text = texts.setdefault(path, path.read_text(encoding="utf-8"))
        found = text.count(old)
        if found == 0:
            failures.append(f"NO MATCH  {path.name}: {old.splitlines()[0][:70]!r}")
            continue
        if expected is not None and found != expected:
            failures.append(
                f"COUNT {found}!={expected}  {path.name}: {old.splitlines()[0][:70]!r}"
            )
            continue
        texts[path] = text.replace(old, new)
        print(f"ok  {path.name:<9} x{found}  {old.splitlines()[0][:64]}")

    if failures:
        print("\nFAILED — nothing written:")
        for f in failures:
            print("   ", f)
        return 1

    # The sweep: after adaptation, no trace of the reference implementation's
    # domain vocabulary may remain. This is the check that turns "we adapted it"
    # into something falsifiable.
    residue: list[str] = []
    for path, text in texts.items():
        for term in ("murshid", "citizen", "national_id", "iban"):
            hits = [
                f"{path.name}:{n}"
                for n, line in enumerate(text.splitlines(), 1)
                if term in line.lower()
            ]
            if hits:
                residue.append(f"{term!r} still present at {', '.join(hits)}")
    if residue:
        print("\nRESIDUE — nothing written:")
        for r in residue:
            print("   ", r)
        return 1

    for path, text in texts.items():
        path.write_text(text, encoding="utf-8")
    print(f"\nsweep clean: no 'murshid', 'citizen', 'national_id' or 'iban' remains")
    print(f"wrote {len(texts)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
