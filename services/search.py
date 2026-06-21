import os
import chromadb
from chromadb.utils import embedding_functions
from sentence_transformers import SentenceTransformer
from PIL import Image
import io

CHROMA_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")

# Persistent Chroma Client
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)

# Lazy loading of models to optimize import times
_clip_model = None

def get_clip_model():
    global _clip_model
    if _clip_model is None:
        # Load local CLIP model for visual search
        _clip_model = SentenceTransformer("clip-ViT-B-32")
    return _clip_model

# Built-in SentenceTransformer Embedding Function for ChromaDB text search
text_emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

# Collections
products_text_collection = chroma_client.get_or_create_collection(
    name="products_text",
    embedding_function=text_emb_fn
)

policies_text_collection = chroma_client.get_or_create_collection(
    name="policies_text",
    embedding_function=text_emb_fn
)

# For visual search (CLIP collection uses custom embeddings generated manually since Chroma doesn't natively wrap CLIP for images)
products_image_collection = chroma_client.get_or_create_collection(
    name="products_image"
)

def add_product_text(product_id: int, name: str, description: str, occasion_tags: str, mood_tags: str, category: str, color: str):
    """
    Format and add/update product text embeddings in Chroma.
    """
    document = (
        f"Name: {name}\n"
        f"Category: {category}\n"
        f"Color: {color}\n"
        f"Description: {description}\n"
        f"Occasions: {occasion_tags}\n"
        f"Moods: {mood_tags}"
    )
    products_text_collection.upsert(
        ids=[str(product_id)],
        documents=[document],
        metadatas=[{
            "product_id": product_id,
            "name": name,
            "category": category,
            "color": color
        }]
    )

def add_policy_chunk(chunk_id: str, text: str, metadata: dict):
    """
    Add a return policy chunk text to Chroma.
    """
    policies_text_collection.upsert(
        ids=[chunk_id],
        documents=[text],
        metadatas=[metadata]
    )

def add_product_image(product_id: int, image_bytes: bytes):
    """
    Embed product image using CLIP and add to Chroma products_image collection.
    """
    clip_model = get_clip_model()
    image = Image.open(io.BytesIO(image_bytes))
    image_emb = clip_model.encode(image).tolist()
    
    products_image_collection.upsert(
        ids=[str(product_id)],
        embeddings=[image_emb],
        metadatas=[{"product_id": product_id}]
    )

def search_products_text(query: str, top_k: int = 3):
    """
    Semantic search over products using query string.
    """
    results = products_text_collection.query(
        query_texts=[query],
        n_results=top_k
    )
    # Reformat results
    items = []
    if results and results["ids"] and results["ids"][0]:
        for i in range(len(results["ids"][0])):
            items.append({
                "product_id": int(results["ids"][0][i]),
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i] if "distances" in results else None
            })
    return items

def search_products_image(image_bytes: bytes, top_k: int = 3):
    """
    Semantic search over products using CLIP image embedding.
    """
    clip_model = get_clip_model()
    image = Image.open(io.BytesIO(image_bytes))
    image_emb = clip_model.encode(image).tolist()
    
    results = products_image_collection.query(
        query_embeddings=[image_emb],
        n_results=top_k
    )
    
    items = []
    if results and results["ids"] and results["ids"][0]:
        for i in range(len(results["ids"][0])):
            items.append({
                "product_id": int(results["ids"][0][i]),
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if "distances" in results else None
            })
    return items

def search_policies(query: str, top_k: int = 2):
    """
    Semantic search over policy document clauses.
    """
    results = policies_text_collection.query(
        query_texts=[query],
        n_results=top_k
    )
    clauses = []
    if results and results["ids"] and results["ids"][0]:
        for i in range(len(results["ids"][0])):
            clauses.append({
                "id": results["ids"][0][i],
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i]
            })
    return clauses
