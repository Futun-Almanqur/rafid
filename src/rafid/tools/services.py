"""Fixture back-ends the tools call. Deterministic, offline, fictional.

In a real deployment these are the student record system, the appointment system
and the registrar queue. Here they are dictionaries — which is enough, because
what the capstone is scoring is the *gate* in front of them, not them.

Every identifier is fictional: WU-STU-000123, WU-REQ-123456, WU-APT-000077.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

#: Which student each request belongs to. This is the ownership source of truth
#: that Session.owns() consults — the session decides, using this record.
REQUESTS: dict[str, dict] = {
    "WU-REQ-100045": {
        "owner": "WU-STU-000123", "service": "transcript_request",
        "status": "in_progress", "status_ar": "قيد التنفيذ", "updated": "2026-09-05",
        "note": "Awaiting fee payment confirmation.",
    },
    "WU-REQ-100046": {
        "owner": "WU-STU-000123", "service": "enrolment_letter",
        "status": "completed", "status_ar": "مكتمل", "updated": "2026-09-02",
        "note": "Letter available for download.",
    },
    "WU-REQ-777001": {
        "owner": "WU-STU-000999", "service": "graduation_clearance",
        "status": "in_progress", "status_ar": "قيد التنفيذ", "updated": "2026-09-07",
        "note": "Library clearance outstanding.",
    },
}

CAMPUSES = ["Main", "North", "Medical", "Online"]
SLOTS = ["morning", "afternoon"]


def owner_of_request(reference: str) -> str | None:
    record = REQUESTS.get(reference)
    return record["owner"] if record else None


def lookup_service_information(service_id: str, language: str = "en") -> dict:
    """Public: what the university offers. No student data involved."""
    from rafid.domain.directory import load_directory

    entry = load_directory().by_id(service_id)
    if entry is None:
        return {"error": "unknown_service", "hint": "That service is not in the directory."}
    return {
        "service_id": entry.id,
        "title": entry.title(language),
        "fee": entry.fee_ar if language == "ar" else entry.fee,
        "processing_time": entry.processing_time_ar if language == "ar" else entry.processing_time,
    }


def check_my_request_status(reference: str, language: str = "en") -> dict:
    """Private: one student's own request. Reached only through the gate."""
    record = REQUESTS.get(reference)
    if record is None:
        return {"error": "not_found", "hint": "I could not find a request with that reference."}
    return {
        "reference": reference,
        "service": record["service"],
        "status": record["status_ar"] if language == "ar" else record["status"],
        "updated": record["updated"],
        "note": record["note"],
    }


def book_advisor_appointment(campus: str, date: str, slot: str, **_) -> dict:
    """Side-effecting: creates something. Reached only through the gate."""
    if campus not in CAMPUSES:
        return {"error": "unknown_campus", "hint": f"Campus must be one of {CAMPUSES}."}
    if slot not in SLOTS:
        return {"error": "unknown_slot", "hint": f"Slot must be one of {SLOTS}."}
    digest = hashlib.sha256(f"{campus}{date}{slot}".encode()).hexdigest()[:6]
    return {
        "confirmation": f"WU-APT-{int(digest, 16) % 1000000:06d}",
        "campus": campus,
        "date": date,
        "slot": slot,
    }


def escalate_to_registrar(summary: str, reason: str = "student_request", **_) -> dict:
    """Terminal: hands the conversation to a human. Makes no model call."""
    return {
        "handoff": True,
        "reason": reason,
        "summary": summary[:200],
        "queued_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
