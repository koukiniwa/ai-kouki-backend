from flask import Flask, jsonify

app = Flask(__name__)


@app.route('/', methods=['GET'])
@app.route('/api/index', methods=['GET'])
def index():
    return jsonify({'message': 'AI こうき バックエンド API'})
