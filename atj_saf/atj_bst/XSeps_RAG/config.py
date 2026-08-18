"""
Configuration for the separation-heuristics RAG proof of concept.
Edit these values to match your local setup.
"""

# --- Local LLM (Qwen) endpoint ---
# Works with any OpenAI-compatible server: Ollama, vLLM, LM Studio, text-generation-webui.
# Ollama default: http://localhost:11434/v1
# vLLM default:   http://localhost:8000/v1
LLM_BASE_URL = "http://localhost:11434/v1"
LLM_API_KEY = "not-needed"          # most local servers ignore this, but the client requires a value
LLM_MODEL = "qwen2.5:14b-instruct"  # whatever tag you've pulled/served

# --- Embedding model (local, via sentence-transformers) ---
# bge-small is fast enough on CPU and fine for a PoC over ~20 pages.
# Swap to "Qwen/Qwen3-Embedding-0.6B" if you want to keep everything in the Qwen family.
EMBED_MODEL = "BAAI/bge-small-en-v1.5"

# --- Storage ---
CHROMA_DIR = "./chroma_db"
COLLECTION_NAME = "separation_heuristics"

# --- Chunking ---
CHUNK_TARGET_WORDS = 250
CHUNK_OVERLAP_WORDS = 40

# --- Retrieval ---
TOP_K = 8
