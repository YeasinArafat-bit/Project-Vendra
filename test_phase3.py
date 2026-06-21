import os
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage
from agent_graph import graph
from database import SessionLocal
from models import Cart, CartItem, ProductVariant

load_dotenv()

def print_messages(messages):
    for m in messages:
        sender = "User" if isinstance(m, HumanMessage) else "Agent"
        print(f"{sender}: {m.content}")

def main():
    print("--- Vendra Phase 3 LangGraph Integration Test ---")
    
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or api_key.startswith("your_"):
        print("\n[WARNING] ANTHROPIC_API_KEY is not configured in .env!")
        print("Simulation Mode: Visualizing the graph compiled nodes.")
        print(f"Compiled nodes: {list(graph.nodes.keys())}")
        return
        
    # State tracking simulation over multiple turns
    state = {
        "messages": [],
        "customer_id": 1,
        "cart_id": None,
        "current_order_id": None,
        "selected_product_id": None,
        "selected_size": None,
        "active_node": "general",
        "intent": "general"
    }
    
    turns = [
        "Hi, I'm looking for some casual cotton canvas sneakers.",
        "Show me details for the sneaker with product ID 5 (Urban Comfort Sneaker).",
        "Add size 9 of this shoe to my cart please.",
        "Can I see what is currently in my cart?"
    ]
    
    for i, user_input in enumerate(turns):
        print(f"\n================ Turn {i+1} ================")
        # Append user message to state
        state["messages"].append(HumanMessage(content=user_input))
        
        # Invoke Graph
        output = graph.invoke(state)
        
        # Update our simulation state from graph return
        state["messages"] = list(output["messages"])
        state["cart_id"] = output.get("cart_id")
        state["intent"] = output.get("intent")
        state["active_node"] = output.get("active_node")
        
        print(f"Intent classified: {output.get('intent')}")
        print(f"Active node path: {output.get('active_node')}")
        print(f"Cart ID: {output.get('cart_id')}")
        
        # Print the last message from agent
        last_msg = state["messages"][-1]
        print(f"Agent response:\n{last_msg.content}")

if __name__ == "__main__":
    main()
