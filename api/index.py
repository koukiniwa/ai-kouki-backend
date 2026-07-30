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


def cors_response(data, status=200):
    resp = jsonify(data)
    resp.status_code = status
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp


def handle_options():
    return cors_response({})


def handle_chat():
    try:
        data = request.get_json(force=True)
        user_message = data.get('message')
        session_id = data.get('session_id', 'default')

        if not user_message:
            return cors_response({'error': 'メッセージが空です'}, 400)

        messages = get_conversation_history(session_id)

        messages.append({
            'role': 'user',
            'content': user_message
        })

        blog_context = build_context_with_blog(user_message)
        enhanced_system_prompt = system_prompt
        if blog_context:
            enhanced_system_prompt += f"\n\n以下はあなた（康揮）が書いたブログ記事の内容です。質問に関連する場合は、この情報を参考にして回答してください。ただし、話し方のスタイルは崩さないでください。{blog_context}"

        response = get_client().messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=200,
            system=enhanced_system_prompt,
            messages=messages
        )

        ai_reply = response.content[0].text

        messages.append({
            'role': 'assistant',
            'content': ai_reply
        })

        save_conversation_history(session_id, messages)

        return cors_response({'reply': ai_reply})

    except Exception as e:
        print(f'エラー: {str(e)}')
        return cors_response({'error': str(e)}, 500)


@app.route('/', defaults={'path': ''}, methods=['GET', 'POST', 'OPTIONS'])
@app.route('/<path:path>', methods=['GET', 'POST', 'OPTIONS'])
def catch_all(path):
    route = request.args.get('route', '')

    if request.method == 'OPTIONS':
        return handle_options()

    if route == 'chat':
        if request.method == 'POST':
            return handle_chat()
        return cors_response({'error': 'Method not allowed'}, 405)

    return cors_response({
        'message': 'AI こうき バックエンド API',
        'debug_method': request.method,
        'debug_route': route,
        'debug_path': request.path,
        'debug_content_type': request.content_type,
        'debug_data_length': request.content_length,
    })
