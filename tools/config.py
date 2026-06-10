DB_PATH = "cache.db"
CACHE_TTL_DAYS = 90
QDRANT_COLLECTION = "stock_news"
DENSE_MODEL = "intfloat/multilingual-e5-large"
SPARSE_MODEL = "Qdrant/bm25"
COMPANY_PROFILES_COLLECTION = "company_profiles"
TICKER_INFO_TTL_HOURS = 24

SYNONYMS = {
    "revenue":          ["%revenue%", "%net sales%", "%total sales%", "%total revenues%"],
    "net income":       ["%net income%", "%net earnings%", "%net profit%", "%net loss%"],
    "gross margin":     ["%gross margin%", "%gross profit%"],
    "r&d":              ["%research%", "%development%", "%technology and content%"],
    "operating income": ["%operating income%", "%income from operations%", "%operating loss%"],
    "cost of sales":    ["%cost of sales%", "%cost of revenue%", "%cost of goods%"],
    "eps":              ["%earnings per share%", "%diluted%"],
}

MODEL = "gpt-oss-120b"
MODEL_AGENT = "gpt-oss-120b"                      # agents — $0.22/$0.59 per M, tool calling confirmed
MODEL_PLAN = "Meta-Llama-3.3-70B-Instruct"       # planner — reliable JSON
MODEL_SYNTHESIS = "gpt-oss-120b"  # synthesis — switched from Llama-3.3-70B 2026-06-10; both pass the FY2022 probe with the year-coverage prompt rule, gpt-oss is cheaper
