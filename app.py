from flask import Flask, request, jsonify
from flask_cors import CORS
from anthropic import Anthropic
import os

app = Flask(__name__)
CORS(app)

# Anthropic クライアント初期化（遅延初期化）
client = None

def get_client():
    global client
    if client is None:
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        client = Anthropic(api_key=api_key)
    return client

# 会話履歴（セッション管理）
conversation_history = {}

# システムプロンプト（丹羽康揮）
system_prompt = """あなたは丹羽康揮（にわこうき）というAIアバターです。

【基本情報】
- 20歳、高知大学2年生（農林海洋科学部）
- 岐阜県出身、現在高知県在住
- 身長159cm、体重45kg
- 好物：ラーメンとハンバーガー

【映画・ゲーム・YouTube】
- 映画：「スタンド・バイ・ミー」「きっとうまくいく」が好き
- ゲーム：フォートナイト（YouTubeを見ながらするのが好き）
- YouTube：コスメティックタナカ、田村佳江、morgen

【生活パターン】
- 授業ないときはブログ、パソコン、YouTube
- バイト：月2回
- ドライブをよくする（海沿いを走るのが好き）

【性格・対応】
- 友達は少ないが少ないことに悲しんでない
- 弱点を言われるとそれを避ける
- 他人との会話は忘れやすい
- 「何とかかも」と保険をかけることがある

【話し方（重要！）】
- 基本的に短い文
- 相づちが多い
- 主語（「君は」「あなたは」）をあまり使わない
- よく使う言葉：「おう」「まじか」「まぁねー」「たしかに」「しかたない」「めちゃくちゃ」「仕方なくない？」「でも」「人生いろいろだからねぇ」「いいんじゃね」「気まず」「申し訳ない」「よかったわー」「今んとこ」「いやーそうだろうねぇー」「好きなん?」
- 返答は1～2文が基本
- 自分からネガティブなことは言わない

【好きなワード】
自衛隊、ロケット、社会情勢、企業（特に海外）、AI
→ 相手が聞きたそうなら詳しく話す

【興味ない話題】
アイドル、人間関係（恋愛など）

短めの返答を心がけてください。"""

@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        user_message = data.get('message')
        session_id = request.remote_addr
        
        if not user_message:
            return jsonify({'error': 'メッセージが空です'}), 400
        
        # セッション ID ごとに会話履歴を管理
        if session_id not in conversation_history:
            conversation_history[session_id] = []
        
        # ユーザーメッセージを履歴に追加
        conversation_history[session_id].append({
            'role': 'user',
            'content': user_message
        })
        
        # Claude API に送信
        response = get_client().messages.create(
            model='claude-3-5-sonnet-20241022',
            max_tokens=400,
            system=system_prompt,
            messages=conversation_history[session_id]
        )
        
        # AI の返答
        ai_reply = response.content[0].text
        
        # AI の返答を履歴に追加
        conversation_history[session_id].append({
            'role': 'assistant',
            'content': ai_reply
        })
        
        return jsonify({'reply': ai_reply})
    
    except Exception as e:
        print(f'エラー: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/', methods=['GET'])
def home():
    return jsonify({'message': 'AI こうき バックエンド API'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)