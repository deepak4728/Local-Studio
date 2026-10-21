import re


def retrieve_document_snippets(organization, query, limit=3):
    terms = {t for t in re.findall(r"[a-z0-9]{3,}", query.casefold())}
    ranked = []
    for document in organization.documents.exclude(extracted_text="").only("title", "extracted_text")[:100]:
        chunks = [c.strip() for c in re.split(r"\n\s*\n", document.extracted_text) if c.strip()]
        for chunk in chunks:
            tokens = set(re.findall(r"[a-z0-9]{3,}", chunk.casefold()))
            score = len(terms & tokens)
            if score:
                ranked.append((score, document.title, chunk[:1800]))
    ranked.sort(reverse=True)
    return [{"title": title, "text": chunk} for _, title, chunk in ranked[:limit]]
