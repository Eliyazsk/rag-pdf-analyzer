import sys
import os
import traceback
from flask import Flask

# Add parent directory to path so app.py can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app import app
except Exception as e:
    tb = traceback.format_exc()
    app = Flask(__name__)
    
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def catch_all(path):
        return f"<h1>App Import Failed</h1><pre>{tb}</pre>", 500

