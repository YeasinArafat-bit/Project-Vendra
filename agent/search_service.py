import os
import io
import json
import chromadb
from chromadb.utils import embedding_functions
from sentence_transformers import SentenceTransformer
from PIL import Image

# Path configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VECTORSTORE_DIR = os.path.join(BASE_DIR, "vectorstore")
CHROMA_PATH = os.path.join(VECTORSTORE_DIR, "chroma_db")

# Create directory if not exists
os.makedirs(VECTORSTORE_DIR, exist_ok=True)

# Lazy-loaded Chroma client and collections
_chroma_client = None
_products_text_collection = None
_policies_text_collection = None
_products_image_collection = None
_text_emb_fn = None

# Lazy load models to minimize import overhead
_clip_model = None

def normalize_category(category_str: str) -> str:
    if not category_str:
        return ""
    cat = str(category_str).strip().lower()
    if cat in ["sport", "sports", "running", "athletic", "hiking", "trainer", "trainers", "active"]:
        return "sport"
    if cat in ["formal", "dress", "oxford", "derby", "wedding", "business", "polished", "office"]:
        return "formal"
    if cat in ["casual", "sneaker", "sneakers", "slip-on", "sandal", "sandals", "comfort", "relax", "minimal"]:
        return "casual"
    if cat in ["sale", "clearance", "promo", "discount"]:
        return "sale"
    return cat

def get_clip_model():
    global _clip_model
    if _clip_model is None:
        _clip_model = SentenceTransformer("clip-ViT-B-32")
    return _clip_model

def get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
    return _chroma_client

def get_text_emb_fn():
    global _text_emb_fn
    if _text_emb_fn is None:
        _text_emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
    return _text_emb_fn

def get_products_text_collection():
    global _products_text_collection
    if _products_text_collection is None:
        client = get_chroma_client()
        emb_fn = get_text_emb_fn()
        _products_text_collection = client.get_or_create_collection(
            name="products_text",
            embedding_function=emb_fn
        )
    return _products_text_collection

def get_policies_text_collection():
    global _policies_text_collection
    if _policies_text_collection is None:
        client = get_chroma_client()
        emb_fn = get_text_emb_fn()
        _policies_text_collection = client.get_or_create_collection(
            name="policies_text",
            embedding_function=emb_fn
        )
    return _policies_text_collection

def get_products_image_collection():
    global _products_image_collection
    if _products_image_collection is None:
        client = get_chroma_client()
        _products_image_collection = client.get_or_create_collection(
            name="products_image"
        )
    return _products_image_collection

def add_product_text(product_id: str, name: str, description: str, occasion_tags: list, mood_tags: list, category: str, price: float):
    document = (
        f"Name: {name}\n"
        f"Category: {category}\n"
        f"Description: {description}\n"
        f"Occasions: {', '.join(occasion_tags)}\n"
        f"Moods: {', '.join(mood_tags)}\n"
        f"Price: {price} BDT"
    )
    get_products_text_collection().upsert(
        ids=[str(product_id)],
        documents=[document],
        metadatas=[{
            "product_id": product_id,
            "name": name,
            "category": category,
            "price": price
        }]
    )

def add_policy_chunk(chunk_id: str, text: str, metadata: dict):
    get_policies_text_collection().upsert(
        ids=[chunk_id],
        documents=[text],
        metadatas=[metadata]
    )

def add_product_image(product_id: str, image_bytes: bytes):
    clip_model = get_clip_model()
    image = Image.open(io.BytesIO(image_bytes))
    image_emb = clip_model.encode(image).tolist()
    
    get_products_image_collection().upsert(
        ids=[str(product_id)],
        embeddings=[image_emb],
        metadatas=[{"product_id": product_id}]
    )

def filter_products_by_metadata(
    all_products: list, 
    category: str = None, 
    max_price: float = None, 
    min_price: float = None
) -> list:
    """Helper to apply category and price metadata pre-filtering to all catalog products."""
    filtered_products = []
    for p in all_products:
        p_id = str(p["id"])
        
        # Safely convert price
        try:
            p_price = float(p.get("price", 0.0))
        except (ValueError, TypeError):
            p_price = 0.0
            
        p_cat = str(p.get("category", "")).strip().lower()
        
        # Filter by category
        if category and category.strip():
            normalized_query_cat = normalize_category(category)
            normalized_p_cat = normalize_category(p_cat)
            if normalized_p_cat != normalized_query_cat:
                continue
        # Filter by max price
        if max_price is not None:
            try:
                if p_price > float(max_price):
                    continue
            except (ValueError, TypeError):
                pass
        # Filter by min price
        if min_price is not None:
            try:
                if p_price < float(min_price):
                    continue
            except (ValueError, TypeError):
                pass
            
        filtered_products.append(p)
    return filtered_products

def search_products_text(
    query: str, 
    top_k: int = 3, 
    category: str = None, 
    max_price: float = None, 
    min_price: float = None
) -> list:
    from adapters import get_adapter
    adapter = get_adapter()
    all_products = adapter.get_products()
    
    # 1. Apply category and price metadata pre-filtering
    filtered_products = filter_products_by_metadata(all_products, category, max_price, min_price)
        
    if not filtered_products:
        return []
        
    # Short-circuit for no-query "browse/filter all" case
    if not query or not query.strip():
        return [
            {
                "product_id": str(p["id"]),
                "document": (
                    f"Name: {p['name']}\n"
                    f"Category: {p.get('category','')}\n"
                    f"Description: {p['description']}\n"
                    f"Occasions: {', '.join(p.get('occasion_tags', []))}\n"
                    f"Moods: {', '.join(p.get('mood_tags', []))}\n"
                    f"Price: {p['price']} BDT"
                ),
                "metadata": {
                    "product_id": str(p["id"]),
                    "name": p["name"],
                    "category": p.get("category",""),
                    "price": p["price"]
                },
                "distance": None,
                "hybrid_score": 1.0
            }
            for p in filtered_products[:top_k]
        ]
        
    filtered_ids = {str(p["id"]) for p in filtered_products}
    
    # 2. Build ChromaDB where query and query the vector store
    where = {}
    filters = []
    if category and category.strip():
        filters.append({"category": normalize_category(category)})
    if max_price is not None:
        try:
            filters.append({"price": {"$lte": float(max_price)}})
        except (ValueError, TypeError):
            pass
    if min_price is not None:
        try:
            filters.append({"price": {"$gte": float(min_price)}})
        except (ValueError, TypeError):
            pass
        
    if len(filters) == 1:
        where = filters[0]
    elif len(filters) > 1:
        where = {"$and": filters}
        
    dense_results = {}
    try:
        coll = get_products_text_collection()
        count = coll.count()
        if count > 0:
            n_candidates = max(top_k * 3, 10)
            results = coll.query(
                query_texts=[query],
                n_results=min(n_candidates, count),
                where=where if where else None
            )
            if results and results["ids"] and results["ids"][0]:
                for i in range(len(results["ids"][0])):
                    p_id = str(results["ids"][0][i])
                    # Only keep if in our filtered set
                    if p_id in filtered_ids:
                        distance = results["distances"][0][i] if "distances" in results else 1.0
                        document = results["documents"][0][i]
                        metadata = results["metadatas"][0][i]
                        # Convert L2 distance metric (lower is closer) to a similarity-like score
                        dense_score = 1.0 / (1.0 + float(distance))
                        dense_results[p_id] = {
                            "dense_score": dense_score,
                            "document": document,
                            "metadata": metadata,
                            "distance": distance
                        }
    except Exception as e:
        print(f"ChromaDB search failed: {e}")
            
    # 3. Calculate sparse (keyword matching) scores and combine
    import re
    query_tokens = [t.lower() for t in re.findall(r'\w+', query) if t]
    
    scored_items = []
    for p in filtered_products:
        p_id = str(p["id"])
        
        # Calculate sparse score
        sparse_score = 0.0
        if query_tokens:
            token_matches = 0.0
            for token in query_tokens:
                if token == p_id.lower():
                    token_matches += 4.0
                elif token in p.get("name", "").lower():
                    token_matches += 2.0
                elif token in p.get("category", "").lower():
                    token_matches += 1.5
                elif any(token in tag.lower() for tag in p.get("occasion_tags", []) + p.get("mood_tags", [])):
                    token_matches += 1.0
                elif token in p.get("description", "").lower():
                    token_matches += 0.5
            sparse_score = token_matches / len(query_tokens)
            sparse_score = min(sparse_score, 1.0)
            
        # Get dense score
        dense_info = dense_results.get(p_id)
        if dense_info:
            dense_score = dense_info["dense_score"]
            document = dense_info["document"]
            metadata = dense_info["metadata"]
            distance = dense_info["distance"]
        else:
            dense_score = 0.0
            # Synthesize document and metadata from product dict
            document = (
                f"Name: {p['name']}\n"
                f"Category: {p.get('category','')}\n"
                f"Description: {p['description']}\n"
                f"Occasions: {', '.join(p.get('occasion_tags', []))}\n"
                f"Moods: {', '.join(p.get('mood_tags', []))}\n"
                f"Price: {p['price']} BDT"
            )
            metadata = {
                "product_id": p_id,
                "name": p["name"],
                "category": p.get("category",""),
                "price": p["price"]
            }
            distance = None
            
        # Combine dense and sparse scores
        hybrid_score = 0.5 * dense_score + 0.5 * sparse_score
            
        # We only keep items that have some match if there's a query
        if hybrid_score > 0.0:
            scored_items.append({
                "product_id": p_id,
                "document": document,
                "metadata": metadata,
                "distance": distance,
                "hybrid_score": hybrid_score
            })
            
    # Sort by hybrid score descending, then by price (cheapest first)
    scored_items.sort(key=lambda x: (-x["hybrid_score"], x["metadata"].get("price", 0)))
    
    # Return top_k
    return scored_items[:top_k]

def search_products_image(
    image_bytes: bytes, 
    top_k: int = 3, 
    query: str = None,
    category: str = None, 
    max_price: float = None, 
    min_price: float = None
) -> list:
    from adapters import get_adapter
    adapter = get_adapter()
    all_products = adapter.get_products()
    
    # 1. Apply category and price metadata pre-filtering
    filtered_products = filter_products_by_metadata(all_products, category, max_price, min_price)
        
    if not filtered_products:
        return []
        
    filtered_ids = {str(p["id"]) for p in filtered_products}
    
    # 2. Get CLIP visual search results
    visual_results = {}
    try:
        clip_model = get_clip_model()
        image = Image.open(io.BytesIO(image_bytes))
        image_emb = clip_model.encode(image).tolist()
        
        coll = get_products_image_collection()
        count = coll.count()
        if count > 0:
            # Query visual items up to count, then filter
            results = coll.query(
                query_embeddings=[image_emb],
                n_results=count
            )
            if results and results["ids"] and results["ids"][0]:
                for i in range(len(results["ids"][0])):
                    p_id = str(results["ids"][0][i])
                    if p_id in filtered_ids:
                        distance = results["distances"][0][i] if "distances" in results else 1.0
                        visual_score = 1.0 / (1.0 + float(distance))
                        visual_results[p_id] = {
                            "visual_score": visual_score,
                            "distance": distance
                        }
    except Exception as e:
        print(f"Visual query failed: {e}")
        
    # 3. Calculate text similarity score if text refinement query is provided
    import re
    query_tokens = [t.lower() for t in re.findall(r'\w+', query) if t] if query else []
    
    scored_items = []
    for p in filtered_products:
        p_id = str(p["id"])
        
        # Get visual score
        vis_info = visual_results.get(p_id)
        if vis_info:
            visual_score = vis_info["visual_score"]
            distance = vis_info["distance"]
        else:
            visual_score = 0.0
            distance = None
            
        # Calculate text sparse score against product details
        sparse_score = 0.0
        if query_tokens:
            token_matches = 0.0
            for token in query_tokens:
                if token == p_id.lower():
                    token_matches += 4.0
                elif token in p.get("name", "").lower():
                    token_matches += 2.0
                elif token in p.get("category", "").lower():
                    token_matches += 1.5
                elif any(token in tag.lower() for tag in p.get("occasion_tags", []) + p.get("mood_tags", [])):
                    token_matches += 1.0
                elif token in p.get("description", "").lower():
                    token_matches += 0.5
            sparse_score = token_matches / len(query_tokens)
            sparse_score = min(sparse_score, 1.0)
            
        # Combine visual score and sparse text score
        if not query or not query.strip():
            # Pure visual search
            hybrid_score = visual_score
        else:
            # Visual is prioritized, but text refinement acts as an booster/modifier
            # 0.7 visual weight, 0.3 text sparse weight
            hybrid_score = 0.7 * visual_score + 0.3 * sparse_score
            
        scored_items.append({
            "product_id": p_id,
            "metadata": {
                "product_id": p_id,
                "name": p["name"],
                "category": p.get("category", ""),
                "price": p["price"]
            },
            "distance": distance,
            "hybrid_score": hybrid_score
        })
        
    # Sort by hybrid_score descending
    scored_items.sort(key=lambda x: -x["hybrid_score"])
    
    return scored_items[:top_k]

def search_policies(query: str, top_k: int = 2) -> list:
    results = get_policies_text_collection().query(
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

def seed_vector_store():
    # Clear collections if they exist to prevent orphan/placeholder embeddings
    client = get_chroma_client()
    for col_name in ["products_text", "policies_text", "products_image"]:
        try:
            client.delete_collection(col_name)
        except Exception:
            pass

    products_file = os.path.join(BASE_DIR, "data", "products.json")
    if os.path.exists(products_file):
        with open(products_file, "r", encoding="utf-8") as f:
            products = json.load(f)
        for p in products:
            add_product_text(
                product_id=p["id"],
                name=p["name"],
                description=p["description"],
                occasion_tags=p["occasion_tags"],
                mood_tags=p["mood_tags"],
                category=p["category"],
                price=p["price"]
            )
            
            try:
                img_path = p.get("image_url", "")
                if img_path.startswith("/static/"):
                    local_img_file = os.path.join(BASE_DIR, img_path.lstrip("/"))
                else:
                    local_img_file = img_path
                
                # Option (a): Only index image if it exists on disk, skipping placeholders
                if img_path and os.path.exists(local_img_file):
                    with open(local_img_file, "rb") as img_f:
                        img_bytes = img_f.read()
                    add_product_image(p["id"], img_bytes)
                else:
                    print(f"Skipping indexing image embedding for product '{p['id']}' as no real image was found.")
            except Exception as ex:
                print(f"Skipped image seed for {p['id']}: {ex}")
                
        print(f"Indexed {len(products)} products in text and visual search collections.")

    policy_file = os.path.join(BASE_DIR, "policies", "return_policy.md")
    if os.path.exists(policy_file):
        with open(policy_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        sections = content.split("\n## ")
        intro = sections[0]
        add_policy_chunk("intro", intro.strip(), {"section": "introduction"})
        
        for idx, sec in enumerate(sections[1:]):
            lines = sec.split("\n")
            title = lines[0]
            body = "\n".join(lines[1:])
            add_policy_chunk(
                f"policy_sec_{idx}",
                f"## {title}\n{body}".strip(),
                {"section": title}
            )
        print("Indexed return policy document.")
