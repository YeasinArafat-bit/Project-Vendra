import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from tools import search_products, check_stock, get_product_details

load_dotenv()

def get_llm():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key or api_key.startswith("your_"):
        print("\n[WARNING] GEMINI_API_KEY / GOOGLE_API_KEY is not configured in .env!")
        print("Simulation Mode: Running queries directly without LLM wrapper.")
        return None
    
    primary = os.getenv("PRIMARY_LLM_MODEL", "gemini-2.0-flash")
    secondary = os.getenv("SECONDARY_LLM_MODEL", "gemini-2.5-flash")
    for model_name in [primary, secondary]:
        try:
            llm = ChatGoogleGenerativeAI(
                model=model_name,
                temperature=0,
                google_api_key=api_key
            )
            # Test model connection quickly
            llm.invoke("Hi")
            print(f"Using model: {model_name}")
            return llm
        except Exception as e:
            print(f"[LLM WARNING] Failed to initialize model {model_name}: {e}")
    raise RuntimeError("Failed to initialize any Gemini models.")

def run_agent_turn(llm, user_message: str):
    print(f"\nUser: {user_message}")
    
    if llm is None:
        # LLM Bypass Mode
        print("Agent (Bypass): Let me resolve the correct tool...")
        if "Oxford" in user_message or "ID 1" in user_message or "ID: 1" in user_message:
            if "size 9" in user_message or "Size 9" in user_message:
                res = check_stock.invoke({"product_id": 1, "size": "9"})
            else:
                res = get_product_details.invoke({"product_id": 1})
        elif "CloudWalk" in user_message or "Runner" in user_message:
            res = check_stock.invoke({"product_id": 3, "size": "10"})
        else:
            res = "No matching tool simulation mapped for this test message."
        print(f"Tool Result:\n{res}")
        return
        
    messages = [HumanMessage(content=user_message)]
    llm_with_tools = llm.bind_tools([search_products, check_stock, get_product_details])
    
    ai_msg = llm_with_tools.invoke(messages)
    messages.append(ai_msg)
    
    if ai_msg.tool_calls:
        for tool_call in ai_msg.tool_calls:
            print(f"--> Agent wants to call tool: {tool_call['name']} with args {tool_call['args']}")
            
            if tool_call['name'] == "search_products":
                tool_output = search_products.invoke(tool_call['args'])
            elif tool_call['name'] == "check_stock":
                tool_output = check_stock.invoke(tool_call['args'])
            elif tool_call['name'] == "get_product_details":
                tool_output = get_product_details.invoke(tool_call['args'])
            else:
                tool_output = "Error: Tool not found."
                
            print(f"--> Tool Output: {tool_output}")
            
            messages.append(ToolMessage(
                content=tool_output,
                tool_call_id=tool_call['id'],
                name=tool_call['name']
            ))
            
        final_msg = llm_with_tools.invoke(messages)
        print(f"Agent: {final_msg.content}")
    else:
        print(f"Agent: {ai_msg.content}")

def main():
    print("--- Vendra Phase 2 Standalone Test ---")
    
    llm = get_llm()
    
    test_queries = [
        "Is the Classic Leather Oxford (ID 1) in size 9 in stock?",
        "Show me all details and sizes for product ID 1.",
        "Do you have CloudWalk Runner in size 10? How many are left?"
    ]
    
    for query in test_queries:
        run_agent_turn(llm, query)

if __name__ == "__main__":
    main()
