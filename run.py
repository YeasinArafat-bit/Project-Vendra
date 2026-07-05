import subprocess
import sys
import os
import time

def main():
    print("🚀 Starting Vendra Development Servers...")

    # Resolve paths
    project_root = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(project_root, ".venv_vendra", "Scripts", "python.exe")
    venv_uvicorn = os.path.join(project_root, ".venv_vendra", "Scripts", "uvicorn.exe")
    venv_streamlit = os.path.join(project_root, ".venv_vendra", "Scripts", "streamlit.exe")

    # Fallback to system executables if virtual env is not found
    if not os.path.exists(venv_python):
        venv_python = sys.executable
        venv_uvicorn = "uvicorn"
        venv_streamlit = "streamlit"

    # Step 1: Seed the database
    print("\n📦 Seeding vector store...")
    try:
        subprocess.run([venv_python, "seed.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Seeding failed: {e}. Attempting to start servers anyway...")

    # Step 2: Start FastAPI Webhook server
    print("\n⚡ Starting FastAPI Backend on http://localhost:8000...")
    fastapi_proc = subprocess.Popen([
        venv_uvicorn, "main:app", "--reload", "--port", "8000", "--workers", "1"
    ])

    # Wait a second for FastAPI to start up
    time.sleep(1.5)

    # Step 3: Start Streamlit Frontend
    print("\n👟 Starting Streamlit UI on http://localhost:8501...")
    try:
        streamlit_proc = subprocess.Popen([
            venv_streamlit, "run", "app.py"
        ])
        
        # Keep script running while sub-processes are active
        while True:
            if fastapi_proc.poll() is not None:
                print("⚠️ FastAPI backend exited unexpectedly.")
                break
            if streamlit_proc.poll() is not None:
                print("⚠️ Streamlit frontend exited.")
                break
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n🛑 Stopping all Vendra services...")
    finally:
        fastapi_proc.terminate()
        try:
            streamlit_proc.terminate()
        except NameError:
            pass
        print("Goodbye!")

if __name__ == "__main__":
    main()
