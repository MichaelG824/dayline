"""Getting one structured tool call out of the model.

The current models reject ``tool_choice`` of type ``tool``/``any`` (forcing a
specific tool), so the tool is offered with ``auto`` and the system prompt says
to call it. If a reply comes back as text instead, the model is asked once
more, explicitly. Callers still validate the tool input themselves.
"""

from __future__ import annotations

from typing import Any, cast

import anthropic

# The first try plus one explicit nudge.
MAX_TOOL_ATTEMPTS = 2


def find_tool_use(response: Any, tool_name: str) -> Any | None:
    """The first ``tool_use`` block calling ``tool_name``, if any."""
    return next(
        (b for b in response.content if b.type == "tool_use" and b.name == tool_name),
        None,
    )


def nudge(tool_name: str) -> dict[str, Any]:
    """The follow-up user turn sent when a reply skipped the tool."""
    return {
        "role": "user",
        "content": f"Respond only by calling the {tool_name} tool, with nothing else.",
    }


def request_tool_call(
    client: anthropic.Anthropic,
    *,
    model: str,
    system: str,
    tool: dict[str, Any],
    messages: list[dict[str, Any]],
    max_tokens: int = 8192,
) -> Any | None:
    """Call the model until it calls ``tool`` (up to ``MAX_TOOL_ATTEMPTS``).
    Returns the ``tool_use`` block, or ``None`` if it never did."""
    history = list(messages)
    for _ in range(MAX_TOOL_ATTEMPTS):
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=cast(Any, [tool]),
            messages=cast(Any, history),
        )
        tool_use = find_tool_use(response, tool["name"])
        if tool_use is not None:
            return tool_use
        history += [{"role": "assistant", "content": response.content}, nudge(tool["name"])]
    return None
