import json
import os
from dotenv import load_dotenv

load_dotenv()

INPUT_PATH = "data/preprocessed/preprocessed.json"
OUTPUT_PATH = "data/analysis/analysis_output.json"

MODEL = "gemini-2.5-flash"

# Kontext für die LLM-Interpretation
DOMAIN_CONTEXT = """Du analysierst Daten für ein Service Sonar im Bereich
soziale Dienstleistungen für Familien in Bayern (Zentrum Bayern Familie und Soziales / ZBFS).
Relevante Themen: Elterngeld, Familiengeld, Kindergeld, Pflegegeld, Kita, Wohngeld für Familien,
Fördermittel, Schwerbehinderung im Familienkontext, Bürokratie bei Anträgen.
NICHT relevant: allgemeine Politik, Impfschäden ohne Familienbezug, Asyl, reine Behördeninfos ohne Problembezug."""


def load_data() -> list:
    """Lädt preprocessed Dokumente."""
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def run_bertopic(docs: list):
    """
    TOOL 1: BERTopic Topic Modeling auf preprocessed_text.
    mpnet-Embedding + HDBSCAN 'leaf' brechen den Mega-Cluster auf;
    KeyBERT+MMR liefern lesbare Topic-Labels für die LLM-Interpretation.
    """
    from bertopic import BERTopic
    from bertopic.representation import KeyBERTInspired, MaximalMarginalRelevance
    from hdbscan import HDBSCAN
    from sentence_transformers import SentenceTransformer
    from sklearn.feature_extraction.text import CountVectorizer
    from spacy.lang.de.stop_words import STOP_WORDS as GERMAN_STOP_WORDS
    from umap import UMAP

    preprocessed_texts = [d.get("preprocessed_text", "") for d in docs]

    embedding_model = SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")

    umap_model = UMAP(
        n_neighbors=15,
        n_components=5,
        min_dist=0.0,
        metric='cosine',
        random_state=42
    )

    # cluster_selection_method='leaf' wählt die feinsten Cluster der Hierarchie
    # — schlüsselparameter gegen den Mega-Cluster.
    hdbscan_model = HDBSCAN(
        min_cluster_size=8,
        min_samples=2,
        metric='euclidean',
        cluster_selection_method='leaf',
        prediction_data=True
    )

    vectorizer_model = CountVectorizer(
        ngram_range=(1, 2),
        stop_words=list(GERMAN_STOP_WORDS),
        min_df=3
    )

    representation_model = [KeyBERTInspired(), MaximalMarginalRelevance(diversity=0.3)]

    topic_model = BERTopic(
        language="multilingual",
        embedding_model=embedding_model,
        calculate_probabilities=True,
        verbose=True,
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer_model,
        representation_model=representation_model
    )
    topics, probs = topic_model.fit_transform(preprocessed_texts)

    new_topics = topic_model.reduce_outliers(
        preprocessed_texts, topics, strategy="embeddings"
    )
    topic_model.update_topics(
        preprocessed_texts,
        topics=new_topics,
        vectorizer_model=vectorizer_model,
        representation_model=representation_model
    )
    return new_topics, probs, topic_model


def run_sentiment(docs: list) -> list:
    """
    TOOL 2: Deutsches Sentiment via oliverguhr/german-sentiment-bert.
    Direkt über transformers pipeline — versionsunabhängig.
    Läuft auf cleaned_text (Satzstruktur erhalten).
    """
    from transformers import pipeline

    sentiment_pipeline = pipeline(
        "text-classification",
        model="oliverguhr/german-sentiment-bert",
        truncation=True,
        max_length=512
    )
    cleaned_texts = [d.get("cleaned_text", "") for d in docs]
    print("Sentiment-Analyse läuft...")
    results = sentiment_pipeline(cleaned_texts)
    return [r["label"] for r in results]


def get_gemini_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print(
            "GEMINI_API_KEY fehlt. Bitte lege eine .env-Datei an "
            "(siehe .env.example) und setze GEMINI_API_KEY, bevor du den "
            "Analysis Agent startest."
        )
        return None
    from google import genai

    return genai.Client(api_key=api_key)


def interpret_topics_with_llm(client, topic_overview: list, topic_sentiments: dict) -> dict:
    """
    REASONING LAYER: Gemini interpretiert die BERTopic Cluster.
    Entscheidet welche Topics relevant sind im Kontext Familie Bayern,
    welche Rauschen sind, und fasst pro Topic das Kernproblem zusammen.
    """
    topics_text = ""
    for topic in topic_overview:
        tid = topic.get("Topic")
        if tid == -1:
            continue
        name = topic.get("Name", "")
        count = topic.get("Count", 0)
        sentiment = topic_sentiments.get(tid, {})
        topics_text += f"\nTopic {tid}: {name} ({count} Dokumente)\n"
        topics_text += f"  Sentiment: {sentiment}\n"

    prompt = f"""{DOMAIN_CONTEXT}

Hier sind die von BERTopic gefundenen Topics mit ihrem Sentiment:
{topics_text}

Deine Aufgabe:
1. Bewerte für jedes Topic ob es RELEVANT für soziale Dienstleistungen im Familienkontext ist
2. Fasse für relevante Topics das Kernproblem in einem Satz zusammen
3. Markiere irrelevante Topics (z.B. Impfschäden, Asyl, reine Behördeninfos)

Antworte NUR mit validem JSON in diesem Format:
{{
  "relevant_topics": [
    {{"topic_id": 0, "kernproblem": "...", "relevanz_begruendung": "..."}}
  ],
  "irrelevante_topics": [
    {{"topic_id": 3, "grund": "..."}}
  ]
}}"""

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt
    )

    text = response.text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def run() -> int:
    """
    Einstiegspunkt — lädt Daten, führt BERTopic + Sentiment durch,
    interpretiert via Gemini, speichert kombinierten Output für Gap Analysis.
    """
    print("Analysis Agent gestartet...")
    client = get_gemini_client()
    if client is None:
        return 1

    docs = load_data()
    print(f"  {len(docs)} Dokumente geladen")

    print("BERTopic läuft...")
    topics, probs, topic_model = run_bertopic(docs)
    topic_info = topic_model.get_topic_info()
    print(f"  {len(topic_info)} Topics gefunden")

    sentiments = run_sentiment(docs)

    topic_sentiments = {}
    for i, topic_id in enumerate(topics):
        topic_sentiments.setdefault(topic_id, {"positive": 0, "negative": 0, "neutral": 0})
        label = sentiments[i]
        if label in topic_sentiments[topic_id]:
            topic_sentiments[topic_id][label] += 1

    print("Gemini interpretiert Topics...")
    topic_overview = topic_info.to_dict(orient="records")
    interpretation = interpret_topics_with_llm(client, topic_overview, topic_sentiments)
    print(f"  {len(interpretation.get('relevant_topics', []))} relevante Topics")
    print(f"  {len(interpretation.get('irrelevante_topics', []))} irrelevante Topics")

    documents = []
    for i, doc in enumerate(docs):
        documents.append({
            **doc,
            "topic": int(topics[i]),
            "topic_probability": float(probs[i].max()) if probs[i] is not None else 0.0,
            "sentiment": sentiments[i]
        })

    output = {
        "documents": documents,
        "topic_overview": topic_overview,
        "topic_sentiments": {str(k): v for k, v in topic_sentiments.items()},
        "llm_interpretation": interpretation
    }

    os.makedirs("data/analysis", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nOutput gespeichert → {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
