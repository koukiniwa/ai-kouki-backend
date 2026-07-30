from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route('/', methods=['GET', 'POST', 'OPTIONS'])
def test():
    return jsonify({'status': 'ok', 'method': request.method, 'path': request.path})
