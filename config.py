import os
import logging
from dotenv import load_dotenv
from sqlalchemy import create_engine

# Configure basic logger for config warnings
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("config")

# Load env variables
load_dotenv(override=True)

# Active backend adapter ("json", "postgres", "shopify", or "woocommerce")
ADAPTER = os.getenv("ADAPTER", "json")

def validate_config() -> None:
    """
    Validates all environment configurations on application startup.
    Fails fast for required keys, warns for optional ones.
    """
    # 1. Validate Groq API Key (Required for LLM multi-agent graph)
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key or not groq_key.strip():
        raise RuntimeError(
            "GROQ_API_KEY environment variable is required for Vendra multi-agent graph execution. "
            "Please generate a key at https://console.groq.com/ and configure it in your environment."
        )

    # 2. Validate Secure Admin API Key (Required for admin panel endpoints)
    admin_key = os.getenv("ADMIN_API_KEY")
    if not admin_key or not admin_key.strip():
        raise RuntimeError("CRITICAL ERROR: ADMIN_API_KEY environment variable is unset. Vendra cannot start without a secure admin API key configuration.")

    # 2.5 Validate JWT Secret Key (Required for customer authentication)
    jwt_secret = os.getenv("JWT_SECRET_KEY")
    if not jwt_secret or not jwt_secret.strip():
        raise RuntimeError(
            "JWT_SECRET_KEY environment variable is required for Vendra customer authentication. "
            "Please configure a strong key in your environment."
        )

    # 3. Validate Adapter-Specific Keys if they are active
    adapter_name = str(ADAPTER).lower().strip()
    if adapter_name == "shopify":
        shopify_url = os.getenv("SHOPIFY_URL")
        shopify_key = os.getenv("SHOPIFY_API_KEY")
        if not shopify_url or not shopify_key:
            raise RuntimeError(
                "SHOPIFY_URL and SHOPIFY_API_KEY environment variables are required when ADAPTER is set to 'shopify'."
            )
    elif adapter_name == "woocommerce":
        wc_url = os.getenv("WC_URL")
        wc_key = os.getenv("WC_KEY")
        wc_secret = os.getenv("WC_SECRET")
        if not wc_url or not wc_key or not wc_secret:
            raise RuntimeError(
                "WC_URL, WC_KEY, and WC_SECRET environment variables are required when ADAPTER is set to 'woocommerce'."
            )

    # 4. Database Connection Validation (Optional presence, required connectivity if configured)
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
            
        try:
            # Check SQLite db path parent dir exists
            if "sqlite" in db_url:
                db_path = db_url.replace("sqlite:///", "")
                parent_dir = os.path.dirname(db_path)
                if parent_dir and not os.path.exists(parent_dir):
                    os.makedirs(parent_dir, exist_ok=True)
                    
            engine = create_engine(db_url)
            with engine.connect() as conn:
                pass
        except Exception as e:
            raise RuntimeError(
                f"Failed to connect to database at startup using DATABASE_URL '{db_url}': {e}"
            ) from e

    # 5. Redis Connection Validation (Optional)
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        try:
            import redis
            r = redis.Redis.from_url(redis_url, socket_connect_timeout=2)
            r.ping()
            logger.info("Successfully connected to Redis cache/store.")
        except Exception as e:
            logger.warning(
                f"Redis is configured at '{redis_url}' but is UNREACHABLE: {e}. "
                "App will fall back to in-memory cart storage and cache bypass."
            )
