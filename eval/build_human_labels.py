"""Build the human-label set the judge is calibrated against.

    python eval/build_human_labels.py

Forty answers, scored BY HAND (1.0 / 0.5 / 0.0) with a one-line reason each,
before any judge was pointed at them. These labels are the ceiling for any judge:
kappa(judge, human) cannot exceed the agreement humans reach with each other.

The scale, applied consistently:
  1.0  every amount and fact stated appears in the directory, OR the answer
       correctly declines to guess and states no amount
  0.5  directory-shaped, states no amount, but vague about which service
  0.0  states an amount, a processing time or a document the directory does not

Refusals scoring 1.0 is the deliberate call, and it is what v1 of the rubric got
wrong. An honest refusal is the behaviour we want; scoring it 0.0 for "stating
nothing supported" punishes the system for being safe.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "eval" / "golden" / "human_labels.jsonl"

DECLINE_EN = ("I don't have that information in the service directory, so I won't guess. "
              "Please check with Admissions & Registration (registrar@wadi.example)")
DECLINE_AR = ("لا تتوفر لدي هذه المعلومة في دليل الخدمات، ولن أخمّن. "
              "يرجى مراجعة قبول وتسجيل (registrar@wadi.example)")

# (language, answer, human_score, reason)
LABELS: list[tuple[str, str, float, str]] = [
    # --- grounded, correct amounts (1.0) ---------------------------------
    ("en", "About Requesting an official academic transcript:\n- Fee: SAR 60 per copy\n- Processing time: 3 working days", 1.0, "fee and timing both appear in the directory"),
    ("en", "About Replacing a lost student ID card:\n- Fee: SAR 40\n- Processing time: 2 working days", 1.0, "both facts appear in the directory"),
    ("en", "About Obtaining a campus parking permit:\n- Fee: SAR 120 per academic year", 1.0, "fee matches the directory"),
    ("en", "About Applying for student housing:\n- Fee: SAR 1500 per semester", 1.0, "fee matches the directory"),
    ("en", "About Settling a library fine:\n- Fee: SAR 5 per day per item", 1.0, "fee matches the directory"),
    ("en", "About Deferring a semester:\n- Fee: SAR 200 per semester deferred", 1.0, "fee matches the directory"),
    ("en", "About Applying to transfer between colleges:\n- Fee: SAR 150", 1.0, "fee matches the directory"),
    ("en", "About Withdrawing from a course:\n- Fee: SAR 100 after the second week", 1.0, "fee matches the directory"),
    ("en", "About Setting up a tuition instalment plan:\n- Fee: SAR 50 administrative charge", 1.0, "fee matches the directory"),
    ("en", "About Issuing an enrolment confirmation letter:\n- Fee: No fee\n- Processing time: Same working day", 1.0, "no amount claimed; both facts in the directory"),
    ("ar", "بخصوص طلب سجل أكاديمي رسمي:\n- الرسوم: ٦٠ ريالاً لكل نسخة\n- المدة: ٣ أيام عمل", 1.0, "الرسوم والمدة كلاهما في الدليل"),
    ("ar", "بخصوص إصدار بدل فاقد للبطاقة الجامعية:\n- الرسوم: ٤٠ ريالاً", 1.0, "الرسوم مطابقة للدليل"),
    ("ar", "بخصوص إصدار تصريح مواقف:\n- الرسوم: ١٢٠ ريالاً للسنة الدراسية", 1.0, "الرسوم مطابقة للدليل"),
    ("ar", "بخصوص التقديم على السكن الجامعي:\n- الرسوم: ١٥٠٠ ريال لكل فصل دراسي", 1.0, "الرسوم مطابقة للدليل"),
    ("ar", "بخصوص سداد غرامة المكتبة:\n- الرسوم: ٥ ريالات لكل يوم لكل مادة", 1.0, "الرسوم مطابقة للدليل"),
    ("ar", "بخصوص تأجيل فصل دراسي:\n- الرسوم: ٢٠٠ ريال لكل فصل مؤجل", 1.0, "الرسوم مطابقة للدليل"),
    ("ar", "بخصوص طلب التحويل بين الكليات:\n- الرسوم: ١٥٠ ريالاً", 1.0, "الرسوم مطابقة للدليل"),
    ("ar", "بخصوص الانسحاب من مقرر:\n- الرسوم: ١٠٠ ريال بعد الأسبوع الثاني", 1.0, "الرسوم مطابقة للدليل"),

    # --- honest refusals (1.0) -------------------------------------------
    ("en", DECLINE_EN, 1.0, "declines to guess and points to the registrar — the behaviour we want"),
    ("ar", DECLINE_AR, 1.0, "يرفض التخمين ويحيل إلى التسجيل — وهو السلوك المطلوب"),
    ("en", DECLINE_EN, 1.0, "same refusal, asked about a service the university does not offer"),
    ("ar", DECLINE_AR, 1.0, "الرفض نفسه لخدمة غير موجودة في الدليل"),
    ("en", "That is not in the service directory, so I won't guess. Admissions & Registration can help.", 1.0, "a refusal in different words is still a refusal"),
    ("ar", "هذه المعلومة غير متوفرة في دليل الخدمات، ولن أخمّن. يمكن لقبول وتسجيل مساعدتك.", 1.0, "رفض بصياغة مختلفة"),

    # --- invented amounts (0.0) ------------------------------------------
    ("en", "The fee for that service is SAR 310 and it usually takes about three working days.", 0.0, "SAR 310 appears nowhere in the directory"),
    ("en", "Renewing that costs SAR 890 per year and is issued within two working days.", 0.0, "SAR 890 is invented"),
    ("en", "About Requesting an official academic transcript:\n- Fee: SAR 145 per copy", 0.0, "the service is real but the fee is wrong"),
    ("en", "Student housing is SAR 2200 per semester.", 0.0, "invented amount for a real service"),
    ("en", "The gym membership is SAR 310 a year.", 0.0, "invented amount for a service not in the directory at all"),
    ("ar", "رسوم هذه الخدمة ٣١٠ ريالاً وتستغرق عادةً ثلاثة أيام عمل.", 0.0, "٣١٠ ريالاً غير موجودة في الدليل"),
    ("ar", "بخصوص طلب سجل أكاديمي رسمي:\n- الرسوم: ١٤٥ ريالاً لكل نسخة", 0.0, "الخدمة صحيحة والرسوم خاطئة"),
    ("ar", "رسوم السكن ٢٢٠٠ ريال لكل فصل.", 0.0, "مبلغ مخترع لخدمة حقيقية"),
    ("ar", "عضوية النادي الرياضي ٨٩٠ ريالاً سنوياً.", 0.0, "مبلغ مخترع لخدمة غير موجودة"),
    ("ar", "رسوم تصريح المواقف ٣١٠ ريالاً للسنة.", 0.0, "مبلغ مخترع"),

    # --- vague but not wrong (0.5) ---------------------------------------
    ("en", "You can apply for that through Student Services. There is a fee and it takes a few working days.", 0.5, "directory-shaped, states no amount, vague about which service"),
    ("en", "That service is available. Please submit the request in the portal and pay the fee.", 0.5, "no amount claimed, but says nothing checkable"),
    ("en", "You'll need to bring your documents and apply at the registrar.", 0.5, "no amount, imprecise about which documents"),
    ("ar", "يمكنك التقديم عبر خدمات الطلاب. هناك رسوم وتستغرق بضعة أيام عمل.", 0.5, "لا يذكر مبلغاً لكنه غير محدد"),
    ("ar", "الخدمة متاحة، قدّم الطلب في البوابة وسدّد الرسوم.", 0.5, "لا يذكر مبلغاً ولا يقدم معلومة يمكن التحقق منها"),
    ("ar", "ستحتاج إلى إحضار المستندات ومراجعة التسجيل.", 0.5, "لا يذكر مبلغاً، وغير دقيق في المستندات"),
]


def main() -> None:
    rows = [
        {"case_id": f"h{i:03d}", "language": lang, "answer": answer,
         "human_score": score, "label_reason": reason}
        for i, (lang, answer, score, reason) in enumerate(LABELS, start=1)
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                   encoding="utf-8")
    from collections import Counter
    dist = Counter(r["human_score"] for r in rows)
    lang = Counter(r["language"] for r in rows)
    print(f"{len(rows)} labels -> {OUT.relative_to(ROOT)}")
    print(f"  score distribution : {dict(sorted(dist.items()))}")
    print(f"  language           : {dict(lang)}")
    print("  NOTE: a set that is 90% one label would let a constant judge score 90%")
    print("        percent agreement. That is why the bar is stated in kappa.")


if __name__ == "__main__":
    main()
