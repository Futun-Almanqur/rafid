"""The one validated request object for this domain: StudentRequest.

Strict on purpose. Enums where the domain is closed, patterns where the format is
fixed, and `extra="forbid"` so an invented field is a validation error rather than
a silent addition. Relaxing any of this to make a failing corpus go green is the
validation wall dismantled — and it reads as a fix in the diff.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ServiceType = Literal["records", "enrolment", "finance", "campus_services", "other"]
Campus = Literal["Main", "North", "Medical", "Online", "unknown"]
Urgency = Literal["routine", "urgent", "emergency"]
Language = Literal["en", "ar"]


class Student(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = None
    student_id: str | None = Field(default=None, pattern=r"^WU-STU-\d{6}$")
    email: str | None = Field(default=None, pattern=r"^WU-STU-\d{6}@students\.wadi\.example$")


class StudentRequest(BaseModel):
    """What the assistant extracts from a free-text message before it acts."""

    model_config = ConfigDict(extra="forbid")

    service_type: ServiceType
    summary_en: str = Field(min_length=3, max_length=300)
    campus: Campus = "unknown"
    urgency: Urgency = "routine"
    language: Language
    student: Student = Field(default_factory=Student)
    needs_human: bool = False

    @staticmethod
    def json_schema_for_provider() -> dict:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "student_request",
                "strict": True,
                "schema": StudentRequest.model_json_schema(),
            },
        }
