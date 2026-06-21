import os
import io
from sqlalchemy.orm import Session
from PIL import Image, ImageDraw, ImageFont

from database import engine, SessionLocal, Base
from models import Product, ProductVariant, Customer
from services.search import (
    add_product_text, 
    add_product_image, 
    add_policy_chunk, 
    products_text_collection, 
    products_image_collection, 
    policies_text_collection
)

# Colors map for generating placeholder product images matching their description
COLOR_MAP = {
    "brown": (139, 69, 19),
    "black": (0, 0, 0),
    "grey": (128, 128, 128),
    "olive": (85, 107, 47),
    "white": (245, 245, 245),
    "red": (220, 20, 60),
    "tan": (210, 180, 140),
    "navy blue": (0, 0, 128),
    "black/white": (50, 50, 50)
}

def generate_mock_shoe_image(name: str, color_name: str) -> bytes:
    """
    Generate a 224x224 RGB image representation of a shoe using PIL.
    Draws a colored block representing the shoe color and prints the product name.
    This creates valid image bytes that CLIP can embed.
    """
    img = Image.new("RGB", (224, 224), color=(240, 240, 240))
    draw = ImageDraw.Draw(img)
    
    # Get color
    rgb = COLOR_MAP.get(color_name.lower(), (100, 100, 100))
    
    # Draw a representing shape (e.g. a shoe silhouette mock block)
    draw.rectangle([20, 80, 204, 160], fill=rgb, outline=(0, 0, 0), width=2)
    draw.polygon([(20, 80), (60, 40), (120, 80)], fill=rgb, outline=(0, 0, 0))
    
    # Draw simple sole
    draw.rectangle([15, 160, 209, 175], fill=(200, 200, 200), outline=(0, 0, 0))
    
    # Text
    draw.text((10, 190), name[:30], fill=(0, 0, 0))
    
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    return img_byte_arr.getvalue()

def seed_db():
    print("Initialising database tables...")
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    try:
        # Clear existing data to ensure re-runnability
        print("Clearing old data...")
        db.query(ProductVariant).delete()
        db.query(Product).delete()
        db.query(Customer).delete()
        db.commit()
        
        # Reset Chroma collections
        print("Clearing old vector embeddings...")
        try:
            # We can clear collections by deleting their documents using a dummy condition or recreate them
            # Let's delete all documents in collections using delete() with ids list
            text_ids = products_text_collection.get()["ids"]
            if text_ids:
                products_text_collection.delete(ids=text_ids)
                
            img_ids = products_image_collection.get()["ids"]
            if img_ids:
                products_image_collection.delete(ids=img_ids)
                
            pol_ids = policies_text_collection.get()["ids"]
            if pol_ids:
                policies_text_collection.delete(ids=pol_ids)
        except Exception as e:
            print(f"Error resetting vector database: {e}")
            
        print("Seeding new products...")
        
        products_data = [
            {
                "name": "Classic Leather Oxford",
                "category": "formal",
                "description": "Handcrafted premium Italian leather dress shoes. Elegant, polished, and timeless for professional settings.",
                "color": "Brown",
                "occasion_tags": "wedding, formal, business, office",
                "mood_tags": "elegant, professional, classic, polished",
                "price": 120.00
            },
            {
                "name": "Midnight Velvet Derby",
                "category": "formal",
                "description": "Sleek velvet dress shoes with a subtle sheen, perfect for black-tie galas and evening weddings.",
                "color": "Black",
                "occasion_tags": "wedding, formal, party, gala",
                "mood_tags": "elegant, bold, premium, luxury",
                "price": 145.00
            },
            {
                "name": "CloudWalk Runner",
                "category": "sport",
                "description": "Breathable mesh running shoes with cloud-like foam cushioning for ultimate athletic comfort.",
                "color": "Grey",
                "occasion_tags": "sport, running, workout, casual",
                "mood_tags": "comfortable, active, lightweight",
                "price": 85.00
            },
            {
                "name": "TrailBlaze Hiker",
                "category": "sport",
                "description": "Rugged, waterproof hiking shoes with a high-grip rubber outsole for all-terrain adventure.",
                "color": "Olive",
                "occasion_tags": "sport, hiking, outdoor, adventure",
                "mood_tags": "durable, rugged, protective",
                "price": 110.00
            },
            {
                "name": "Urban Comfort Sneaker",
                "category": "casual",
                "description": "Minimalist everyday sneakers made of organic cotton canvas. Versatile, clean, and lightweight.",
                "color": "White",
                "occasion_tags": "casual, travel, daily",
                "mood_tags": "comfortable, minimal, clean, simple",
                "price": 65.00
            },
            {
                "name": "Veloce Athletic Trainer",
                "category": "sport",
                "description": "High-performance training shoes built with responsive support for gym and CrossFit workouts.",
                "color": "Red",
                "occasion_tags": "sport, gym, crossfit",
                "mood_tags": "bold, energetic, stable",
                "price": 95.00
            },
            {
                "name": "Sunset Leather Sandal",
                "category": "sandals",
                "description": "Hand-stitched premium leather sandals with an ergonomic footbed for effortless beach-to-street walks.",
                "color": "Tan",
                "occasion_tags": "casual, beach, summer, travel",
                "mood_tags": "comfortable, relaxed, breezy",
                "price": 55.00
            },
            {
                "name": "Metro Slip-on",
                "category": "casual",
                "description": "Easy slip-on canvas shoes. Perfect for quick errands, lounging, and lazy Sunday strolls.",
                "color": "Navy Blue",
                "occasion_tags": "casual, daily, lounging",
                "mood_tags": "comfortable, relaxed, convenient",
                "price": 48.00
            },
            {
                "name": "Gladiator Strap Sandal",
                "category": "sandals",
                "description": "Fashion-forward strappy sandals with adjustable buckles for a bold summer statement.",
                "color": "Black",
                "occasion_tags": "casual, summer, festival, party",
                "mood_tags": "bold, stylish, trendy",
                "price": 60.00
            },
            {
                "name": "Elite Chelsea Boot",
                "category": "formal",
                "description": "Sleek suede Chelsea boots with elastic side panels. Bridges the gap between casual and formal.",
                "color": "Tan",
                "occasion_tags": "formal, casual, office, evening",
                "mood_tags": "elegant, stylish, modern",
                "price": 130.00
            },
            {
                "name": "WaveBreeze Active Slide",
                "category": "sandals",
                "description": "Waterproof, cushioned slip-on slides, ideal for pool-side lounging or post-workout recovery.",
                "color": "Black",
                "occasion_tags": "casual, pool, beach, recovery",
                "mood_tags": "comfortable, casual, lightweight",
                "price": 35.00
            },
            {
                "name": "Brogue Heritage Boot",
                "category": "formal",
                "description": "Classic wingtip brogue dress boots in rich tan grain leather with intricate perforation details.",
                "color": "Tan",
                "occasion_tags": "wedding, formal, winter",
                "mood_tags": "elegant, classic, premium, detailed",
                "price": 150.00
            },
            {
                "name": "Retro Street High-Top",
                "category": "casual",
                "description": "Vintage-inspired high-top leather sneakers with a rubber toe cap and padded ankle collar.",
                "color": "Black/White",
                "occasion_tags": "casual, street, concert",
                "mood_tags": "bold, retro, trendy",
                "price": 75.00
            },
            {
                "name": "FlexFit Knit Sneaker",
                "category": "casual",
                "description": "Sock-like stretch knit sneakers that mold to your feet. The ultimate lightweight walking shoe.",
                "color": "Black",
                "occasion_tags": "casual, travel, walking",
                "mood_tags": "comfortable, minimal, flexible",
                "price": 70.00
            },
            {
                "name": "Patent Gala Pump",
                "category": "formal",
                "description": "Ultra-glossy black patent leather formal shoes designed for weddings and black-tie ceremonies.",
                "color": "Black",
                "occasion_tags": "wedding, formal, gala, ballroom",
                "mood_tags": "elegant, polished, premium, luxury",
                "price": 140.00
            }
        ]

        # Directory to save mock images locally
        images_dir = os.path.join(os.path.dirname(__file__), "static", "images")
        os.makedirs(images_dir, exist_ok=True)
        
        for p_info in products_data:
            # Create SQLite product
            product = Product(
                name=p_info["name"],
                category=p_info["category"],
                description=p_info["description"],
                color=p_info["color"],
                occasion_tags=p_info["occasion_tags"],
                mood_tags=p_info["mood_tags"],
                price=p_info["price"],
                image_url=f"/static/images/{p_info['name'].lower().replace(' ', '_')}.png"
            )
            db.add(product)
            db.flush()  # Populates product.id
            
            # Generate mock image bytes
            img_bytes = generate_mock_shoe_image(p_info["name"], p_info["color"])
            
            # Save mock image file locally
            img_filename = f"{p_info['name'].lower().replace(' ', '_')}.png"
            with open(os.path.join(images_dir, img_filename), "wb") as f:
                f.write(img_bytes)
            
            # Generate variants (sizes 6-11)
            # Vary the stock quantity, setting some sizes to 0 stock
            for size in ["6", "7", "8", "9", "10", "11"]:
                # Size 9 for Classic Leather Oxford has 0 stock (out of stock path test)
                if p_info["name"] == "Classic Leather Oxford" and size == "9":
                    stock = 0
                elif p_info["name"] == "CloudWalk Runner" and size == "11":
                    stock = 0
                else:
                    stock = 10  # Standard stock
                    
                variant = ProductVariant(
                    product_id=product.id,
                    size=size,
                    stock_quantity=stock
                )
                db.add(variant)
            
            # Add to Chroma Product text collection
            add_product_text(
                product_id=product.id,
                name=product.name,
                description=product.description,
                occasion_tags=product.occasion_tags,
                mood_tags=product.mood_tags,
                category=product.category,
                color=product.color
            )
            
            # Add to Chroma Product image collection (CLIP)
            add_product_image(
                product_id=product.id,
                image_bytes=img_bytes
            )
            
        # Seed a test customer
        test_customer = Customer(
            name="Alice Smith",
            email="alice@example.com"
        )
        db.add(test_customer)
        db.commit()
        print(f"Successfully seeded {len(products_data)} products and 1 customer in SQLite database.")
        
        # Seed Policy Document into Chroma
        print("Embedding return policy document into vector store...")
        policy_path = os.path.join(os.path.dirname(__file__), "policies", "return_policy.md")
        with open(policy_path, "r", encoding="utf-8") as f:
            policy_text = f.read()
            
        # Simple chunker: split policy by markdown headers
        sections = policy_text.split("## ")
        # Header section is the first element
        header = sections[0].strip()
        if header:
            add_policy_chunk(
                chunk_id="policy_header",
                text=header,
                metadata={"title": "Vendra Return Policy Header"}
            )
            
        for idx, sec in enumerate(sections[1:]):
            lines = sec.strip().split("\n")
            title = lines[0].strip()
            content = "\n".join(lines[1:]).strip()
            full_chunk = f"Section: {title}\n{content}"
            add_policy_chunk(
                chunk_id=f"policy_sec_{idx+1}",
                text=full_chunk,
                metadata={"title": title}
            )
            
        print("Seeding completed successfully!")
        
    except Exception as e:
        db.rollback()
        print(f"Seeding failed with error: {e}")
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    seed_db()
