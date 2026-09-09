"""Designed refusals: bilingual, specific, and they never echo the payload.

Echoing an attack back is a leak vector and it teaches the attacker what landed.
Every refusal here is written in advance, in both languages, and says what the
student can do next — a refusal that only says "no" is a support ticket.
"""

from __future__ import annotations

REFUSALS: dict[str, dict[str, str]] = {
    "injection": {
        "en": ("I can only help with Wadi University student services — fees, "
               "transcripts, enrolment, appointments. What do you need?"),
        "ar": ("يمكنني المساعدة في خدمات طلاب جامعة الوادي فقط — الرسوم والسجلات "
               "والتسجيل والمواعيد. كيف أساعدك؟"),
    },
    "off_scope": {
        "en": ("That is outside what I can help with. I cover Wadi University "
               "student services. For anything else, Admissions & Registration can help."),
        "ar": ("هذا خارج نطاق مساعدتي. أغطي خدمات طلاب جامعة الوادي. لأي أمر آخر، "
               "يمكن لقبول وتسجيل مساعدتك."),
    },
    "distress": {
        "en": ("It sounds like you are going through something difficult. I am "
               "connecting you with a person in Student Support now."),
        "ar": ("يبدو أنك تمر بوقت صعب. سأحوّلك الآن إلى موظف في دعم الطلاب."),
    },
    "identifier_outbound": {
        "en": ("I cannot include that identifier in a reply. You can see it in your "
               "Student Services account."),
        "ar": ("لا يمكنني إظهار هذا المعرّف في الرد. يمكنك رؤيته في حسابك في خدمات الطلاب."),
    },
    "system_prompt_leak": {
        "en": ("I can't share my configuration. I can help with fees, transcripts, "
               "enrolment and appointments."),
        "ar": ("لا يمكنني مشاركة إعداداتي. يمكنني المساعدة في الرسوم والسجلات "
               "والتسجيل والمواعيد."),
    },
}


def refusal_for(category: str, language: str = "en") -> str:
    entry = REFUSALS.get(category, REFUSALS["off_scope"])
    return entry.get(language, entry["en"])
