import os
import sys
import time
import threading
import webbrowser
import uvicorn
from api.index import app

def main():
    # Set default variables
    os.environ["OPENROUTER_MODEL"] = "google/gemini-2.5-flash"
    
    def open_browser():
        time.sleep(1.5)
        webbrowser.open("http://127.0.0.1:8000")
        
    threading.Thread(target=open_browser, daemon=True).start()
    
    print("Iniciando AutoExcel local...")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")

if __name__ == "__main__":
    main()
