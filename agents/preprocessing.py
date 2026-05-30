import json
import os
import spacy

INPUT_PATHS = [
    "data/raw/scraped_web.json",
    "data/raw/scraped_reddit.json",
    "data/raw/scraped_fragdenstaat.json"
]
OUTPUT_PATH = "data/preprocessed/preprocessed.json"

# spaCy Modell laden
nlp = spacy.load("de_core_news_lg")

# PII Platzhalter
PII_LABELS = {
    "PER": "[NAME]",
    "LOC": "[ORT]",
    "ORG": "[ORGANISATION]",
}


def process_doc(doc: spacy.tokens.Doc, raw_text: str) -> tuple[str, str]:
    """
    Verarbeitet ein spaCy Doc einmal und gibt beide Text-Versionen zurück.
    Ein einziger nlp() Call pro Dokument — kein doppeltes Processing.

    Returns:
        cleaned_text: PII anonymisiert, Satzstruktur erhalten (für GerVader)
        preprocessed_text: lemmatisiert, Stopwords raus (für BERTopic)
    """
    # ── Output 1: cleaned_text (für GerVader) ──
    # PII von hinten ersetzen damit Indizes nicht verschoben werden
    cleaned = raw_text
    for ent in reversed(doc.ents):
        placeholder = PII_LABELS.get(ent.label_)
        if placeholder:  # nur PER, LOC, ORG ersetzen — alles andere original lassen
            cleaned = cleaned[:ent.start_char] + placeholder + cleaned[ent.end_char:]
    cleaned = " ".join(cleaned.split())  # Whitespace normalisieren
    # ── Output 2: preprocessed_text (für BERTopic) ──
    tokens = [
    token.lemma_.lower()
    for token in doc
    if not token.is_stop
    and not token.is_punct
    and not token.is_space
    and not token.like_num
    and not token.like_url           # URLs raus
    and len(token.lemma_) > 2
    and not any(x in token.text.lower() for x in ["http", "www", ".de", ".com"])
]
    preprocessed = " ".join(tokens)

    return cleaned, preprocessed


def load_sources() -> list:
    """
    Lädt alle drei Quellen und merged sie zu einer Liste.
    """
    all_docs = []
    for path in INPUT_PATHS:
        if not os.path.exists(path):
            print(f"Nicht gefunden, übersprungen: {path}")
            continue
        with open(path, "r", encoding="utf-8") as f:
            docs = json.load(f)
            all_docs.extend(docs)
            print(f"  {len(docs)} Dokumente geladen aus {path}")
    return all_docs


def run():
    """
    Einstiegspunkt — lädt alle Quellen, preprocesst via nlp.pipe() in Batches,
    speichert zwei Text-Versionen pro Dokument.
    """
    print("Preprocessing gestartet...")
    docs = load_sources()
    print(f"  {len(docs)} Dokumente gesamt")

    # Texte extrahieren für nlp.pipe()
    texts = [doc.get("text", "") for doc in docs]

    results = []
    # nlp.pipe() verarbeitet in Batches — deutlich schneller als einzeln
    for i, (spacy_doc, meta) in enumerate(zip(nlp.pipe(texts, batch_size=32), docs)):
        if i % 50 == 0:
            print(f"  [{i}/{len(docs)}] verarbeitet...")

        raw_text = meta.get("text", "")
        if not raw_text.strip():
            continue

        cleaned, preprocessed = process_doc(spacy_doc, raw_text)

        result = {
            **meta,
            "cleaned_text": cleaned,
            "preprocessed_text": preprocessed
        }
        results.append(result)

    os.makedirs("data/preprocessed", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n{len(results)} Dokumente preprocesst → {OUTPUT_PATH}")


if __name__ == "__main__":
    run()