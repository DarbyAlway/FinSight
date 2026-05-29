DB_PATH = "cache.db"
CACHE_TTL_DAYS = 90
QDRANT_COLLECTION = "stock_news"
DENSE_MODEL = "intfloat/multilingual-e5-large"
SPARSE_MODEL = "Qdrant/bm25"
COMPANY_PROFILES_COLLECTION = "company_profiles"
TICKER_INFO_TTL_HOURS = 24

SYNONYMS = {
    "revenue":          ["%revenue%", "%net sales%", "%total sales%", "%total revenues%"],
    "net income":       ["%net income%", "%net earnings%", "%profit%", "%net loss%"],
    "gross margin":     ["%gross margin%", "%gross profit%"],
    "r&d":              ["%research%", "%development%", "%technology and content%"],
    "operating income": ["%operating income%", "%income from operations%", "%operating loss%"],
    "cost of sales":    ["%cost of sales%", "%cost of revenue%", "%cost of goods%"],
    "eps":              ["%earnings per share%", "%diluted%"],
}

MODEL = "qwen3:14b"                         # agents — local Ollama
MODEL_AGENT = "qwen/qwen3-32b"              # agents — Groq
MODEL_PLAN = "llama-3.3-70b-versatile"      # orchestrator planning — Groq
MODEL_SYNTHESIS = "llama-3.3-70b-versatile" # synthesis — Groq
