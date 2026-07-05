import os
from dotenv import load_dotenv

# Load env variables
load_dotenv(override=True)

# Active backend adapter ("json", "shopify", or "woocommerce")
ADAPTER = os.getenv("ADAPTER", "json")
