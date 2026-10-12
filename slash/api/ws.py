"""Server-sent events for task progress. WebSocket takeover is not part of M2."""


def format_sse(event: str, data: str) -> str:
    lines = data.splitlines() or [""]
    payload = "\n".join(f"data: {line}" for line in lines)
    return f"event: {event}\n{payload}\n\n"
