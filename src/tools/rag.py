import chromadb
from chromadb.utils import embedding_functions
from src.config import CHROMA_DB_DIR, GEMINI_API_KEY

def get_chroma_client():
    return chromadb.PersistentClient(path=CHROMA_DB_DIR)

def get_embedding_fn():
    return embedding_functions.GoogleGenerativeAiEmbeddingFunction(api_key=GEMINI_API_KEY)

def add_to_vector_store(collection_name, documents, metadatas, ids):
    client = get_chroma_client()
    embedding_fn = get_embedding_fn()
    collection = client.get_or_create_collection(name=collection_name, embedding_function=embedding_fn)
    collection.add(documents=documents, metadatas=metadatas, ids=ids)

def query_vector_store(collection_name, query_text, n_results=3):
    client = get_chroma_client()
    embedding_fn = get_embedding_fn()
    collection = client.get_or_create_collection(name=collection_name, embedding_function=embedding_fn)
    results = collection.query(query_texts=[query_text], n_results=n_results)
    return results
