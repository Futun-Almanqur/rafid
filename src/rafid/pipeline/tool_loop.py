"""The bounded tool loop, and the gate every tool call passes through.

Three rules, all of them things that go wrong when they are left implicit:

* **the loop is bounded.** ``MAX_ITERATIONS`` is enforced here. A loop whose exit
  condition is "the model stops asking" has no exit condition.
* **every call passes the gate**, and the gate dispatches on ``tool.auth_policy``
  alone. Not on the risk class, not on the tool name, not on anything the model
  said.
* **every call is logged with its risk class and its loop iteration.** That is a
  graded requirement, and it is also the only way to answer "what did it actually
  do?" after the fact.

The model never executes a tool. It asks; the application decides and runs.
"""

from __future__ import annotations

import json

from rafid.domain.session import Session
from rafid.llm.interfaces import LLMClient, LLMRequest, Message
from rafid.observability import get_logger
from rafid.tools.registry import Tool, by_name, schemas

log = get_logger(__name__)

#: Lookup -> confirm -> act -> summarise. Four is enough for every flow Rafid has.
MAX_ITERATIONS = 4


class ToolLoopResult:
    def __init__(self) -> None:
        self.text: str | None = None
        self.calls: list[dict] = []
        self.iterations: int = 0
        self.stopped_because: str = ""
        self.terminal: bool = False


def execute_tool(tool: Tool, args: dict, session: Session, *, iteration: int) -> dict:
    """Gate, then run. Never the other way round."""
    verdict = session.authorize(tool, args)
    record = {
        "tool": tool.name,
        "risk": tool.risk,
        "visibility": tool.visibility,
        "auth_policy": tool.auth_policy,
        "iteration": iteration,
        "args": args,
        "allowed": verdict.allowed,
        "reason": verdict.reason,
    }
    session.tool_trace.append(record)
    log.info("tool_call", **{k: v for k, v in record.items() if k != "args"})

    if not verdict.allowed:
        return {"error": verdict.reason, "hint": verdict.user_hint}

    try:
        result = tool.fn(**args)
    except TypeError as exc:
        # The model fumbled the tool contract — a missing or unexpected argument.
        # That is a bad turn, not a crash: the application tells the model what it
        # got wrong and the loop gets another bounded chance.
        log.warning("tool_contract_error", tool=tool.name, error=str(exc)[:120])
        return {"error": "bad_arguments", "hint": f"{tool.name}: {exc}"}

    if tool.risk == "side_effecting" and "error" not in result:
        session.record_side_effect(tool.name, args, result)
    return result


def run_tool_loop(
    client: LLMClient,
    messages: list[Message],
    session: Session,
    *,
    model_alias: str = "rafid-flagship",
    max_tokens: int = 500,
    max_iterations: int = MAX_ITERATIONS,
) -> ToolLoopResult:
    out = ToolLoopResult()
    history = list(messages)

    for iteration in range(1, max_iterations + 1):
        out.iterations = iteration
        response = client.complete(
            LLMRequest(
                messages=history,
                model_alias=model_alias,
                max_tokens=max_tokens,
                tools=schemas(),
                cache_prefix_messages=1,
            )
        )

        if not response.tool_calls:
            out.text = response.text
            out.stopped_because = "model_answered"
            return out

        history.append(
            Message(role="assistant", content=response.text or "", tool_calls=response.tool_calls)
        )

        for call in response.tool_calls:
            tool = by_name(call.name)
            if tool is None:
                result = {"error": "unknown_tool", "hint": f"No tool named {call.name}."}
                out.calls.append({"tool": call.name, "risk": "unknown", "iteration": iteration})
            else:
                try:
                    args = json.loads(call.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = execute_tool(tool, args, session, iteration=iteration)
                out.calls.append(session.tool_trace[-1])
                if tool.risk == "terminal" and "error" not in result:
                    out.text = result.get("summary")
                    out.terminal = True
                    out.stopped_because = "terminal_tool"
                    history.append(
                        Message(role="tool", tool_call_id=call.id, name=call.name,
                                content=json.dumps(result, ensure_ascii=False))
                    )
                    return out

            history.append(
                Message(role="tool", tool_call_id=call.id, name=call.name,
                        content=json.dumps(result, ensure_ascii=False))
            )

    out.stopped_because = "iteration_bound"
    log.warning("tool_loop_bound_reached", iterations=out.iterations, session=session.id)
    return out
