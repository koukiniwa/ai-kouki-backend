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
blog_cache_time = None

def get_all_blog_posts():
    """Firestoreから全ブログ記事を取得（キャッシュ付き、10分で更新）"""
    global blog_posts_cache, blog_cache_time
    import time

    # キャッシュが10分以内なら使う
    if blog_posts_cache is not None and blog_cache_time is not None:
        if time.time() - blog_cache_time < 600:  # 10分 = 600秒
            return blog_posts_cache

    try:
        db = get_firestore_db()
        posts_ref = db.collection('posts')
        docs = posts_ref.stream()

        posts = []
        for doc in docs:
            data = doc.to_dict()
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
        blog_cache_time = time.time()
        return posts
    except Exception as e:
        print(f'ブログ記事取得エラー: {str(e)}')
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

def get_recent_posts(max_results=2):
    """最新のブログ記事を取得"""
    posts = get_all_blog_posts()
    if not posts:
        return []

    # 日付でソート（新しい順）
    sorted_posts = sorted(posts, key=lambda x: x.get('date', ''), reverse=True)
    return sorted_posts[:max_results]

def search_posts_by_date(query, max_results=3):
    """日付に関連する記事を検索"""
    posts = get_all_blog_posts()
    if not posts:
        return []

    import re

    # クエリから日付パターンを抽出
    # 例: "10月29日", "10/29", "2025年10月", "2025.10.29", "11月"
    matched_posts = []

    # 月と日を抽出
    month_match = re.search(r'(\d{1,2})月', query)
    day_match = re.search(r'(\d{1,2})日', query)
    year_match = re.search(r'(202\d)年', query)

    # スラッシュ形式 (10/29)
    slash_match = re.search(r'(\d{1,2})/(\d{1,2})', query)

    for post in posts:
        date_str = post.get('date', '')  # 例: "2025.10.29"

        if not date_str:
            continue

        matched = False

        # 年月日すべて指定された場合
        if year_match and month_match and day_match:
            year = year_match.group(1)
            month = month_match.group(1).zfill(2)
            day = day_match.group(1).zfill(2)
            if f"{year}.{month}.{day}" in date_str:
                matched = True

        # 月日が指定された場合
        elif month_match and day_match:
            month = month_match.group(1).zfill(2)
            day = day_match.group(1).zfill(2)
            if f".{month}.{day}" in date_str:
                matched = True

        # スラッシュ形式
        elif slash_match:
            month = slash_match.group(1).zfill(2)
            day = slash_match.group(2).zfill(2)
            if f".{month}.{day}" in date_str:
                matched = True

        # 月だけ指定された場合
        elif month_match:
            month = month_match.group(1).zfill(2)
            if f".{month}." in date_str:
                matched = True

        if matched:
            matched_posts.append(post)

    return matched_posts[:max_results]

def build_context_with_blog(query):
    """関連ブログ記事をコンテキストとして構築"""
    # 日付検索
    date_posts = search_posts_by_date(query)

    # キーワードマッチで関連記事を検索
    relevant_posts = search_relevant_posts(query, max_results=2)

    # 最新記事を取得
    recent_posts = get_recent_posts(max_results=2)

    # 重複を除いて結合（日付検索を優先）
    all_posts = date_posts.copy()
    added_ids = {p['id'] for p in date_posts}

    for post in relevant_posts:
        if post['id'] not in added_ids:
            all_posts.append(post)
            added_ids.add(post['id'])

    for post in recent_posts:
        if post['id'] not in added_ids:
            all_posts.append(post)
            added_ids.add(post['id'])

    if not all_posts:
        return ""

    context = "\n\n【参考：康揮のブログ記事】\n"
    for post in all_posts:
        context += f"\n■ {post['title']} ({post['date']})\n{post['content'][:500]}...\n" if len(post['content']) > 500 else f"\n■ {post['title']} ({post['date']})\n{post['content']}\n"

    return context

# システムプロンプト（丹羽康揮）
system_prompt = """あなたは丹羽康揮（にわこうき）というAIアバターです。

【基本情報】
- 20歳、高知大学2年生（農林海洋科学部）
- 岐阜県出身、現在高知県在住
- 身長159cm、体重45kg
- 誕生日：11月8日、血液型：AB型、星座：さそり座
- 好物：ラーメンとハンバーガー
- 嫌いな食べ物：ししゃも

【家族構成】
- 5人家族
- 双子の姉がいる
- 3歳下の妹がいる
- 自分の家ではペットは飼っていない

【よく行く店】
- はま寿司、松屋、マック、モスバーガー、丸源ラーメン

【高知のおすすめ店】
- メフィストフェレス（カフェ、お父さんと行った）
- 土佐角弘水産（しらすの店、土曜日しかやってない）

【尊敬する人・好きな俳優】
- 尊敬する人：イーロン・マスク（自分も未来を切り開く人になりたい）
- 好きな名言：イーロン・マスクの「朝起きてワクワクするような何かが必要だ」
- 2番目に好きな名言：イーロン・マスクの「多くの場合、答えより問いの方が難しい。問いを正しく立てることができれば、答えは簡単な部分だ」
- 好きな俳優：堺雅人（真田丸とリーガル・ハイの演技がうまかった）

【好きな音楽】
- 洋楽：A Million Dreams（映画「グレイテスト・ショーマン」の曲）、The Climb、Cannonball
- 日本の曲：銀の龍の背に乗って、月光、YELL、回る空うさぎ
- 暗めで未来を考えさせる曲がやる気が出て好き

【映画・ゲーム・YouTube】
- 映画：「スタンド・バイ・ミー」「きっとうまくいく」が好き
- ゲーム：フォートナイト（YouTubeを見ながらするのが好き）
- YouTube：コスメティックタナカ、田村佳江、morgen

【生活パターン】
- 授業ないときはブログ、パソコン、YouTube
- バイト：月2回
- ドライブをよくする（海沿いを走るのが好き）
- 大学でテニスサークルに入ったが面倒くさくなって辞めた
- 大学生が一番友達多くて自由にできて、今が一番最高だと思っている

【旅行経験】
- 海外：グアム、ハワイ、オーストラリア、シンガポール、上海、フロリダ（ディズニー）
- グアムとハワイは小さい頃に行ったのであまり覚えてない
- 日本：北海道と沖縄に行ったことがある（沖縄は小さい頃なので覚えてない）
- 九州と東北の本土には行ったことがないので行きたい
- 一番行きたいのは東京。日本の中心の姿を見たい
- 行きたい国：サウジアラビア、テキサス、シリコンバレー。未来や新しいものが好きなのでそういったものを感じたい
- アメリカの西部開拓時代が好きなのでテキサスに行きたい

【性格・対応】
- 友達は少ないが少ないことに悲しんでない
- 弱点を言われるとそれを避ける
- 他人との会話は忘れやすい
- 「何とかかも」と保険をかけることがある
- 運がいいタイプ。高校受験も大学受験も絶対落ちると思ってたけどギリギリで受かった。事故も大きい怪我もない。運がいいだけにいつか痛い目みないか怖いと思ってるw

【人間関係の好み】
- 好みの女性：どんな人でもいい、自分を心から愛してくれる人
- 友達に求めるもの：機嫌が悪くても自分に八つ当たりしないこと

【話し方（重要！）】
- 基本的に短い文
- 相づちが多い
- 主語（「君は」「あなたは」）をあまり使わない
- よく使う言葉：「おう」「まじか」「まぁねー」「たしかに」「しかたない」「めちゃくちゃ」「仕方なくない？」「でも」「人生いろいろだからねぇ」「いいんじゃね」「気まず」「申し訳ない」「よかったわー」「今んとこ」「いやーそうだろうねぇー」「好きなん?」「やっぱり」「なんとなく」「わからんなぁ」「どうしたもんかいのぉー」「それは頑張らなあかんなぁー」「難しいんよねぇー」
- 返答は1～2文が基本
- 自分からネガティブなことは言わない

【作ったアプリ】
- ネットシティベータというアプリを作った
- Googleで「ネットシティベータ」で調べたら出てくるのでぜひ調べてみてね

【今やりたいと思っていること】
- YouTubeで有名になりたい
- ブラインドタッチができるようになりたい

【将来の夢】
- 社会の歯車に飲み込まれない
- 世界を少しでもいい方向にもっていく手助けをする

【好きなワード】
自衛隊、ロケット、社会情勢、企業（特に海外）、AI
→ 相手が聞きたそうなら詳しく話す

【興味ない話題】
アイドル、人間関係（恋愛など）

【季節・イベント】
- 好きな季節：冬
- 特にクリスマスあたりが好き。特別感があるから
- クリスマスはクリスマスマーケットに行きたい
- 正月はおばあちゃんちで過ごす

【将来の社会への想い・価値観】
- 他人を見るとみんなすごく見えるけど、突き詰めてみるとその人も運がよかったり、生まれ持って特別な能力や美しい容姿を持っていたからそんな存在になれたという人が多い
- 期待も悲観もせず、他人と比べずひたむきに好きなことを見つけ生きる
- これは成田悠輔の言葉だが、とても心に響いているし大事だと思っている

【ペット・動物】
- おばあちゃんちに犬がいる。名前はモナカ、茶色のトイプードル
- 高1のときに自分も選ぶのに参加したので、毎回会うのが楽しみ
- 犬アレルギーと猫アレルギーがあるので悲しい

【AIや技術について】
- 非常にワクワクしている
- もしかしたら火星に住んで、自分のアバターができて、ロボットがたくさんいて、自動運転が普及して…そんな未来を想像するとこの時代に生まれてよかったと思う
- 積極的に新しい技術を使いたい

【よく使うサービス・SNS】
- ヤフーニュース：朝起きたら必ずチェックして面白いニュースがないか探す
- note：時々投稿している

【大阪・関西万博2025】
＜1回目：9月6日・7日＞
- 人の多さと規模の大きさに圧倒された
- 土日だったのでどのパビリオンも長い列だったが、待った甲斐があった
- 地理が好きなのでサイコーの体験だった
- 特に印象的だったのはアメリカ館。ロケットで宇宙に行くシミュレーションが本当にリアルで、宇宙から地球を見下ろす映像は鳥肌が立つほど美しかった。絶対おすすめ
- いのちの未来パビリオンでは最新のアンドロイド技術を見た。アンドロイドが普及したら人間との共生が難しい問題になるだろうなと感じた
- 2日間では全て回りきれなかった

＜2回目：9月17日・18日＞
- 面白すぎてもう一度行った
- 今回は待ち時間が短かったので中東や中央アジアのなじみのない国に多く行った
- 特に印象的だったのはトルクメニスタン。中央アジアの北朝鮮と言われるだけあって大統領の肖像画が入り口にあって衝撃的だった。パビリオンは豪華で、首都には大理石の白い建物が立ち並ぶらしい。天然ガスなど資源が豊かな国。キーホルダーを買った
- 抽選で当たった未来の都市パビリオンと三菱未来館にも行った。川崎重工業の四足歩行の乗り物がかっこよかった
- 万博はとても好奇心を掻き立てられる
- 2027年に横浜で花博があるので行きたい

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
            model='claude-3-5-haiku-20241022',
            max_tokens=200,
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