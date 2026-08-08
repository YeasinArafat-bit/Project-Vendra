import subprocess
import sys
import os
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

def main():
    print("🚀 Starting Vendra Development Servers...")

    # Check command line arguments
    with_streamlit = "--with-streamlit" in sys.argv

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

    # Step 2: Check frontend dependencies and install if missing
    frontend_dir = os.path.join(project_root, "frontend")
    node_modules_dir = os.path.join(frontend_dir, "node_modules")
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"

    if not os.path.exists(node_modules_dir):
        print("\n📦 Node modules missing in frontend/ directory. Installing dependencies via npm install...")
        try:
            subprocess.run([npm_cmd, "install"], cwd=frontend_dir, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"⚠️ Warning: Failed to run npm install automatically: {e}")
            print("Please make sure Node.js is installed and run 'npm install' manually inside the 'frontend/' directory.")

    # Step 3: Start FastAPI Webhook server
    print("\n⚡ Starting FastAPI Backend on http://localhost:8000...")
    fastapi_proc = subprocess.Popen([
        venv_uvicorn, "main:app", "--reload", "--port", "8000", "--workers", "1"
    ])

    # Wait a second for FastAPI to start up
    time.sleep(1.5)

    # Step 4: Start Streamlit Frontend (Fallback/Admin UI) if explicitly requested
    streamlit_proc = None
    if with_streamlit:
        print("\n👟 Starting Streamlit UI (Fallback/Admin) on http://localhost:8501...")
        streamlit_proc = subprocess.Popen([
            venv_streamlit, "run", "app.py"
        ])
    else:
        print("\nℹ️ Streamlit UI is disabled by default. Run with --with-streamlit to start it, or run 'streamlit run app.py' manually.")

    # Step 5: Start Next.js Frontend (Production Frontend)
    print("\n🌐 Starting Next.js Production Frontend on http://localhost:3000...")
    nextjs_proc = None
    try:
        nextjs_proc = subprocess.Popen([
            npm_cmd, "run", "dev"
        ], cwd=frontend_dir)
    except Exception as e:
        print(f"⚠️ Failed to start Next.js frontend: {e}")

    # Keep script running while sub-processes are active
    try:
        while True:
            if fastapi_proc.poll() is not None:
                print("⚠️ FastAPI backend exited unexpectedly.")
                break
            if streamlit_proc and streamlit_proc.poll() is not None:
                print("⚠️ Streamlit fallback/admin UI exited.")
                break
            if nextjs_proc and nextjs_proc.poll() is not None:
                print("⚠️ Next.js frontend exited unexpectedly.")
                break
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n🛑 Stopping all Vendra services...")
    finally:
        print("Stopping backend server...")
        fastapi_proc.terminate()
        if streamlit_proc:
            print("Stopping Streamlit server...")
            try:
                streamlit_proc.terminate()
            except Exception:
                pass
        if nextjs_proc:
            print("Stopping Next.js server...")
            try:
                nextjs_proc.terminate()
            except Exception:
                pass
        print("Goodbye!")

if __name__ == "__main__":
    main()
