"""Environment variable loading and validation.

Shared by both backend/api and backend/pipeline — see
docs/FOLDER_STRUCTURE_GUIDANCE.MD.
"""

# --- Embedding stage (pipeline/stages/cluster/embedder.py) ---
# Model choice: the corpus is Vietnamese financial news with embedded
# English terms (ticker symbols, "margin", "IPO"), so the model must be
# multilingual rather than Vietnamese-only.
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-base"
EMBEDDING_DIM = 768

# E5 models are trained with a "query: " / "passage: " input-prefix
# convention. For symmetric article-to-article similarity (not
# asymmetric query/document search) every text gets the same "query: "
# prefix. Omitting it does not raise an error — it silently produces
# worse embeddings — so do not strip it downstream.
E5_QUERY_PREFIX = "query: "
