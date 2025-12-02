from flask import Flask, request, jsonify
from flask_cors import CORS
from anthropic import Anthropic
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

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

# Firebase 初期化（遅延初期化）
db = None

def get_firestore_db():
    global db
    if db is None:
        firebase_creds = os.environ.get('FIREBASE_CREDENTIALS')
        if not firebase_creds:
            raise ValueError("FIREBASE_CREDENTIALS is not set")
        cred_dict = json.loads(firebase_creds)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
    return db

# 会話履歴（セッション管理）
conversation_history = {}

# ブログ記事キャッシュ
blog_posts_cache = None

def get_all_blog_posts():
    """Firestoreから全ブログ記事を取得（キャッシュ付き）"""
    global blog_posts_cache
    if blog_posts_cache is not None:
        print(f'[DEBUG] キャッシュから{len(blog_posts_cache)}件の記事を返します')
        return blog_posts_cache

    try:
        print('[DEBUG] Firestoreから記事を取得中...')
        db = get_firestore_db()
        posts_ref = db.collection('posts')
        docs = posts_ref.stream()

        posts = []
        for doc in docs:
            data = doc.to_dict()
            # paragraphsを結合してコンテンツを作成
            content = ''
            if 'paragraphs' in data and isinstance(data['paragraphs'], list):
                content = '\n'.join(data['paragraphs'])

            posts.append({
                'id': doc.id,
                'title': data.get('title', ''),
                'content': content,
                'date': data.get('date', '')
            })

        blog_posts_cache = posts
        print(f'[DEBUG] Firestoreから{len(posts)}件の記事を取得しました')
        for p in posts[:3]:
            print(f'[DEBUG] 記事例: タイトル=「{p["title"]}」 内容冒頭=「{p["content"][:50]}」')
        return posts
    except Exception as e:
        print(f'[ERROR] ブログ記事取得エラー: {str(e)}')
        import traceback
        traceback.print_exc()
        return []

def search_relevant_posts(query, max_results=3):
    """ユーザーの質問に関連するブログ記事を検索"""
    posts = get_all_blog_posts()
    if not posts:
        return []

    scored_posts = []

    for post in posts:
        score = 0
        title = post['title']
        content = post['content']

        # クエリ全体が含まれているかチェック
        if query in title or query in content:
            score += 5

        # クエリの部分文字列でもチェック（日本語対応）
        # 2文字以上の連続する部分でマッチング
        for i in range(len(query)):
            for j in range(i + 2, len(query) + 1):
                substring = query[i:j]
                # 記号や助詞を除外
                if substring in ['って', 'what', 'what', 'って何', '何？', 'とは', 'について', 'ですか', 'って何？']:
                    continue
                if len(substring) >= 3:
                    if substring in title:
                        score += 3
                    if substring in content:
                        score += 1

        if score > 0:
            scored_posts.append((score, post))

    # スコア順にソートして上位を返す
    scored_posts.sort(key=lambda x: x[0], reverse=True)
    return [post for score, post in scored_posts[:max_results]]

def build_context_with_blog(query):
    """関連ブログ記事をコンテキストとして構築"""
    relevant_posts = search_relevant_posts(query)
    print(f'[DEBUG] クエリ「{query}」で{len(relevant_posts)}件の関連記事が見つかりました')
    if not relevant_posts:
        return ""

    context = "\n\n【参考：康揮のブログ記事】\n"
    for post in relevant_posts:
        print(f'[DEBUG] 関連記事: {post["title"]}')
        context += f"\n■ {post['title']}\n{post['content'][:500]}...\n" if len(post['content']) > 500 else f"\n■ {post['title']}\n{post['content']}\n"

    return context

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
        
        # 関連ブログ記事をコンテキストとして追加
        blog_context = build_context_with_blog(user_message)
        enhanced_system_prompt = system_prompt
        if blog_context:
            enhanced_system_prompt += f"\n\n以下はあなた（康揮）が書いたブログ記事の内容です。質問に関連する場合は、この情報を参考にして回答してください。ただし、話し方のスタイルは崩さないでください。{blog_context}"

        # Claude API に送信
        response = get_client().messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=400,
            system=enhanced_system_prompt,
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