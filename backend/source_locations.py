"""Additive PDF citation metadata; existing global line locations stay valid."""


def page_references(document, start, end):
    if not document or document.get("format") != "pdf":
        return []
    if type(start) is not int or type(end) is not int or not 1 <= start <= end <= document["line_count"]:
        return []
    references = []
    for line in document["lines"][start - 1:end]:
        if not references or references[-1]["page_number"] != line["page_number"]:
            references.append({"page_number": line["page_number"],
                               "line_start": line["page_line_number"], "line_end": line["page_line_number"]})
        else:
            references[-1]["line_end"] = line["page_line_number"]
    return references


def add_page_references(result, documents):
    lookup = {d["document_id"]: d for d in documents}
    for group in ("claims", "contradictions", "requirement_checks"):
        for item in result.get(group, []):
            for citation in item.get("citations", []):
                refs = page_references(lookup.get(citation.get("document_id")),
                                       citation.get("line_start"), citation.get("line_end"))
                if refs:
                    citation["page_references"] = refs
