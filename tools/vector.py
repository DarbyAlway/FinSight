import hashlib
import logging
import time

from qdrant_client import QdrantClient, models as qmodels

from tools.config import (
    QDRANT_COLLECTION, COMPANY_PROFILES_COLLECTION,
    DENSE_MODEL, SPARSE_MODEL,
)

# multilingual-e5-large produces 1024-dim vectors (supports Thai↔English cross-lingual search)
DENSE_DIM = 1024

_dense_encoder = None
_sparse_encoder = None
_qdrant_client = None


def _get_encoders():
    global _dense_encoder, _sparse_encoder
    if _dense_encoder is None or _sparse_encoder is None:
        from fastembed import TextEmbedding, SparseTextEmbedding
        if _dense_encoder is None:
            _dense_encoder = TextEmbedding(DENSE_MODEL)
        if _sparse_encoder is None:
            _sparse_encoder = SparseTextEmbedding(SPARSE_MODEL)
    return _dense_encoder, _sparse_encoder


def init_qdrant() -> QdrantClient:
    client = QdrantClient("localhost", port=6333)
    existing = [c.name for c in client.get_collections().collections]
    if QDRANT_COLLECTION not in existing:
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config={
                "dense": qmodels.VectorParams(size=DENSE_DIM, distance=qmodels.Distance.COSINE)
            },
            sparse_vectors_config={
                "sparse": qmodels.SparseVectorParams(
                    index=qmodels.SparseIndexParams(on_disk=False)
                )
            },
        )
    if COMPANY_PROFILES_COLLECTION not in existing:
        client.create_collection(
            collection_name=COMPANY_PROFILES_COLLECTION,
            vectors_config={
                "dense": qmodels.VectorParams(size=DENSE_DIM, distance=qmodels.Distance.COSINE)
            },
        )
    return client


def _get_qdrant() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = init_qdrant()
    return _qdrant_client


def store_articles(client: QdrantClient, articles: list[dict]):
    if not articles:
        return
    dense_enc, sparse_enc = _get_encoders()
    texts = [a["title"] for a in articles]
    dense_vecs = list(dense_enc.embed(texts))
    sparse_vecs = list(sparse_enc.embed(texts))
    points = []
    for i, article in enumerate(articles):
        point_id = int(hashlib.md5(f"{article.get('ticker','')}::{article['title']}".encode()).hexdigest(), 16) % (2 ** 63)
        points.append(
            qmodels.PointStruct(
                id=point_id,
                vector={
                    "dense": dense_vecs[i].tolist(),
                    "sparse": qmodels.SparseVector(
                        indices=sparse_vecs[i].indices.tolist(),
                        values=sparse_vecs[i].values.tolist(),
                    ),
                },
                payload={**article, "stored_at": time.time()},
            )
        )
    client.upsert(collection_name=QDRANT_COLLECTION, points=points)


def hybrid_search(client: QdrantClient, query: str, ticker: str = None, top_k: int = 10, cutoff: float = 0.0) -> list[dict]:
    try:
        dense_enc, sparse_enc = _get_encoders()
        q_dense = list(dense_enc.embed([query]))[0].tolist()
        q_sparse = list(sparse_enc.embed([query]))[0]

        must = []
        if ticker:
            must.append(qmodels.FieldCondition(key="ticker", match=qmodels.MatchValue(value=ticker)))
        if cutoff > 0:
            must.append(qmodels.FieldCondition(key="published_at", range=qmodels.Range(gte=cutoff)))
        payload_filter = qmodels.Filter(must=must) if must else None

        results = client.query_points(
            collection_name=QDRANT_COLLECTION,
            prefetch=[
                qmodels.Prefetch(query=q_dense, using="dense", limit=20),
                qmodels.Prefetch(
                    query=qmodels.SparseVector(
                        indices=q_sparse.indices.tolist(),
                        values=q_sparse.values.tolist(),
                    ),
                    using="sparse",
                    limit=20,
                ),
            ],
            query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
            query_filter=payload_filter,
            limit=top_k,
        )
        return [r.payload for r in results.points]
    except Exception:
        return []


def upsert_company_profile(client: QdrantClient, symbol: str, summary: str, sector: str, industry: str):
    dense_enc, _ = _get_encoders()
    vec = list(dense_enc.embed([summary]))[0].tolist()
    point_id = int(hashlib.md5(symbol.encode()).hexdigest(), 16) % (2 ** 63)
    client.upsert(
        collection_name=COMPANY_PROFILES_COLLECTION,
        points=[qmodels.PointStruct(
            id=point_id,
            vector={"dense": vec},
            payload={"symbol": symbol, "sector": sector, "industry": industry, "summary": summary},
        )],
    )


def search_company_profiles(client: QdrantClient, query: str, top_k: int = 5) -> list[dict]:
    dense_enc, _ = _get_encoders()
    q_vec = list(dense_enc.embed([query]))[0].tolist()
    results = client.query_points(
        collection_name=COMPANY_PROFILES_COLLECTION,
        query=q_vec,
        using="dense",
        limit=top_k,
    )
    return [r.payload for r in results.points]
