from http.server import BaseHTTPRequestHandler
import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import requests
from _utils import correct_reading, split_text


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            text = data.get('text')

            if not text:
                self._send_json({'error': 'テキストが空です'}, 400)
                return

            # 読み仮名を修正
            text = correct_reading(text)

            # ElevenLabs API設定
            elevenlabs_api_key = os.environ.get('ELEVENLABS_API_KEY')
            voice_id = os.environ.get('ELEVENLABS_VOICE_ID', 'nqkmNHx4hSecnBDJh39A')

            if not elevenlabs_api_key:
                self._send_json({'error': 'ElevenLabs APIキーが設定されていません'}, 500)
                return

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

                response = requests.post(url, json=payload, headers=headers)

                if response.status_code != 200:
                    self._send_json({'error': f'音声生成エラー: {response.text}'}, 500)
                    return

                audio_chunks.append(response.content)

            # 音声データを結合
            combined_audio = b''.join(audio_chunks)

            # 音声データを返す
            self.send_response(200)
            self.send_header('Content-Type', 'audio/mpeg')
            self.send_header('Content-Length', str(len(combined_audio)))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(combined_audio)

        except Exception as e:
            print(f'TTSエラー: {str(e)}')
            self._send_json({'error': str(e)}, 500)

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
