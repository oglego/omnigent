"""
Shared translation between OpenAI Responses API format and Chat
Completions format.

This is the bridge layer — every provider adapter speaks Chat
Completions internally, and this module converts to/from the
Responses API format that the public ``Client`` exposes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from omnigent.llms.types import (
    FunctionCallOutput,
    MessageOutput,
    NativeToolOutput,
    OutputText,
    Response,
    ResponseCompletedEvent,
    ResponseReasoningStartedEvent,
    ResponseReasoningTextDeltaEvent,
    ResponseStreamEvent,
    ResponseTextDeltaEvent,
    Usage,
)

# ── Input direction: Responses API -> Chat Completions ────

# Block types that carry plain text in a ``text`` field.
_TEXT_BLOCK_TYPES = {"input_text", "output_text", "text"}


def _translate_content(
    content: list[dict[str, Any]] | str | None,
) -> list[dict[str, Any]] | str | None:
    """
    Translate Responses API content to Chat Completions content.

    If *content* is a list of content blocks, each block is converted
    to Chat Completions format via :func:`_translate_block`. If every
    block is a text block, the result is collapsed to a plain string
    (many providers handle plain strings more efficiently than
    single-element content arrays).

    If *content* is already a string or ``None``, it passes through
    unchanged.

    :param content: Responses API content — a list of content block
        dicts, a plain string, or ``None``.
    :returns: Chat Completions content — a list of Chat Completions
        content parts, a plain string, or ``None``.
    """
    if not isinstance(content, list):
        return content

    translated = [_translate_block(block) for block in content]

    # Collapse to plain string when all blocks are text — avoids
    # unnecessarily sending a content array to providers that only
    # support string content for text-only messages.
    if all(part["type"] == "text" for part in translated):
        return "\n".join(part["text"] for part in translated)

    return translated


def _translate_block(block: dict[str, Any]) -> dict[str, Any]:
    """
    Translate a single Responses API content block to Chat
    Completions format.

    Mapping:

    - ``input_text`` / ``output_text`` / ``text``
      → ``{"type": "text", "text": "..."}``
    - ``input_image`` (with ``image_url``)
      → ``{"type": "image_url", "image_url": {"url": "...", "detail": "..."}}``
    - ``input_file`` (with ``file_data``)
      → passed through as-is (provider adapters handle in Phase 3)
    - Unrecognized types → passed through as-is for forward
      compatibility.

    :param block: A single Responses API content block dict,
        e.g. ``{"type": "input_text", "text": "Hello"}``.
    :returns: A Chat Completions content part dict.
    """
    block_type = block.get("type")

    if block_type in _TEXT_BLOCK_TYPES:
        return {"type": "text", "text": block["text"]}

    if block_type == "input_image":
        image_url_value = block.get("image_url")
        if image_url_value is not None:
            result: dict[str, Any] = {
                "type": "image_url",
                "image_url": {"url": image_url_value},
            }
            detail = block.get("detail")
            if detail is not None:
                result["image_url"]["detail"] = detail
            return result

    # input_file, input_audio, and any future types: pass through
    # as-is. Provider adapters (Phase 3) are responsible for
    # translating these into their native formats.
    return block


def responses_input_to_chat_messages(
    input_items: list[dict[str, Any]],
    instructions: str | None,
) -> list[dict[str, Any]]:
    """
    Convert Responses API input items and instructions into Chat
    Completions messages.

    Responses API keeps function calls as separate items. Chat
    Completions embeds them in assistant messages with a
    ``tool_calls`` array. This function groups consecutive
    ``function_call`` items into a single assistant message.

    :param input_items: Responses API input items, e.g.
        ``[{"role": "user", "content": "Hello"},
        {"type": "function_call", "call_id": "c1", ...}]``.
    :param instructions: System instructions string, or ``None``.
    :returns: Chat Completions message list suitable for any
        provider adapter.
    """
    messages: list[dict[str, Any]] = []

    if instructions:
        messages.append({"role": "system", "content": instructions})

    pending_tool_calls: list[dict[str, Any]] = []

    for item in input_items:
        item_type = item.get("type")

        if item_type == "function_call":
            pending_tool_calls.append(
                {
                    "id": item["call_id"],
                    "type": "function",
                    "function": {
                        "name": item["name"],
                        "arguments": item["arguments"],
                    },
                }
            )
            continue

        # Flush any pending tool calls into an assistant message
        # before processing the next non-function_call item.
        if pending_tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": pending_tool_calls,
                }
            )
            pending_tool_calls = []

        if item_type == "function_call_output":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": item["call_id"],
                    "content": item["output"],
                }
            )
        else:
            # Regular message (user or assistant).
            # Content may be a list of content blocks (multimodal)
            # or a plain string (text-only legacy path).
            raw_content = item.get("content")
            messages.append(
                {
                    "role": item["role"],
                    "content": _translate_content(raw_content),
                }
            )

    # Flush any trailing tool calls
    if pending_tool_calls:
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": pending_tool_calls,
            }
        )

    return messages


# ── Output direction: Chat Completions -> Responses API ───


def chat_response_to_response(
    chat_dict: dict[str, Any],
) -> Response:
    """
    Convert a Chat Completions response dict into a Responses API
    ``Response`` object.

    :param chat_dict: A Chat Completions response with ``choices``,
        ``model``, and optionally ``usage`` keys.
    :returns: A :class:`Response` with ``output``, ``model``, and
        ``usage``.
    """
    output: list[MessageOutput | FunctionCallOutput | NativeToolOutput] = []
    choice = chat_dict["choices"][0]
    message = choice["message"]

    # Text content
    if content := message.get("content"):
        output.append(MessageOutput(content=[OutputText(text=content)]))

    # Tool calls
    for tc in message.get("tool_calls") or []:
        func = tc["function"]
        output.append(
            FunctionCallOutput(
                call_id=tc["id"],
                name=func["name"],
                arguments=func["arguments"],
            )
        )

    usage = _extract_usage(chat_dict.get("usage"))

    return Response(
        output=output,
        model=chat_dict["model"],
        usage=usage,
    )


def _extract_usage(usage_dict: dict[str, Any] | None) -> Usage | None:
    """
    Map Chat Completions usage to Responses API usage.

    :param usage_dict: Chat Completions usage dict with
        ``prompt_tokens``, ``completion_tokens``, ``total_tokens``.
    :returns: A :class:`Usage` instance, or ``None``.
    """
    if not usage_dict:
        return None
    return Usage(
        input_tokens=usage_dict.get("prompt_tokens"),
        output_tokens=usage_dict.get("completion_tokens"),
        total_tokens=usage_dict.get("total_tokens"),
    )


# ── Streaming: Chat Completions chunks -> Responses API events


def _extract_delta_content(
    content: str | list[Any],
) -> tuple[str, str]:
    """
    Extract text and reasoning from a Chat Completions delta content value.

    Handles both plain string content (most providers) and list-of-blocks
    content (Kimi / some Databricks-served models that emit typed content
    blocks in the streaming delta).

    :param content: The ``delta.content`` value from a streaming chunk.
        Either a plain string, e.g. ``"Hello"``, or a list of typed
        blocks, e.g. ``[{"type": "reasoning", "summary": [...]},
        {"type": "text", "text": "hello"}]``.
    :returns: A pair ``(text, reasoning)`` where ``text`` is the
        assistant-visible answer text and ``reasoning`` is the
        chain-of-thought text extracted from ``reasoning`` blocks.
        Either or both may be empty strings.
    """
    if isinstance(content, str):
        return content, ""
    if not isinstance(content, list):
        return "", ""

    text_pieces: list[str] = []
    reasoning_pieces: list[str] = []

    for block in content:
        if isinstance(block, str):
            text_pieces.append(block)
            continue
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type in {"text", "output_text"}:
            t = block.get("text")
            if isinstance(t, str):
                text_pieces.append(t)
        elif block_type == "reasoning":
            # Kimi and OpenAI reasoning blocks carry chain-of-thought
            # text in a ``summary`` list of ``{"type": "summary_text",
            # "text": "..."}`` items.
            for item in block.get("summary") or []:
                if isinstance(item, dict):
                    t = item.get("text")
                    if isinstance(t, str):
                        reasoning_pieces.append(t)

    return "".join(text_pieces), "".join(reasoning_pieces)


class _InlineThinkTagSplitter:
    """
    Splits raw ``<think>...</think>`` tags out of plain-string content
    deltas, buffering across chunk boundaries.

    Some local/self-hosted reasoning models (DeepSeek-R1-distill, QwQ,
    Qwen3 in thinking mode, ...) are commonly served through a bare
    OpenAI-compatible endpoint — a plain ``llama-server``, LM Studio, or
    similar — that does *not* split reasoning into a separate
    ``reasoning_content`` field the way DeepSeek's own API (or a
    reasoning-aware proxy) does. The whole ``<think>...</think>`` block
    instead arrives as literal text inside ``delta.content``.

    Feeding content through this splitter recovers the same
    ``(text, reasoning)`` split that :func:`_extract_delta_content` gets
    for free from typed content blocks, so this reasoning still surfaces
    as a ``ResponseReasoningTextDeltaEvent`` — and is rendered (or
    hidden) by the web UI's "show thinking" toggle like any other
    reasoning model — instead of leaking raw ``<think>`` tags into the
    visible answer. See omnigent-ai/omnigent#2180.

    Only looks for an opening ``<think>`` tag before any real answer
    text has been seen, matching how these models actually behave
    (reasoning, when present, always comes first in the response). Once
    answer text starts, the splitter stops scanning for tags and passes
    the rest of the stream through unchanged — this keeps a literal
    "<think>" that legitimately appears later in an answer from being
    misinterpreted as the start of a reasoning block.
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._in_think = False
        self._seen_answer_text = False
        self._buffer = ""

    def feed(self, chunk: str) -> tuple[str, str]:
        """
        Feed the next plain-text content delta.

        :param chunk: The next piece of ``delta.content`` text.
        :returns: A pair ``(text, reasoning)`` — the portions of *chunk*
            (plus any tag fragment buffered from a previous call) that
            should be surfaced as answer text and as reasoning,
            respectively. Either may be empty.
        """
        if self._seen_answer_text and not self._in_think:
            # Already past the reasoning phase (if there was one) — the
            # rest of the stream is just answer text.
            return chunk, ""

        data = self._buffer + chunk
        self._buffer = ""
        text_out: list[str] = []
        reasoning_out: list[str] = []

        while data:
            tag = self._CLOSE if self._in_think else self._OPEN
            idx = data.find(tag)

            if idx == -1:
                # No full tag in what we have. The tail might be the
                # start of one split across a chunk boundary — hold it
                # back rather than emitting it as content.
                keep = _partial_tag_suffix_len(data, tag)
                head, self._buffer = (data[:-keep], data[-keep:]) if keep else (data, "")
                if self._in_think:
                    reasoning_out.append(head)
                else:
                    text_out.append(head)
                    if head.strip():
                        self._seen_answer_text = True
                data = ""
                continue

            head, data = data[:idx], data[idx + len(tag) :]
            if self._in_think:
                reasoning_out.append(head)
                self._in_think = False
            else:
                text_out.append(head)
                if head.strip():
                    self._seen_answer_text = True
                else:
                    self._in_think = True

            if self._seen_answer_text and not self._in_think:
                # Answer has started — stop scanning the remainder of
                # this chunk for tags, treat it all as plain text.
                text_out.append(data)
                data = ""

        return "".join(text_out), "".join(reasoning_out)


def _partial_tag_suffix_len(data: str, tag: str) -> int:
    """
    Length of the longest suffix of *data* that is a proper (non-empty,
    non-full) prefix of *tag* — i.e. text that might be the start of
    *tag* split across a chunk boundary, and so should be buffered
    rather than emitted as content yet.

    :param data: The text scanned so far.
    :param tag: The full tag being watched for, e.g. ``"<think>"``.
    :returns: Number of trailing characters of *data* to hold back, or
        ``0`` if none of its suffixes could be the start of *tag*.
    """
    for length in range(min(len(data), len(tag) - 1), 0, -1):
        if tag.startswith(data[-length:]):
            return length
    return 0


async def chat_stream_to_response_events(
    chunks: AsyncIterator[dict[str, Any]],
    model: str,
) -> AsyncIterator[ResponseStreamEvent]:
    """
    Convert an async iterator of Chat Completions streaming chunk
    dicts into Responses API streaming events.

    Emits ``ResponseTextDeltaEvent`` for each text token and
    ``ResponseReasoningTextDeltaEvent`` for reasoning tokens (e.g.
    Kimi's chain-of-thought blocks). A ``ResponseReasoningStartedEvent``
    is emitted before the first reasoning delta in each reasoning run.
    Accumulates tool call deltas across chunks. Emits a final
    ``ResponseCompletedEvent`` with the assembled ``Response``.

    :param chunks: Async iterator of Chat Completions chunk
        dicts, each with ``choices[0].delta``.
    :param model: The model identifier for the ``Response``,
        e.g. ``"kimi-k2-instruct"``.
    """
    accumulated_text = ""
    # tool_calls_by_index: {index: {"id": ..., "name": ..., "arguments": ...}}
    tool_calls_by_index: dict[int, dict[str, str]] = {}
    usage_dict: dict[str, Any] | None = None
    # Tracks whether a reasoning.started event has been emitted for the
    # current reasoning run; reset when a text delta arrives (reasoning
    # is always prepended before the answer).
    reasoning_started = False
    # Recovers reasoning from raw inline <think>...</think> tags that some
    # bare local-model servers emit directly in plain-string content
    # deltas (no structured reasoning_content field). See
    # _InlineThinkTagSplitter for why this is needed.
    think_splitter = _InlineThinkTagSplitter()

    async for chunk in chunks:
        choices = chunk.get("choices") or []
        if not choices:
            # Usage-only final chunk (stream_options.include_usage=true)
            if chunk.get("usage"):
                usage_dict = chunk["usage"]
            continue

        delta = choices[0].get("delta", {})

        # Top-level reasoning content (xAI Grok, DeepSeek) arrives as a sibling
        # ``reasoning_content`` string while ``content`` is null during the
        # thinking phase. Surface it as reasoning so Grok thinking is not
        # dropped — the typed-block path below only handles Kimi-style blocks
        # nested inside ``content``.
        reasoning_content = delta.get("reasoning_content")
        if isinstance(reasoning_content, str) and reasoning_content:
            if not reasoning_started:
                yield ResponseReasoningStartedEvent()
                reasoning_started = True
            yield ResponseReasoningTextDeltaEvent(delta=reasoning_content)

        # Content delta — may be a plain string or a list of typed blocks
        # (Kimi and some Databricks models use typed blocks).
        content = delta.get("content")
        if content is not None:
            if isinstance(content, str):
                text, reasoning = think_splitter.feed(content)
            else:
                text, reasoning = _extract_delta_content(content)
            if reasoning:
                if not reasoning_started:
                    yield ResponseReasoningStartedEvent()
                    reasoning_started = True
                yield ResponseReasoningTextDeltaEvent(delta=reasoning)
            if text:
                reasoning_started = False
                accumulated_text += text
                yield ResponseTextDeltaEvent(delta=text)

        # Tool call deltas — accumulate across chunks
        for tc_delta in delta.get("tool_calls") or []:
            idx = tc_delta.get("index", 0)
            if idx not in tool_calls_by_index:
                # Accumulator: id/name are overwritten on first chunk,
                # arguments is appended to across chunks.
                tool_calls_by_index[idx] = {
                    "id": "",
                    "name": "",
                    "arguments": "",
                }
            entry = tool_calls_by_index[idx]
            if tc_id := tc_delta.get("id"):
                entry["id"] = tc_id
            if func := tc_delta.get("function"):
                if name := func.get("name"):
                    entry["name"] = name
                if args := func.get("arguments"):
                    entry["arguments"] += args

        # Capture usage from final chunk
        if chunk.get("usage"):
            usage_dict = chunk["usage"]

    # Assemble the final Response
    output: list[MessageOutput | FunctionCallOutput | NativeToolOutput] = []
    if accumulated_text:
        output.append(MessageOutput(content=[OutputText(text=accumulated_text)]))
    for _idx in sorted(tool_calls_by_index):
        tc = tool_calls_by_index[_idx]
        output.append(
            FunctionCallOutput(
                call_id=tc["id"],
                name=tc["name"],
                arguments=tc["arguments"],
            )
        )

    usage = _extract_usage(usage_dict)
    response = Response(output=output, model=model, usage=usage)
    yield ResponseCompletedEvent(response=response)
