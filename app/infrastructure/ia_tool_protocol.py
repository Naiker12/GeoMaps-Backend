"""Reject textual tool markup when a provider did not return native calls."""
import re

_TOOL_MARKUP = re.compile(r'<\|tool_call(?:_start|_end)?\|>|</?tool_call\b|<function\s*=|<parameter\s*=', re.I)

def invalid_textual_tool_response(content: str, tool_calls: list) -> bool:
    return not tool_calls and bool(_TOOL_MARKUP.search(content or ''))

def tool_protocol_error() -> dict:
    return {
        'status': 'error',
        'error_message': 'El modelo devolvió una llamada de herramienta en un formato no válido. Reintenta la consulta o selecciona otro modelo.',
        'status_code': 502,
        'error_code': 'INVALID_TOOL_FORMAT',
    }
