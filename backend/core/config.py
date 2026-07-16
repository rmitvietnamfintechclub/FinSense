# --- Embedding stage (pipeline/stages/cluster/embedder.py) ---
# Model choice: the corpus is Vietnamese financial news with embedded
# English terms (ticker symbols, "margin", "IPO"), so the model must be
# multilingual rather than Vietnamese-only.
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-base"

# Batch size for SentenceTransformer.encode(). Tunable — higher trades
# more memory for higher throughput.
EMBEDDING_BATCH_SIZE = 32


E5_QUERY_PREFIX = "query: "
