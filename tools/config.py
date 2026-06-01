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

MODEL = "qwen2.5:14b"             # default
MODEL_AGENT = "qwen2.5:14b"      # agents — no thinking mode, reliable tool calling
MODEL_PLAN = "qwen3:30b-a3b"     # planner — smarter ticker resolution (add /no_think prefix)
MODEL_SYNTHESIS = "qwen3:14b"    # synthesis — good reasoning, faster than 30b
