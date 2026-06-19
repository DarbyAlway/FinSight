import os

DB_PATH = os.getenv("CACHE_DB_PATH", "cache.db")
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
MODEL_AGENT = "gemma-4-31B-it"                    # agents — non-reasoning, ~1.4s/round vs gpt-oss's variable 8-57s (reasoning); cheap ($0.38/$1.15) + reliable parallel tool calls on SambaNova (Llama-3.3 400s on them)
MODEL_PLAN = "Meta-Llama-3.3-70B-Instruct"       # planner — reliable JSON
MODEL_SYNTHESIS = "Meta-Llama-3.3-70B-Instruct"  # synthesis — non-reasoning, ~1-2s vs gpt-oss's 27-44s (reasoning); no tools so no 400 risk; passed the FY2022 fidelity probe historically (was synthesis model pre-2026-06-10)
