DB_PATH = "cache.db"
CACHE_TTL_DAYS = 90
QDRANT_COLLECTION = "stock_news"
DENSE_MODEL = "BAAI/bge-large-en-v1.5"
SPARSE_MODEL = "Qdrant/bm25"
COMPANY_PROFILES_COLLECTION = "company_profiles"
TICKER_INFO_TTL_HOURS = 72

SYNONYMS = {
    "revenue":          ["%revenue%", "%net sales%", "%total sales%"],
    "net income":       ["%net income%", "%net earnings%", "%profit%"],
    "gross margin":     ["%gross margin%", "%gross profit%"],
    "r&d":              ["%research%", "%development%", "%technology and content%"],
    "operating income": ["%operating income%", "%income from operations%"],
    "cost of sales":    ["%cost of sales%", "%cost of revenue%", "%cost of goods%"],
    "eps":              ["%earnings per share%", "%diluted%"],
}

MODEL = "qwen3:14b"
