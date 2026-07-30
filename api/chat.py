from flask import Flask, request, jsonify
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

app = Flask(__name__)


@app.route('/api/chat', methods=['POST', 'OPTIONS'])
def chat():
    if request.method == 'OPTIONS':
        resp = jsonify({})
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return resp

    try:
        data = request.get_json()
        user_message = data.get('message')
        session_id = data.get('session_id', 'default')

        if not user_message:
            return jsonify({'error': 'メッセージが空です'}), 400

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

        resp = jsonify({'reply': ai_reply})
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp

    except Exception as e:
        print(f'エラー: {str(e)}')
        resp = jsonify({'error': str(e)})
        resp.status_code = 500
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp
