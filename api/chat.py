from http.server import BaseHTTPRequestHandler
import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from _utils import (
    get_client,
    get_conversation_history,
    save_conversation_history,
    build_context_with_blog,
    system_prompt,
)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            user_message = data.get('message')
            session_id = data.get('session_id', self.client_address[0] if self.client_address else 'default')

            if not user_message:
                self._send_json({'error': 'メッセージが空です'}, 400)
                return

            # Firestoreから会話履歴を取得
            messages = get_conversation_history(session_id)

            # ユーザーメッセージを追加
            messages.append({
                'role': 'user',
                'content': user_message
            })

            # 関連ブログ記事をコンテキストとして追加
            blog_context = build_context_with_blog(user_message)
            enhanced_system_prompt = system_prompt
            if blog_context:
                enhanced_system_prompt += f"\n\n以下はあなた（康揮）が書いたブログ記事の内容です。質問に関連する場合は、この情報を参考にして回答してください。ただし、話し方のスタイルは崩さないでください。{blog_context}"

            # Claude API に送信
            response = get_client().messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=200,
                system=enhanced_system_prompt,
                messages=messages
            )

            ai_reply = response.content[0].text

            # AIの返答を履歴に追加
            messages.append({
                'role': 'assistant',
                'content': ai_reply
            })

            # Firestoreに会話履歴を保存
            save_conversation_history(session_id, messages)

            self._send_json({'reply': ai_reply})

        except Exception as e:
            print(f'エラー: {str(e)}')
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
