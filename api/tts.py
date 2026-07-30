from flask import Flask, request, jsonify, Response
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import requests as http_requests
from _utils import correct_reading, split_text

app = Flask(__name__)


@app.route('/api/tts', methods=['POST', 'OPTIONS'])
@app.route('/', methods=['POST', 'OPTIONS'])
def tts():
    if request.method == 'OPTIONS':
        resp = jsonify({})
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return resp

    try:
        data = request.get_json()
        text = data.get('text')

        if not text:
            return jsonify({'error': 'テキストが空です'}), 400

        # 読み仮名を修正
        text = correct_reading(text)

        # ElevenLabs API設定
        elevenlabs_api_key = os.environ.get('ELEVENLABS_API_KEY')
        voice_id = os.environ.get('ELEVENLABS_VOICE_ID', 'nqkmNHx4hSecnBDJh39A')

        if not elevenlabs_api_key:
            return jsonify({'error': 'ElevenLabs APIキーが設定されていません'}), 500

        # テキストを分割
        text_chunks = split_text(text, max_length=100)

        # 各チャンクを音声に変換して結合
        audio_chunks = []

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": elevenlabs_api_key
        }

        for chunk in text_chunks:
            payload = {
                "text": chunk,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.7,
                    "similarity_boost": 0.85,
                    "style": 0.0,
                    "use_speaker_boost": True
                }
            }

            resp = http_requests.post(url, json=payload, headers=headers)

            if resp.status_code != 200:
                return jsonify({'error': f'音声生成エラー: {resp.text}'}), 500

            audio_chunks.append(resp.content)

        # 音声データを結合
        combined_audio = b''.join(audio_chunks)

        response = Response(combined_audio, mimetype='audio/mpeg')
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Cache-Control'] = 'no-cache'
        return response

    except Exception as e:
        print(f'TTSエラー: {str(e)}')
        return jsonify({'error': str(e)}), 500
