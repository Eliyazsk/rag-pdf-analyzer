import sys
import os
import traceback

# Add parent directory to path so app.py can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app import app
except Exception as e:
    tb = traceback.format_exc()
    try:
        from flask import Flask
        app = Flask(__name__)
        
        @app.route('/', defaults={'path': ''})
        @app.route('/<path:path>')
        def catch_all(path):
            return f"<h1>App Import Failed</h1><pre>{tb}</pre>", 500
    except ImportError:
        def app(environ, start_response):
            status = '500 Internal Server Error'
            headers = [('Content-type', 'text/html; charset=utf-8')]
            start_response(status, headers)
            body = f"<h1>App Import Failed (Flask missing)</h1><pre>{tb}</pre>".encode('utf-8')
            return [body]

