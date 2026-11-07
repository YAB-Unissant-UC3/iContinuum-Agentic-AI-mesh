"""Conservative, explicit retention-duration conflicts for the synthetic demo."""

import re


def detect_conflicts(passages):
    statements = []
    units = {"hour": 1, "day": 24, "week": 168}
    for passage in passages:
        text = passage.text.casefold()
        if not re.search(r"\b(retain\w*|retention|keep|kept)\b", text):
            continue
        if not re.search(r"\b(records?|logs?)\b", text):
            continue
        if re.search(r"\b(no|not|never|less|more|least|most|minimum|maximum)\b|[<>≤≥]", text):
            continue
        matches = list(re.finditer(r"\b(\d+)\s*[- ]?\s*(hour|day|week)s?\b", text))
        if len(matches) != 1:
            continue
        match = matches[0]
        topic = "audit records" if "audit" in text else "records/logs"
        statements.append((passage, topic, int(match[1]) * units[match[2]], match[0]))
    conflicts = []
    for index, (first, topic, value, duration) in enumerate(statements):
        for second, other_topic, other_value, other_duration in statements[index + 1:]:
            if topic != other_topic or value == other_value:
                continue
            conflicts.append({"conflict_id": "X{:03d}".format(len(conflicts) + 1),
                              "description": "Potential {} retention conflict: {} versus {}. Human review required.".format(
                                  topic, duration, other_duration),
                              "citations": [{"document_id": p.document_id, "line_start": p.number,
                                             "line_end": p.number, "quote": p.text} for p in (first, second)]})
            if len(conflicts) >= 30:
                return conflicts
    return conflicts
