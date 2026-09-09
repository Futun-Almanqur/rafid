"""The whole Rafid request path as five named, individually testable stages.

    guard_input | route_intent | (service_info | workflow | escalate) | guard_output

The rule that keeps this honest: **if a stage cannot be run alone in a test, it is
not a stage.** ``tests/test_stages.py`` constructs each one with stubs and no
network, and the notebook demonstrates each one alone in its own cell.

A note on the numbering. The course's own test file groups the three handlers
under one banner labelled "stage 3: the handlers" and labels the output guard
"stage 5", leaving stage 4 unlabelled. We show each handler in its own cell,
which is what the rule above actually requires, and we do not depend on which of
the middle two is called 3 and which 4.

The three layers inside ``guard_input`` — deterministic, masking, classifier — are
LAYERS, not stages.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from rafid.domain.session import Session
from rafid.guards.input_guards import GuardedInput, InputGuard
from rafid.guards.output_guards import OutputGuard
from rafid.llm.interfaces import LLMClient, Message
from rafid.observability import get_logger, new_trace_id
from rafid.pipeline.router import IntentRouter
from rafid.pipeline.service_info import ServiceInfoHandler
from rafid.pipeline.tool_loop import run_tool_loop
from rafid.pipeline.types import Reply
from rafid.prompts.registry import load_prompt

log = get_logger(__name__)


class EscalationHandler:
    """Humans are not a model call — so this stage makes none."""

    def handoff(self, guarded: GuardedInput, session: Session) -> Reply:
        from rafid.tools.registry import by_name
        from rafid.pipeline.tool_loop import execute_tool

        tool = by_name("escalate_to_registrar")
        result = execute_tool(
            tool,
            {"summary": guarded.text[:200], "reason": "student_request"},
            session,
            iteration=1,
        )
        text = (
            "سأحوّلك إلى موظف في قبول وتسجيل الآن، وسيصلك رد قريباً."
            if guarded.language == "ar"
            else "I'm passing you to someone in Admissions & Registration now; "
                 "they'll be in touch shortly."
        )
        return Reply(
            text=text,
            intent="escalate",
            language=guarded.language,
            escalated=True,
            tool_calls=[dict(session.tool_trace[-1], result_ok="error" not in result)],
        )


class WorkflowHandler:
    """The path that can act: the bounded tool loop behind the gate."""

    def __init__(self, client: LLMClient, *, prompt_ref: str = "service_workflow.v1") -> None:
        self._client = client
        self.prompt_ref = prompt_ref

    def run(self, guarded: GuardedInput, session: Session) -> Reply:
        from rafid.domain.directory import rendered_directory

        prompt = load_prompt(self.prompt_ref)
        messages = [
            Message(role="system",
                    content=prompt.render(service_directory=rendered_directory(guarded.language))),
            Message(role="user", content=f"<student_message>{guarded.text}</student_message>"),
        ]
        result = run_tool_loop(self._client, messages, session)
        return Reply(
            text=result.text or "",
            intent="my_request",
            language=guarded.language,
            escalated=result.terminal,
            tool_calls=list(result.calls),
            prompt_version=self.prompt_ref,
        )


@dataclass
class Dependencies:
    input_guard: InputGuard
    router: IntentRouter
    service_info: ServiceInfoHandler
    workflow: WorkflowHandler
    output_guard: OutputGuard
    escalation: EscalationHandler | None = None


class Rafid:
    """The application. One entry point, five stages, and the harness calls THIS."""

    def __init__(self, deps: Dependencies) -> None:
        self.deps = deps
        self.escalation = deps.escalation or EscalationHandler()

    def ask(self, text: str, session: Session | None = None) -> Reply:
        session = session or Session()
        new_trace_id()
        started = time.perf_counter()
        stages: list[str] = []

        # --- stage 1 --------------------------------------------------
        stages.append("guard_input")
        guarded = self.deps.input_guard.check(text, session)
        if guarded.blocked:
            return Reply(
                text=guarded.refusal or "",
                intent="refused",
                language=guarded.language,
                blocked=True,
                guard_layer=guarded.verdict.layer,
                guard_category=guarded.verdict.category,
                latency_ms=(time.perf_counter() - started) * 1000,
                stages=stages,
            )

        # --- stage 2 --------------------------------------------------
        stages.append("route_intent")
        intent = self.deps.router.classify(guarded.text)

        # --- stages 3 / 4 / escalate ----------------------------------
        if intent == "escalate":
            stages.append("escalate")
            reply = self.escalation.handoff(guarded, session)
        elif intent == "my_request":
            stages.append("workflow")
            reply = self.deps.workflow.run(guarded, session)
        else:
            stages.append("service_info")
            response = self.deps.service_info.answer(guarded, session)
            reply = Reply(
                text=response.text or "",
                intent="service_info",
                language=guarded.language,
                model_id=response.model_id,
                route=response.route,
                prompt_version=self.deps.service_info.prompt_ref,
            )

        # --- stage 5 --------------------------------------------------
        stages.append("guard_output")
        text_out, verdict = self.deps.output_guard.apply(reply.text, language=guarded.language, session=session)
        reply.text = text_out
        reply.output_guard_category = verdict.category
        if not verdict.allowed:
            reply.blocked = True
        reply.latency_ms = (time.perf_counter() - started) * 1000
        reply.stages = stages
        return reply


def build_assistant(client: LLMClient, *, guard_client: LLMClient | None = None,
                    classifier_enabled: bool = True, prompt_ref: str = "answer_service.v2") -> Rafid:
    """THE entry point the notebook, the demo and the eval harness all use.

    One construction path. A harness with its own simplified copy of the request
    path drifts within weeks, and then it is measuring the copy.
    """
    guard_client = guard_client or client
    return Rafid(
        Dependencies(
            input_guard=InputGuard(guard_client, classifier_enabled=classifier_enabled),
            router=IntentRouter(guard_client),
            service_info=ServiceInfoHandler(client, prompt_ref=prompt_ref),
            workflow=WorkflowHandler(client),
            output_guard=OutputGuard(),
            escalation=EscalationHandler(),
        )
    )
