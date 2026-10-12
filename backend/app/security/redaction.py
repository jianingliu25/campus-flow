"""Best-effort reversible contact masking; not a guarantee of anonymization."""
import json
import re

PATTERN = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|(?<!\w)(?:\+?\d[ -]?){8,15}(?!\w)")


def mask(messages):
    mapping = {}
    def replace(match):
        value = match.group()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
            return value
        if value not in mapping:
            mapping[value] = f"[CF_PRIVATE_{len(mapping):04d}]"
        return mapping[value]
    # Role definitions are developer-owned; user input may include copied contact data.
    prepared = [{**message, "content": PATTERN.sub(replace, message["content"]) if message["role"] != "system" else message["content"]}
                for message in messages]
    return prepared, {marker: value for value, marker in mapping.items()}


def restore(answer, mapping):
    def text(value):
        for marker, original in mapping.items():
            value = value.replace(marker, original)
        return value
    def walk(value):
        if isinstance(value, str): return text(value)
        if isinstance(value, list): return [walk(item) for item in value]
        if isinstance(value, dict): return {key: walk(item) for key, item in value.items()}
        return value
    try:
        return json.dumps(walk(json.loads(answer)), ensure_ascii=False)
    except (ValueError, TypeError):
        return text(answer)
