import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

def test_models():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("API Key not found.")
        return
        
    primary_env = os.getenv("PRIMARY_LLM_MODEL", "gemini-2.5-flash")
    secondary_env = os.getenv("SECONDARY_LLM_MODEL", "gemini-1.5-flash")
    
    models_to_test = [
        primary_env,
        secondary_env,
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash-lite",
        "gemini-flash-latest",
        "gemini-pro-latest"
    ]
    
    for model_name in models_to_test:
        try:
            print(f"Testing model: {model_name}...")
            llm = ChatGoogleGenerativeAI(
                model=model_name,
                temperature=0,
                google_api_key=api_key
            )
            response = llm.invoke("Hi, respond with 'success'.")
            print(f"--> Success! Response: {response.content.strip()}")
            print(f"Use this model name: {model_name}\n")
            return model_name
        except Exception as e:
            print(f"--> Failed for {model_name}: {e}\n")
            
if __name__ == "__main__":
    test_models()
