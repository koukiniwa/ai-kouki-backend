from anthropic import Anthropic
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
import requests
import time

# Anthropic クライアント（遅延初期化）
_client = None

def get_client():
    global _client
    if _client is None:
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        _client = Anthropic(api_key=api_key)
    return _client

# Firebase 初期化（遅延初期化）
_db = None

def get_firestore_db():
    global _db
    if _db is None:
        firebase_creds = os.environ.get('FIREBASE_CREDENTIALS')
        if not firebase_creds:
            raise ValueError("FIREBASE_CREDENTIALS is not set")
        cred_dict = json.loads(firebase_creds)
        cred = credentials.Certificate(cred_dict)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        _db = firestore.client()
    return _db

# --- 会話履歴（Firestore管理） ---

def get_conversation_history(session_id):
    """Firestoreからセッションの会話履歴を取得"""
    try:
        db = get_firestore_db()
        doc = db.collection('conversations').document(session_id).get()
        if doc.exists:
            data = doc.to_dict()
            return data.get('messages', [])
        return []
    except Exception as e:
        print(f'会話履歴取得エラー: {str(e)}')
        return []

def save_conversation_history(session_id, messages):
    """Firestoreにセッションの会話履歴を保存"""
    try:
        db = get_firestore_db()
        db.collection('conversations').document(session_id).set({
            'messages': messages,
            'updated_at': time.time()
        })
    except Exception as e:
        print(f'会話履歴保存エラー: {str(e)}')

# --- ブログ記事 ---

_blog_posts_cache = None

def get_all_blog_posts():
    """Firestoreから全ブログ記事を取得（キャッシュ付き）"""
    global _blog_posts_cache
    if _blog_posts_cache is not None:
        return _blog_posts_cache

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

        _blog_posts_cache = posts
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

        if query in title or query in content:
            score += 5

        for i in range(len(query)):
            for j in range(i + 2, len(query) + 1):
                substring = query[i:j]
                if substring in ['って', 'what', 'what', 'って何', '何？', 'とは', 'について', 'ですか', 'って何？']:
                    continue
                if len(substring) >= 3:
                    if substring in title:
                        score += 3
                    if substring in content:
                        score += 1

        if score > 0:
            scored_posts.append((score, post))

    scored_posts.sort(key=lambda x: x[0], reverse=True)
    return [post for score, post in scored_posts[:max_results]]

def get_recent_posts(max_results=2):
    """最新のブログ記事を取得"""
    posts = get_all_blog_posts()
    if not posts:
        return []

    sorted_posts = sorted(posts, key=lambda x: x.get('date', ''), reverse=True)
    return sorted_posts[:max_results]

def search_posts_by_date(query, max_results=3):
    """日付に関連する記事を検索"""
    posts = get_all_blog_posts()
    if not posts:
        return []

    import re

    matched_posts = []

    month_match = re.search(r'(\d{1,2})月', query)
    day_match = re.search(r'(\d{1,2})日', query)
    year_match = re.search(r'(202\d)年', query)
    slash_match = re.search(r'(\d{1,2})/(\d{1,2})', query)

    for post in posts:
        date_str = post.get('date', '')

        if not date_str:
            continue

        matched = False

        if year_match and month_match and day_match:
            year = year_match.group(1)
            month = month_match.group(1).zfill(2)
            day = day_match.group(1).zfill(2)
            if f"{year}.{month}.{day}" in date_str:
                matched = True
        elif month_match and day_match:
            month = month_match.group(1).zfill(2)
            day = day_match.group(1).zfill(2)
            if f".{month}.{day}" in date_str:
                matched = True
        elif slash_match:
            month = slash_match.group(1).zfill(2)
            day = slash_match.group(2).zfill(2)
            if f".{month}.{day}" in date_str:
                matched = True
        elif month_match:
            month = month_match.group(1).zfill(2)
            if f".{month}." in date_str:
                matched = True

        if matched:
            matched_posts.append(post)

    return matched_posts[:max_results]

def build_context_with_blog(query):
    """関連ブログ記事をコンテキストとして構築"""
    date_posts = search_posts_by_date(query)
    relevant_posts = search_relevant_posts(query, max_results=2)
    recent_posts = get_recent_posts(max_results=2)

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

# --- システムプロンプト ---

system_prompt = """あなたは丹羽康揮（にわこうき）というAIアバターです。

【基本情報】
- 20歳、高知大学2年生（農林海洋科学部）
- 岐阜県出身、現在高知県在住
- 身長159cm、体重45kg
- 誕生日：11月8日、血液型：AB型、星座：さそり座
- 好物：ラーメンとハンバーガー
- 嫌いな食べ物：ししゃも
- 好きな教科：地理

【家族構成】
- 5人家族
- 双子の姉がいる
- 3歳下の妹がいる
- 家族は仲が良くにぎやか
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
- YouTube：コスメティックタナカ、田村かえ、morgen

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
- 人の名前を忘れやすい
- 飽き性
- 怒られるのが苦手
- 「何とかかも」と保険をかけることがある
- 運がいいタイプ。高校受験も大学受験も絶対落ちると思ってたけどギリギリで受かった。事故も大きい怪我もない。運がいいだけにいつか痛い目みないか怖いと思ってるw

【人間関係の好み】
- 好みの女性：どんな人でもいい、自分を心から愛してくれる人
- 友達に求めるもの：機嫌が悪くても自分に八つ当たりしないこと

【話し方（重要！）】
- 基本的に短い文
- 相づちが多い
- 主語（「君は」「あなたは」）をあまり使わない
- よく使う言葉：「いやー」「あー」「まじか」「まぁねー」「たしかに」「しかたない」「めちゃくちゃ」「仕方なくない？」「でも」「人生いろいろだからねぇ」「いいんじゃね」「気まず」「申し訳ない」「よかったわー」「今んとこ」「いやーそうだろうねぇー」「好きなん?」「やっぱり」「なんとなく」「わからんなぁ」「どうしたもんかいのぉー」「それは頑張らなあかんなぁー」「難しいんよねぇー」
- 使わない表現：「なんとかなんだよねー」「なんとかなるよねー」
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
アイドル、人間関係（恋愛など）、サッカー（好きではない）

【季節・イベント】
- 好きな季節：冬
- 特にクリスマスあたりが好き。特別感があるから
- クリスマスはクリスマスマーケットに行きたい
- 正月はおばあちゃんちで過ごす

【将来の社会への想い・価値観】
- 他人を見るとみんなすごく見えるけど、突き詰めてみるとその人も運がよかったり、生まれ持って特別な能力や美しい容姿を持っていたからそんな存在になれたという人が多い
- 期待も悲観もせず、他人と比べずひたむきに好きなことを見つけ生きる
- これは成田悠輔の言葉だが、とても心に響いているし大事だと思っている
- 努力できるのも能力のひとつ。無理に努力するよりも、自分の人生に合った生き方を見つけることが大事

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


短めの返答を心がけてください。"""

# --- 読み仮名辞書（TTS用） ---

reading_corrections = {
    '丹羽康揮': 'にわこうき',
    '康揮': 'こうき',
    '丹羽': 'にわ',
    '丸源ラーメン': 'まるげんラーメン',
    '丸源': 'まるげん',
    '土佐角弘水産': 'とさかくひろすいさん',
    'メフィストフェレス': 'メフィストフェレス',
    '高知大学': 'こうちだいがく',
    '高知': 'こうち',
    '海': 'うみ',
    '海沿い': 'うみぞい',
    '岐阜県': 'ぎふけん',
    '岐阜': 'ぎふ',
    '四万十川': 'しまんとがわ',
    '申し訳ない': 'もうしわけない',
    '仕方ない': 'しかたない',
    '仕方なくない': 'しかたなくない',
    '気まず': 'きまず',
    '気分転換': 'きぶんてんかん',
    '今んとこ': 'いまんとこ',
    '双子': 'ふたご',
    '姉': 'あね',
    '妹': 'いもうと',
    '通う': 'かよう',
    'モナカ': 'モナカ',
    'トイプードル': 'トイプードル',
    '正月': 'しょうがつ',
    'クリスマス': 'クリスマス',
    'ラーメン': 'ラーメン',
    'ハンバーガー': 'ハンバーガー',
    'ししゃも': 'ししゃも',
    'しらす': 'しらす',
    'イーロン・マスク': 'イーロン マスク',
    '堺雅人': 'さかいまさと',
    '成田悠輔': 'なりたゆうすけ',
    '農林海洋科学部': 'のうりんかいようかがくぶ',
    'テニスサークル': 'テニスサークル',
    'ネットシティベータ': 'ネットシティベータ',
    'YouTube': 'ユーチューブ',
    'ヤフーニュース': 'ヤフーニュース',
    '応援': 'おうえん',
    '堅実': 'けんじつ',
    '企業': 'きぎょう',
    '実習': 'じっしゅう',
    '松屋': 'まつや',
    '笑': 'わらい',
    '庭園': 'ていえん',
    '主に': 'おもに',
    '栽培': 'さいばい',
    '植物': 'しょくぶつ',
    '土': 'つち',
    '育てる': 'そだてる',
    '歯車': 'はぐるま',
}

def correct_reading(text):
    """テキストの読み間違いを修正"""
    corrected_text = text
    for wrong, correct in reading_corrections.items():
        corrected_text = corrected_text.replace(wrong, correct)
    return corrected_text

def split_text(text, max_length=100):
    """テキストを句読点で分割（最大文字数を考慮）"""
    if len(text) <= max_length:
        return [text]

    chunks = []
    current_chunk = ""

    sentences = text.replace('。', '。\n').replace('、', '、\n').replace('！', '！\n').replace('？', '？\n').split('\n')

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if len(current_chunk) + len(sentence) <= max_length:
            current_chunk += sentence
        else:
            if current_chunk:
                chunks.append(current_chunk)

            if len(sentence) > max_length:
                for i in range(0, len(sentence), max_length):
                    chunks.append(sentence[i:i+max_length])
                current_chunk = ""
            else:
                current_chunk = sentence

    if current_chunk:
        chunks.append(current_chunk)

    return chunks
