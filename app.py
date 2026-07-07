from flask import Flask, render_template, request, jsonify
import websocket
import hashlib
import hmac
import time
import json
import ssl
import threading
import sqlite3
import uuid
import os
from urllib.parse import urlencode
from datetime import datetime, timezone
from base64 import b64encode
from functools import wraps

app = Flask(__name__)

# 数据库配置 - 使用绝对路径确保在Railway上能正确找到
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'essay_system.db')

def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化数据库表"""
    if not os.path.exists(DATABASE):
        conn = get_db()
        cursor = conn.cursor()
        
        # 作文版本表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS essay_versions (
                id TEXT PRIMARY KEY,
                user_id TEXT DEFAULT 'anonymous',
                topic TEXT NOT NULL,
                title TEXT,
                content TEXT NOT NULL,
                version_number INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                language_base_score REAL,
                content_idea_score REAL,
                structure_score REAL,
                writing_norm_score REAL,
                total_score REAL,
                corrections TEXT
            )
        ''')
        
        # 语法错误记录表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS grammar_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT DEFAULT 'anonymous',
                error_type TEXT NOT NULL,
                error_content TEXT NOT NULL,
                correct_form TEXT,
                context TEXT,
                occurrence_count INTEGER DEFAULT 1,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 用户学习进度表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_progress (
                user_id TEXT PRIMARY KEY,
                weak_points TEXT,
                practice_history TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        print("数据库初始化完成")

# 启动时初始化数据库
init_db()

# 讯飞API配置
APPID = "c5f1d808"
APISecret = "OGM3NjQyMjI3NDIzMTkxZjllYzdhZjBm"
APIKey = "6ea8ee91eeb3439ae24b25303cfd5c17"


def create_signature_url():
    """生成讯飞鉴权URL - 使用正确的HMAC-SHA256签名"""
    # 获取当前UTC时间
    now = datetime.now(timezone.utc)
    date = now.strftime('%a, %d %b %Y %H:%M:%S GMT')
    
    # 构建签名原文
    signature_origin = f"host: spark-api.xf-yun.com\ndate: {date}\nGET /v3.5/chat HTTP/1.1"
    
    # 使用APISecret进行HMAC-SHA256签名
    signature_sha = hmac.new(
        APISecret.encode('utf-8'),
        signature_origin.encode('utf-8'),
        hashlib.sha256
    ).digest()
    
    # Base64编码
    signature_sha_b64 = b64encode(signature_sha).decode('utf-8')
    
    # 构建authorization
    authorization_origin = f'api_key="{APIKey}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature_sha_b64}"'
    authorization = b64encode(authorization_origin.encode('utf-8')).decode('utf-8')
    
    # 构建URL参数
    params = {
        "authorization": authorization,
        "date": date,
        "host": "spark-api.xf-yun.com"
    }
    
    return f"wss://spark-api.xf-yun.com/v3.5/chat?{urlencode(params)}"


class XunfeiChatBot:
    def __init__(self):
        self.ws = None
        self.appid = APPID
        self.full_response = ""
        self.error = None
        self.done = threading.Event()
    
    def get_auth_url(self):
        return create_signature_url()
    
    def send_message(self, message):
        """发送消息到讯飞星火大模型"""
        self.full_response = ""
        self.error = None
        self.done.clear()
        
        auth_url = self.get_auth_url()
        
        def on_message(ws, message):
            try:
                data = json.loads(message)
                print(f"收到消息: {data}")  # 调试输出
                
                # 检查是否有错误
                if "header" in data:
                    code = data["header"].get("code", 0)
                    if code != 0:
                        self.error = f"API错误({code}): {data['header'].get('message', 'Unknown error')}"
                        self.done.set()
                        return
                
                # 解析响应内容
                if "payload" in data and "choices" in data["payload"]:
                    choices = data["payload"]["choices"]
                    if "text" in choices:
                        for item in choices["text"]:
                            if "content" in item:
                                self.full_response += item["content"]
                    
                    # 检查是否是最后一条消息
                    status = choices.get("status", 0)
                    if status == 2:  # 完成
                        self.done.set()
                        
            except Exception as e:
                print(f"解析消息出错: {e}")
        
        def on_error(ws, error):
            print(f"WebSocket错误: {error}")
            self.error = str(error)
            self.done.set()
        
        def on_close(ws, code, msg):
            print(f"连接关闭: {code}, {msg}")
            self.done.set()
        
        def on_open(ws):
            print("WebSocket连接已打开")
            payload = {
                "header": {
                    "app_id": self.appid,
                    "uid": "user_001"
                },
                "parameter": {
                    "chat": {
                        "domain": "generalv3.5",
                        "temperature": 0.5,
                        "max_tokens": 2048
                    }
                },
                "payload": {
                    "message": {
                        "text": [
                            {"role": "user", "content": message}
                        ]
                    }
                }
            }
            ws.send(json.dumps(payload))
            print(f"发送消息: {message[:50]}...")
        
        self.ws = websocket.WebSocketApp(
            auth_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open
        )
        
        # 在新线程中运行WebSocket
        thread = threading.Thread(target=self.ws.run_forever, kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}})
        thread.daemon = True
        thread.start()
        
        # 等待响应，最多等待60秒
        if not self.done.wait(timeout=60):
            self.error = "请求超时"
        
        return self.full_response, self.error


def format_prompt_for_correction(essay_content):
    """格式化批改提示词 - 四大维度评分"""
    prompt = f"""你是一位专业的中学英语教师。请对以下英语作文进行详细批改。

【评分维度与标准】
一、语言基础（35分）
- 语法准确性（17.5分）：时态、语态、主谓一致、从句、非谓语动词等
- 词汇运用（17.5分）：词汇丰富度、搭配准确性、词性使用、词义辨析

二、内容思想（35分）
- 内容完整性（12分）：要点覆盖、内容充实、切题程度
- 逻辑连贯性（12分）：段落衔接、论证逻辑、过渡自然
- 思想深度（11分）：观点独到、思考深入、见解新颖

三、结构形式（20分）
- 篇章结构（10分）：开头结尾、段落划分、层次分明
- 衔接手段（10分）：连接词使用、过渡句运用、指代清晰

四、写作规范（10分）
- 文体格式规范（10分）：书信/议论文/记叙文等格式要求、标点符号

【重要规则】
1. 必须按四大维度给出具体得分，每项给出明确的子项得分
2. 找出所有语法错误，格式：原文 → 正确写法（说明原因）
3. 最终总分不得低于60分，如果原始计算低于60分，请按60分输出并适当调整各维度分数

【输出格式】
1. 【多维评分】按四大维度列出得分详情
2. 【错误标注】列出所有错误及修改建议
3. 【总体评价】优缺点分析
4. 【改进建议】具体提升方向

作文内容：
{essay_content}
"""
    return prompt


@app.route('/')
def index():
    return render_template('index.html')


def parse_four_dimension_scores(response_text):
    """从AI响应中解析四大维度评分"""
    import re
    
    scores = {
        'language_base': {'grammar': 8, 'vocabulary': 8, 'total': 16},
        'content_idea': {'completeness': 8, 'coherence': 8, 'depth': 7, 'total': 23},
        'structure': {'organization': 8, 'transition': 8, 'total': 16},
        'writing_norm': {'format': 8, 'total': 8},
        'total': 63
    }
    
    # 尝试提取各维度得分
    patterns = {
        'language_base': [
            r'语言基础[：:]\s*(\d+(?:\.\d+)?)',
            r'语言基础.*?([0-9]+(?:\.[0-9]+)?)\s*分',
            r'语法准确性.*?([0-9]+(?:\.[0-9]+)?).*?词汇运用.*?([0-9]+(?:\.[0-9]+)?)'
        ],
        'content_idea': [
            r'内容思想[：:]\s*(\d+(?:\.\d+)?)',
            r'内容思想.*?([0-9]+(?:\.[0-9]+)?)\s*分'
        ],
        'structure': [
            r'结构形式[：:]\s*(\d+(?:\.\d+)?)',
            r'结构形式.*?([0-9]+(?:\.[0-9]+)?)\s*分'
        ],
        'writing_norm': [
            r'写作规范[：:]\s*(\d+(?:\.\d+)?)',
            r'写作规范.*?([0-9]+(?:\.[0-9]+)?)\s*分'
        ],
        'total': [
            r'总分[：:]\s*(\d+(?:\.\d+)?)',
            r'总计[：:]\s*(\d+(?:\.\d+)?)',
            r'([0-9]+(?:\.[0-9]+)?)\s*分.*?满分100'
        ]
    }
    
    for dimension, patterns_list in patterns.items():
        for pattern in patterns_list:
            match = re.search(pattern, response_text, re.IGNORECASE | re.DOTALL)
            if match:
                try:
                    if dimension == 'language_base' and len(match.groups()) >= 2:
                        grammar = float(match.group(1)) if match.group(1) else 8
                        vocab = float(match.group(2)) if match.group(2) else 8
                        scores['language_base'] = {
                            'grammar': grammar,
                            'vocabulary': vocab,
                            'total': min(35, grammar + vocab)
                        }
                    else:
                        score = float(match.group(1))
                        if dimension == 'language_base':
                            scores['language_base']['total'] = min(35, score)
                        elif dimension == 'content_idea':
                            scores['content_idea']['total'] = min(35, score)
                        elif dimension == 'structure':
                            scores['structure']['total'] = min(20, score)
                        elif dimension == 'writing_norm':
                            scores['writing_norm']['total'] = min(10, score)
                        elif dimension == 'total':
                            scores['total'] = score
                except:
                    pass
                break
    
    # 保底机制：如果总分低于60，调整为60分
    calculated_total = (scores['language_base']['total'] + 
                       scores['content_idea']['total'] + 
                       scores['structure']['total'] + 
                       scores['writing_norm']['total'])
    
    if calculated_total < 60:
        # 按比例放大到60分
        scale_factor = 60 / max(calculated_total, 1)
        scores['language_base']['total'] = min(35, round(scores['language_base']['total'] * scale_factor, 1))
        scores['content_idea']['total'] = min(35, round(scores['content_idea']['total'] * scale_factor, 1))
        scores['structure']['total'] = min(20, round(scores['structure']['total'] * scale_factor, 1))
        scores['writing_norm']['total'] = min(10, round(scores['writing_norm']['total'] * scale_factor, 1))
        scores['total'] = 60
    else:
        scores['total'] = calculated_total
    
    return scores


def extract_grammar_errors(response_text):
    """从AI响应中提取语法错误"""
    import re
    
    errors = []
    
    # 匹配格式：原文 → 正确写法（原因）或 原文 -> 正确写法
    error_pattern = r'([^→\n]{3,50})\s*[→\-]\s*([^（\n(]{3,50})\s*(?:（|\()([^）\)]+)'
    matches = re.findall(error_pattern, response_text)
    
    error_types = {
        '时态': 'tense',
        '语态': 'voice',
        '主谓一致': 'sv_agreement',
        '冠词': 'article',
        '介词': 'preposition',
        '搭配': 'collocation',
        '词汇': 'vocabulary',
        '拼写': 'spelling',
        '标点': 'punctuation',
        '句式': 'sentence_structure'
    }
    
    for match in matches[:10]:  # 最多提取10个错误
        original = match[0].strip()
        corrected = match[1].strip()
        reason = match[2].strip() if len(match) > 2 else ''
        
        # 判断错误类型
        error_type = 'grammar'
        for key, val in error_types.items():
            if key in reason or key in original:
                error_type = val
                break
        
        errors.append({
            'type': error_type,
            'original': original,
            'corrected': corrected,
            'reason': reason,
            'context': original[:50]
        })
    
    return errors


@app.route('/api/correct', methods=['POST'])
def correct_essay():
    """作文批改API - 四维评分"""
    data = request.get_json()
    essay = data.get('essay', '')
    title = data.get('title', '')
    topic = data.get('topic', title or '未分类').strip()
    user_id = data.get('user_id', 'anonymous')
    save_version_flag = data.get('save_version', True)

    # 标准化话题名称
    if topic and topic != '未分类':
        topic = topic.title()
    
    if not essay or len(essay.strip()) < 10:
        return jsonify({"error": "请输入足够的作文内容", "success": False}), 400
    
    prompt = format_prompt_for_correction(essay)
    bot = XunfeiChatBot()
    
    try:
        response, error = bot.send_message(prompt)
        
        if error:
            return jsonify({"success": False, "error": error, "response": ""}), 500
        
        # 解析四大维度评分
        scores = parse_four_dimension_scores(response)
        
        # 提取语法错误
        grammar_errors = extract_grammar_errors(response)
        
        # 保存语法错误记录
        if grammar_errors:
            save_grammar_errors(user_id, grammar_errors)
        
        # 保存版本
        version_info = None
        if save_version_flag:
            conn = get_db()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT MAX(version_number) as max_version 
                FROM essay_versions 
                WHERE user_id = ? AND topic = ?
            ''', (user_id, topic))
            
            result = cursor.fetchone()
            version_number = (result['max_version'] or 0) + 1
            
            version_id = str(uuid.uuid4())
            cursor.execute('''
                INSERT INTO essay_versions 
                (id, user_id, topic, title, content, version_number, 
                 language_base_score, content_idea_score, structure_score, 
                 writing_norm_score, total_score, corrections)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                version_id, user_id, topic, title, essay, version_number,
                scores['language_base']['total'],
                scores['content_idea']['total'],
                scores['structure']['total'],
                scores['writing_norm']['total'],
                scores['total'],
                json.dumps(grammar_errors, ensure_ascii=False)
            ))
            
            conn.commit()
            conn.close()
            
            version_info = {
                'version_id': version_id,
                'version_number': version_number
            }
        
        return jsonify({
            "success": True,
            "response": response,
            "scores": scores,
            "grammar_errors": grammar_errors,
            "version_info": version_info,
            "error": ""
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e), "response": ""}), 500


def format_chat_prompt(question):
    """格式化聊天提示词 - 带有引导回归功能"""
    
    # 检测是否为英语相关问题
    english_keywords = [
        '英语', 'english', '作文', 'essay', '写作', 'writing', '语法', 'grammar',
        '词汇', 'vocabulary', '阅读', 'reading', '口语', 'speaking', '听力', 'listening',
        '单词', 'sentence', 'paragraph', 'composition', 'letter', 'email', 'story'
    ]
    
    is_english_related = any(keyword in question.lower() for keyword in english_keywords)
    
    if is_english_related:
        # 英语相关问题正常回答
        prompt = f"""你是一位专业的中学英语教师，名叫小梦。

请用简洁、友好、易懂的语言回答用户关于英语写作的问题。
回答要点：
1. 直接回答用户问题
2. 给出具体的例子或技巧
3. 鼓励学生继续练习
4. 回答控制在200字以内

用户问题：{question}"""
    else:
        # 非英语相关问题，引导回归
        prompt = f"""你是一位专注于中学英语作文辅导的AI助手，名叫小梦。

用户的问题与英语学习无关，请礼貌地引导用户回到英语作文学习的话题上。

引导话术要求：
1. 先礼貌地回应用户的话题
2. 说明你的专业领域是英语作文辅导
3. 推荐几个英语写作相关的话题供用户选择
4. 语气要友好、鼓励，不要生硬拒绝

请使用以下格式回复：
"我理解您对[用户话题]的兴趣，但作为您的英语作文助手，我专注于帮助您提升英语写作能力。

您是否有以下方面的问题？
- 如何提高英语作文得分？
- 英语作文的结构和技巧
- 特定话题的表达方式
- 语法错误纠正

或者您可以问我：'如何提高写作水平？'"

用户问题：{question}"""
    
    return prompt


@app.route('/api/chat', methods=['POST'])
def chat():
    """数字人问答API - 带引导功能"""
    data = request.get_json()
    question = data.get('question', '')
    
    if not question:
        return jsonify({"error": "请输入问题", "success": False}), 400
    
    prompt = format_chat_prompt(question)
    bot = XunfeiChatBot()
    
    try:
        response, error = bot.send_message(prompt)
        
        if error:
            return jsonify({"success": False, "error": error, "response": ""}), 500
        
        return jsonify({
            "success": True,
            "response": response,
            "error": ""
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "response": ""}), 500
    
    bot = XunfeiChatBot()
    
    try:
        response, error = bot.send_message(prompt)
        
        if error:
            return jsonify({"success": False, "error": error, "response": ""}), 500
        
        return jsonify({
            "success": True,
            "response": response,
            "error": ""
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "response": ""}), 500


# ==================== 版本管理API ====================

@app.route('/api/versions', methods=['GET'])
def get_versions():
    """获取用户的作文版本列表"""
    topic = request.args.get('topic', '')
    user_id = request.args.get('user_id', 'anonymous')
    
    conn = get_db()
    cursor = conn.cursor()
    
    if topic:
        # 使用不区分大小写的查询
        cursor.execute('''
            SELECT * FROM essay_versions 
            WHERE user_id = ? AND LOWER(topic) = LOWER(?) 
            ORDER BY version_number DESC
        ''', (user_id, topic))
    else:
        cursor.execute('''
            SELECT * FROM essay_versions 
            WHERE user_id = ? 
            ORDER BY created_at DESC
        ''', (user_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    versions = []
    for row in rows:
        versions.append({
            'id': row['id'],
            'topic': row['topic'],
            'title': row['title'],
            'version_number': row['version_number'],
            'created_at': row['created_at'],
            'total_score': row['total_score'],
            'scores': {
                'language_base': row['language_base_score'],
                'content_idea': row['content_idea_score'],
                'structure': row['structure_score'],
                'writing_norm': row['writing_norm_score']
            }
        })
    
    return jsonify({'success': True, 'versions': versions})


@app.route('/api/versions', methods=['POST'])
def save_version():
    """保存作文版本"""
    data = request.get_json()
    user_id = data.get('user_id', 'anonymous')
    topic = data.get('topic', '').strip()
    title = data.get('title', '')
    content = data.get('content', '')
    scores = data.get('scores', {})
    corrections = data.get('corrections', [])

    # 标准化话题名称（首字母大写，其余小写）
    if topic:
        topic = topic.title()

    if not content:
        return jsonify({'success': False, 'error': '作文内容不能为空'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    # 获取该话题下的最新版本号
    cursor.execute('''
        SELECT MAX(version_number) as max_version 
        FROM essay_versions 
        WHERE user_id = ? AND topic = ?
    ''', (user_id, topic))
    
    result = cursor.fetchone()
    version_number = (result['max_version'] or 0) + 1
    
    # 插入新版本
    version_id = str(uuid.uuid4())
    cursor.execute('''
        INSERT INTO essay_versions 
        (id, user_id, topic, title, content, version_number, 
         language_base_score, content_idea_score, structure_score, 
         writing_norm_score, total_score, corrections)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        version_id, user_id, topic, title, content, version_number,
        scores.get('language_base', 0),
        scores.get('content_idea', 0),
        scores.get('structure', 0),
        scores.get('writing_norm', 0),
        scores.get('total', 0),
        json.dumps(corrections, ensure_ascii=False)
    ))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True, 
        'version_id': version_id,
        'version_number': version_number
    })


@app.route('/api/versions/compare', methods=['POST'])
def compare_versions():
    """对比两个版本"""
    data = request.get_json()
    version_id1 = data.get('version_id1')
    version_id2 = data.get('version_id2')
    
    if not version_id1 or not version_id2:
        return jsonify({'success': False, 'error': '请提供两个版本ID'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM essay_versions WHERE id = ?', (version_id1,))
    v1 = cursor.fetchone()
    
    cursor.execute('SELECT * FROM essay_versions WHERE id = ?', (version_id2,))
    v2 = cursor.fetchone()
    
    conn.close()
    
    if not v1 or not v2:
        return jsonify({'success': False, 'error': '版本不存在'}), 404
    
    return jsonify({
        'success': True,
        'version1': {
            'id': v1['id'],
            'content': v1['content'],
            'version_number': v1['version_number'],
            'created_at': v1['created_at'],
            'total_score': v1['total_score']
        },
        'version2': {
            'id': v2['id'],
            'content': v2['content'],
            'version_number': v2['version_number'],
            'created_at': v2['created_at'],
            'total_score': v2['total_score']
        }
    })


@app.route('/api/progress/chart', methods=['GET'])
def get_progress_chart():
    """获取成绩折线图数据"""
    topic = request.args.get('topic', '')
    user_id = request.args.get('user_id', 'anonymous')
    
    # 调试日志
    print(f'[DEBUG] get_progress_chart called with topic={repr(topic)}, user_id={repr(user_id)}')
    
    conn = get_db()
    cursor = conn.cursor()
    
    # 先看看总共有多少数据
    cursor.execute('SELECT COUNT(*) FROM essay_versions WHERE user_id = ?', (user_id,))
    total_count = cursor.fetchone()[0]
    print(f'[DEBUG] Total records for user {user_id}: {total_count}')
    
    if topic:
        # 先看看有哪些话题
        cursor.execute('SELECT DISTINCT topic FROM essay_versions WHERE user_id = ?', (user_id,))
        all_topics = [r[0] for r in cursor.fetchall()]
        print(f'[DEBUG] All topics in DB: {all_topics}')
        
        # 使用不区分大小写的查询
        cursor.execute('''
            SELECT version_number, created_at, 
                   language_base_score, content_idea_score, 
                   structure_score, writing_norm_score, total_score
            FROM essay_versions 
            WHERE user_id = ? AND LOWER(topic) = LOWER(?) 
            ORDER BY version_number ASC
        ''', (user_id, topic))
    else:
        cursor.execute('''
            SELECT topic, version_number, created_at, 
                   language_base_score, content_idea_score, 
                   structure_score, writing_norm_score, total_score
            FROM essay_versions 
            WHERE user_id = ? 
            ORDER BY created_at ASC
        ''', (user_id,))
    
    rows = cursor.fetchall()
    print(f'[DEBUG] Query returned {len(rows)} rows')
    
    conn.close()
    
    chart_data = []
    # 按时间排序并重新分配版本号（避免不同大小写话题的version_number冲突）
    sorted_rows = sorted(rows, key=lambda r: r['created_at'])
    for idx, row in enumerate(sorted_rows, start=1):
        chart_data.append({
            'topic': row['topic'] if 'topic' in row.keys() else topic,
            'version': idx,  # 使用重新排序后的版本号
            'date': row['created_at'],
            'language_base': row['language_base_score'],
            'content_idea': row['content_idea_score'],
            'structure': row['structure_score'],
            'writing_norm': row['writing_norm_score'],
            'total': row['total_score']
        })
    
    print(f'[DEBUG] Returning {len(chart_data)} chart data items')
    return jsonify({'success': True, 'data': chart_data})


# ==================== 语法错误追踪API ====================

@app.route('/api/grammar/errors', methods=['GET'])
def get_grammar_errors():
    """获取用户语法错误统计"""
    user_id = request.args.get('user_id', 'anonymous')
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT error_type, error_content, correct_form, 
               occurrence_count, context
        FROM grammar_errors 
        WHERE user_id = ? 
        ORDER BY occurrence_count DESC
    ''', (user_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    errors = {}
    for row in rows:
        error_type = row['error_type']
        if error_type not in errors:
            errors[error_type] = {
                'type': error_type,
                'count': 0,
                'examples': []
            }
        errors[error_type]['count'] += row['occurrence_count']
        if len(errors[error_type]['examples']) < 3:
            errors[error_type]['examples'].append({
                'error': row['error_content'],
                'correct': row['correct_form'],
                'context': row['context']
            })
    
    return jsonify({
        'success': True, 
        'errors': list(errors.values()),
        'total_errors': sum(e['count'] for e in errors.values())
    })


def save_grammar_errors(user_id, errors):
    """保存语法错误到数据库"""
    conn = get_db()
    cursor = conn.cursor()
    
    for error in errors:
        # 检查是否已存在相似错误
        cursor.execute('''
            SELECT id, occurrence_count FROM grammar_errors 
            WHERE user_id = ? AND error_type = ? AND error_content = ?
        ''', (user_id, error['type'], error['original']))
        
        existing = cursor.fetchone()
        
        if existing:
            # 更新计数
            cursor.execute('''
                UPDATE grammar_errors 
                SET occurrence_count = ?, last_seen = ?
                WHERE id = ?
            ''', (existing['occurrence_count'] + 1, datetime.now(), existing['id']))
        else:
            # 插入新错误
            cursor.execute('''
                INSERT INTO grammar_errors 
                (user_id, error_type, error_content, correct_form, context)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                user_id,
                error['type'],
                error['original'],
                error.get('corrected', ''),
                error.get('context', '')
            ))
    
    conn.commit()
    conn.close()


@app.route('/api/grammar/hints', methods=['POST'])
def get_grammar_hints():
    """获取实时语法提示"""
    data = request.get_json()
    text = data.get('text', '')
    user_id = data.get('user_id', 'anonymous')
    
    if not text:
        return jsonify({'success': True, 'hints': []})
    
    # 获取用户历史错误类型
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT error_type, error_content, occurrence_count
        FROM grammar_errors 
        WHERE user_id = ? AND occurrence_count >= 2
        ORDER BY occurrence_count DESC
    ''', (user_id,))
    
    user_errors = cursor.fetchall()
    conn.close()
    
    hints = []
    
    # 基于用户历史错误进行检测
    for err in user_errors:
        if err['error_content'].lower() in text.lower():
            hints.append({
                'type': err['error_type'],
                'message': f"注意：您之前多次出现「{err['error_content']}」的错误",
                'severity': 'high' if err['occurrence_count'] >= 5 else 'medium'
            })
    
    # 常见易错点检测
    common_patterns = [
        {'pattern': r'\bi am\b', 'type': 'capitalization', 'message': '注意：句首应大写 "I am"'},
        {'pattern': r'\bi\s+', 'type': 'capitalization', 'message': '注意："I" 应始终大写'},
        {'pattern': r'\s{2,}', 'type': 'spacing', 'message': '注意：单词间不要有多余空格'},
    ]
    
    import re
    for pattern in common_patterns:
        if re.search(pattern['pattern'], text, re.IGNORECASE):
            hints.append({
                'type': pattern['type'],
                'message': pattern['message'],
                'severity': 'low'
            })
    
    return jsonify({'success': True, 'hints': hints})


# ==================== 知识图谱API ====================

@app.route('/api/knowledge/graph', methods=['GET'])
def get_knowledge_graph():
    """获取知识图谱数据 - 中心辐射式布局"""
    graph_data = {
        'nodes': [
            # ========== Level 1: 中心节点 ==========
            {'id': 'center', 'name': '中学英语作文', 'type': 'center', 'level': 1, 'color': '#6C5CE7'},
            
            # ========== Level 2: 文体节点（4种） ==========
            {'id': 'narrative', 'name': '记叙文', 'type': 'genre', 'level': 2, 'color': '#FF6B6B', 'parent': 'center'},
            {'id': 'argumentative', 'name': '议论文', 'type': 'genre', 'level': 2, 'color': '#4ECDC4', 'parent': 'center'},
            {'id': 'expository', 'name': '说明文', 'type': 'genre', 'level': 2, 'color': '#FFD166', 'parent': 'center'},
            {'id': 'practical', 'name': '应用文', 'type': 'genre', 'level': 2, 'color': '#95E1D3', 'parent': 'center'},
            
            # ========== Level 3: 分类节点（每种文体3个分类） ==========
            # 记叙文分类（红色系）
            {'id': 'narrative_expr', 'name': '常见表达', 'type': 'category', 'level': 3, 'color': '#FF8E8E', 'parent': 'narrative', 'category': 'expression'},
            {'id': 'narrative_format', 'name': '通用格式', 'type': 'category', 'level': 3, 'color': '#FF8E8E', 'parent': 'narrative', 'category': 'format'},
            {'id': 'narrative_topics', 'name': '话题推荐', 'type': 'category', 'level': 3, 'color': '#FF8E8E', 'parent': 'narrative', 'category': 'topics'},
            
            # 议论文分类（青色系）
            {'id': 'argumentative_expr', 'name': '常见表达', 'type': 'category', 'level': 3, 'color': '#6EDDD6', 'parent': 'argumentative', 'category': 'expression'},
            {'id': 'argumentative_format', 'name': '通用格式', 'type': 'category', 'level': 3, 'color': '#6EDDD6', 'parent': 'argumentative', 'category': 'format'},
            {'id': 'argumentative_topics', 'name': '话题推荐', 'type': 'category', 'level': 3, 'color': '#6EDDD6', 'parent': 'argumentative', 'category': 'topics'},
            
            # 说明文分类（黄色系）
            {'id': 'expository_expr', 'name': '常见表达', 'type': 'category', 'level': 3, 'color': '#FFE08E', 'parent': 'expository', 'category': 'expression'},
            {'id': 'expository_format', 'name': '通用格式', 'type': 'category', 'level': 3, 'color': '#FFE08E', 'parent': 'expository', 'category': 'format'},
            {'id': 'expository_topics', 'name': '话题推荐', 'type': 'category', 'level': 3, 'color': '#FFE08E', 'parent': 'expository', 'category': 'topics'},
            
            # 应用文分类（绿色系）
            {'id': 'practical_expr', 'name': '常见表达', 'type': 'category', 'level': 3, 'color': '#B5EBE0', 'parent': 'practical', 'category': 'expression'},
            {'id': 'practical_format', 'name': '通用格式', 'type': 'category', 'level': 3, 'color': '#B5EBE0', 'parent': 'practical', 'category': 'format'},
            {'id': 'practical_topics', 'name': '话题推荐', 'type': 'category', 'level': 3, 'color': '#B5EBE0', 'parent': 'practical', 'category': 'topics'},
            
            # ========== Level 4: 内容节点（叶子节点） ==========
            # 记叙文-常见表达
            {'id': 'narr_time', 'name': '时间表达', 'type': 'content', 'level': 4, 'color': '#FFB3B3', 'parent': 'narrative_expr'},
            {'id': 'narr_emotion', 'name': '情感表达', 'type': 'content', 'level': 4, 'color': '#FFB3B3', 'parent': 'narrative_expr'},
            {'id': 'narr_desc', 'name': '描写表达', 'type': 'content', 'level': 4, 'color': '#FFB3B3', 'parent': 'narrative_expr'},
            
            # 记叙文-通用格式
            {'id': 'narr_structure', 'name': '基本结构', 'type': 'content', 'level': 4, 'color': '#FFB3B3', 'parent': 'narrative_format'},
            {'id': 'narr_tense', 'name': '常用时态', 'type': 'content', 'level': 4, 'color': '#FFB3B3', 'parent': 'narrative_format'},
            
            # 记叙文-话题推荐
            {'id': 'narr_topic_campus', 'name': '校园生活', 'type': 'content', 'level': 4, 'color': '#FFB3B3', 'parent': 'narrative_topics'},
            {'id': 'narr_topic_family', 'name': '家庭生活', 'type': 'content', 'level': 4, 'color': '#FFB3B3', 'parent': 'narrative_topics'},
            {'id': 'narr_topic_growth', 'name': '个人成长', 'type': 'content', 'level': 4, 'color': '#FFB3B3', 'parent': 'narrative_topics'},
            
            # 议论文-常见表达
            {'id': 'argu_opinion', 'name': '观点表达', 'type': 'content', 'level': 4, 'color': '#9EE8E3', 'parent': 'argumentative_expr'},
            {'id': 'argu_proof', 'name': '论证表达', 'type': 'content', 'level': 4, 'color': '#9EE8E3', 'parent': 'argumentative_expr'},
            {'id': 'argu_transition', 'name': '转折表达', 'type': 'content', 'level': 4, 'color': '#9EE8E3', 'parent': 'argumentative_expr'},
            {'id': 'argu_conclusion', 'name': '结论表达', 'type': 'content', 'level': 4, 'color': '#9EE8E3', 'parent': 'argumentative_expr'},
            
            # 议论文-通用格式
            {'id': 'argu_structure', 'name': '基本结构', 'type': 'content', 'level': 4, 'color': '#9EE8E3', 'parent': 'argumentative_format'},
            {'id': 'argu_method', 'name': '论证方法', 'type': 'content', 'level': 4, 'color': '#9EE8E3', 'parent': 'argumentative_format'},
            
            # 议论文-话题推荐
            {'id': 'argu_topic_edu', 'name': '教育学习', 'type': 'content', 'level': 4, 'color': '#9EE8E3', 'parent': 'argumentative_topics'},
            {'id': 'argu_topic_env', 'name': '环境保护', 'type': 'content', 'level': 4, 'color': '#9EE8E3', 'parent': 'argumentative_topics'},
            {'id': 'argu_topic_tech', 'name': '科技发展', 'type': 'content', 'level': 4, 'color': '#9EE8E3', 'parent': 'argumentative_topics'},
            
            # 说明文-常见表达
            {'id': 'expo_intro', 'name': '介绍表达', 'type': 'content', 'level': 4, 'color': '#FFF0B3', 'parent': 'expository_expr'},
            {'id': 'expo_order', 'name': '顺序表达', 'type': 'content', 'level': 4, 'color': '#FFF0B3', 'parent': 'expository_expr'},
            {'id': 'expo_example', 'name': '举例表达', 'type': 'content', 'level': 4, 'color': '#FFF0B3', 'parent': 'expository_expr'},
            
            # 说明文-通用格式
            {'id': 'expo_structure', 'name': '基本结构', 'type': 'content', 'level': 4, 'color': '#FFF0B3', 'parent': 'expository_format'},
            {'id': 'expo_sequence', 'name': '说明顺序', 'type': 'content', 'level': 4, 'color': '#FFF0B3', 'parent': 'expository_format'},
            
            # 说明文-话题推荐
            {'id': 'expo_topic_object', 'name': '事物介绍', 'type': 'content', 'level': 4, 'color': '#FFF0B3', 'parent': 'expository_topics'},
            {'id': 'expo_topic_activity', 'name': '活动说明', 'type': 'content', 'level': 4, 'color': '#FFF0B3', 'parent': 'expository_topics'},
            {'id': 'expo_topic_place', 'name': '地点描述', 'type': 'content', 'level': 4, 'color': '#FFF0B3', 'parent': 'expository_topics'},
            
            # 应用文-常见表达
            {'id': 'prac_letter_open', 'name': '书信开头', 'type': 'content', 'level': 4, 'color': '#D4F2EA', 'parent': 'practical_expr'},
            {'id': 'prac_letter_close', 'name': '书信结尾', 'type': 'content', 'level': 4, 'color': '#D4F2EA', 'parent': 'practical_expr'},
            {'id': 'prac_notice', 'name': '通知表达', 'type': 'content', 'level': 4, 'color': '#D4F2EA', 'parent': 'practical_expr'},
            
            # 应用文-通用格式
            {'id': 'prac_letter_fmt', 'name': '书信格式', 'type': 'content', 'level': 4, 'color': '#D4F2EA', 'parent': 'practical_format'},
            {'id': 'prac_notice_fmt', 'name': '通知格式', 'type': 'content', 'level': 4, 'color': '#D4F2EA', 'parent': 'practical_format'},
            {'id': 'prac_email_fmt', 'name': '邮件格式', 'type': 'content', 'level': 4, 'color': '#D4F2EA', 'parent': 'practical_format'},
            
            # 应用文-话题推荐
            {'id': 'prac_topic_letter', 'name': '书信', 'type': 'content', 'level': 4, 'color': '#D4F2EA', 'parent': 'practical_topics'},
            {'id': 'prac_topic_notice', 'name': '通知', 'type': 'content', 'level': 4, 'color': '#D4F2EA', 'parent': 'practical_topics'},
            {'id': 'prac_topic_email', 'name': '邮件', 'type': 'content', 'level': 4, 'color': '#D4F2EA', 'parent': 'practical_topics'},
        ],
        'links': [
            # ========== 中心到文体（实线） ==========
            {'source': 'center', 'target': 'narrative', 'type': 'solid'},
            {'source': 'center', 'target': 'argumentative', 'type': 'solid'},
            {'source': 'center', 'target': 'expository', 'type': 'solid'},
            {'source': 'center', 'target': 'practical', 'type': 'solid'},
            
            # ========== 文体到分类（虚线） ==========
            {'source': 'narrative', 'target': 'narrative_expr', 'type': 'dashed'},
            {'source': 'narrative', 'target': 'narrative_format', 'type': 'dashed'},
            {'source': 'narrative', 'target': 'narrative_topics', 'type': 'dashed'},
            
            {'source': 'argumentative', 'target': 'argumentative_expr', 'type': 'dashed'},
            {'source': 'argumentative', 'target': 'argumentative_format', 'type': 'dashed'},
            {'source': 'argumentative', 'target': 'argumentative_topics', 'type': 'dashed'},
            
            {'source': 'expository', 'target': 'expository_expr', 'type': 'dashed'},
            {'source': 'expository', 'target': 'expository_format', 'type': 'dashed'},
            {'source': 'expository', 'target': 'expository_topics', 'type': 'dashed'},
            
            {'source': 'practical', 'target': 'practical_expr', 'type': 'dashed'},
            {'source': 'practical', 'target': 'practical_format', 'type': 'dashed'},
            {'source': 'practical', 'target': 'practical_topics', 'type': 'dashed'},
            
            # ========== 分类到内容（实线） ==========
            # 记叙文
            {'source': 'narrative_expr', 'target': 'narr_time', 'type': 'solid'},
            {'source': 'narrative_expr', 'target': 'narr_emotion', 'type': 'solid'},
            {'source': 'narrative_expr', 'target': 'narr_desc', 'type': 'solid'},
            {'source': 'narrative_format', 'target': 'narr_structure', 'type': 'solid'},
            {'source': 'narrative_format', 'target': 'narr_tense', 'type': 'solid'},
            {'source': 'narrative_topics', 'target': 'narr_topic_campus', 'type': 'solid'},
            {'source': 'narrative_topics', 'target': 'narr_topic_family', 'type': 'solid'},
            {'source': 'narrative_topics', 'target': 'narr_topic_growth', 'type': 'solid'},
            
            # 议论文
            {'source': 'argumentative_expr', 'target': 'argu_opinion', 'type': 'solid'},
            {'source': 'argumentative_expr', 'target': 'argu_proof', 'type': 'solid'},
            {'source': 'argumentative_expr', 'target': 'argu_transition', 'type': 'solid'},
            {'source': 'argumentative_expr', 'target': 'argu_conclusion', 'type': 'solid'},
            {'source': 'argumentative_format', 'target': 'argu_structure', 'type': 'solid'},
            {'source': 'argumentative_format', 'target': 'argu_method', 'type': 'solid'},
            {'source': 'argumentative_topics', 'target': 'argu_topic_edu', 'type': 'solid'},
            {'source': 'argumentative_topics', 'target': 'argu_topic_env', 'type': 'solid'},
            {'source': 'argumentative_topics', 'target': 'argu_topic_tech', 'type': 'solid'},
            
            # 说明文
            {'source': 'expository_expr', 'target': 'expo_intro', 'type': 'solid'},
            {'source': 'expository_expr', 'target': 'expo_order', 'type': 'solid'},
            {'source': 'expository_expr', 'target': 'expo_example', 'type': 'solid'},
            {'source': 'expository_format', 'target': 'expo_structure', 'type': 'solid'},
            {'source': 'expository_format', 'target': 'expo_sequence', 'type': 'solid'},
            {'source': 'expository_topics', 'target': 'expo_topic_object', 'type': 'solid'},
            {'source': 'expository_topics', 'target': 'expo_topic_activity', 'type': 'solid'},
            {'source': 'expository_topics', 'target': 'expo_topic_place', 'type': 'solid'},
            
            # 应用文
            {'source': 'practical_expr', 'target': 'prac_letter_open', 'type': 'solid'},
            {'source': 'practical_expr', 'target': 'prac_letter_close', 'type': 'solid'},
            {'source': 'practical_expr', 'target': 'prac_notice', 'type': 'solid'},
            {'source': 'practical_format', 'target': 'prac_letter_fmt', 'type': 'solid'},
            {'source': 'practical_format', 'target': 'prac_notice_fmt', 'type': 'solid'},
            {'source': 'practical_format', 'target': 'prac_email_fmt', 'type': 'solid'},
            {'source': 'practical_topics', 'target': 'prac_topic_letter', 'type': 'solid'},
            {'source': 'practical_topics', 'target': 'prac_topic_notice', 'type': 'solid'},
            {'source': 'practical_topics', 'target': 'prac_topic_email', 'type': 'solid'},
        ],
        'details': {
            # ========== 中心节点详情 ==========
            'center': {
                'title': '中学英语作文知识图谱',
                'description': '本图谱涵盖中学英语作文的四大文体，帮助同学们系统掌握各类作文的写作技巧、常用表达和话题选择。',
                'tips': ['点击各节点查看详细信息', '四种文体各有特色', '多练习多积累']
            },
            
            # ========== 记叙文详情 ==========
            'narrative': {
                'title': '记叙文',
                'description': '记叙文是以记人、叙事、写景、状物为主，以写人物的经历和事物发展变化为主要内容的一种文体。',
                'features': ['以记叙为主要表达方式', '以时间、地点、人物、事件为主要内容', '以生动形象的语言描述'],
                'tips': ['交代清楚时间、地点、人物', '详略得当突出重点', '结尾要有感悟', '多用感官描写']
            },
            'narr_time': {
                'title': '时间表达',
                'examples': ['Once upon a time...（很久很久以前）', 'Last summer vacation...（去年暑假）', 'The other day...（前几天）', 'It was a cold winter morning...（那是一个寒冷的冬日早晨）', 'When I was young...（我小的时候）']
            },
            'narr_emotion': {
                'title': '情感表达',
                'examples': ['I was so excited that...（我非常兴奋以至于...）', 'To my surprise...（令我惊讶的是...）', 'I felt proud of...（我为...感到骄傲）', 'Tears welled up in my eyes...（泪水涌上我的眼眶）', 'My heart was filled with joy...（我的心里充满了喜悦）']
            },
            'narr_desc': {
                'title': '描写表达',
                'examples': ['It was a beautiful day with...（那是美好的一天，...）', 'The sun was shining brightly...（阳光明媚）', 'Everything seemed perfect...（一切看起来都很完美）', 'The air was filled with...（空气中弥漫着...）', 'As far as the eye could see...（目之所及...）']
            },
            'narr_structure': {
                'title': '记叙文基本结构',
                'points': ['开头（Beginning）：交代时间、地点、人物，引出事件', '发展（Development）：叙述事件经过，逐步推进', '高潮（Climax）：事件的转折点或最精彩部分', '结尾（Ending）：总结感悟，点明主题']
            },
            'narr_tense': {
                'title': '记叙文常用时态',
                'points': ['一般过去时为主：叙述过去发生的事情', '过去进行时：描述背景或同时进行的动作', '过去完成时：表示过去某一时间之前已经完成的动作', '一般现在时：引用名言或表达客观真理']
            },
            
            # ========== 议论文详情 ==========
            'argumentative': {
                'title': '议论文',
                'description': '议论文是对某个问题或事件进行分析、评论，表明自己的观点、立场、态度、看法和主张的一种文体。',
                'features': ['以议论为主要表达方式', '以明确的观点为核心', '以充分的论据为支撑', '以严密的逻辑为纽带'],
                'tips': ['观点明确', '论据充分', '逻辑严密', '语言正式']
            },
            'argu_opinion': {
                'title': '观点表达',
                'examples': ['In my opinion...（在我看来...）', 'From my perspective...（从我的角度来看...）', 'I firmly believe that...（我坚信...）', 'It seems to me that...（在我看来...）', 'As far as I am concerned...（就我而言...）']
            },
            'argu_proof': {
                'title': '论证表达',
                'examples': ['There is no doubt that...（毫无疑问...）', 'A good case in point is...（一个很好的例子是...）', 'According to the survey...（根据调查...）', 'This can be proved by the fact that...（这可以通过...的事实证明）', 'Statistics show that...（统计数据显示...）']
            },
            'argu_transition': {
                'title': '转折表达',
                'examples': ['However...（然而...）', 'On the other hand...（另一方面...）', 'Nevertheless...（尽管如此...）', 'Conversely...（相反地...）', 'While it is true that...（虽然...是事实）']
            },
            'argu_conclusion': {
                'title': '结论表达',
                'examples': ['In conclusion...（总之...）', 'To sum up...（总结来说...）', 'All in all...（总而言之...）', 'Taking all factors into consideration...（综合考虑所有因素...）', 'Therefore, I believe that...（因此，我相信...）']
            },
            'argu_structure': {
                'title': '议论文基本结构',
                'points': ['开头：引出话题，表明观点（Thesis Statement）', '主体段1：论据1 + 论证 + 例子', '主体段2：论据2 + 论证 + 例子', '主体段3：论据3 + 论证 + 例子（可选）', '结尾：重申观点，提出建议或展望']
            },
            'argu_method': {
                'title': '论证方法',
                'points': ['举例论证：用具体事例证明观点', '对比论证：通过比较突出观点', '因果论证：分析因果关系支持观点', '数据论证：用统计数据增强说服力', '引用论证：引用名人名言或权威观点']
            },
            
            # ========== 说明文详情 ==========
            'expository': {
                'title': '说明文',
                'description': '说明文是以说明为主要表达方式来解说事物、阐明事理而给人知识的文章体裁。',
                'features': ['以说明为主要表达方式', '以传播知识为主要目的', '以客观准确为基本要求', '以条理清晰为组织原则'],
                'tips': ['客观准确', '条理清晰', '语言简练', '多用连接词']
            },
            'expo_intro': {
                'title': '介绍表达',
                'examples': ['As we all know...（众所周知...）', 'It is widely accepted that...（人们普遍认为...）', '...is one of the most...（...是最重要的...之一）', 'When it comes to...（当谈到...）', 'Have you ever wondered...（你有没有想过...）']
            },
            'expo_order': {
                'title': '顺序表达',
                'examples': ['First of all...（首先...）', 'Secondly...（其次...）', 'Next...（接下来...）', 'Then...（然后...）', 'Finally...（最后...）', 'In the end...（最终...）']
            },
            'expo_example': {
                'title': '举例表达',
                'examples': ['For example...（例如...）', 'Such as...（比如...）', 'Take...for example...（以...为例...）', 'A good illustration is...（一个很好的例子是...）', 'To illustrate...（为了说明...）']
            },
            'expo_structure': {
                'title': '说明文基本结构',
                'points': ['开头：引出说明对象，引起读者兴趣', '主体：分点说明特征、原理、步骤或方法', '结尾：总结说明内容，或提出展望']
            },
            'expo_sequence': {
                'title': '说明顺序',
                'points': ['时间顺序：按照事物发展的时间先后说明', '空间顺序：按照事物的空间位置或方位说明', '逻辑顺序：按照事物的内在逻辑关系说明', '程序顺序：按照操作步骤或工艺流程说明']
            },
            
            # ========== 应用文详情 ==========
            'practical': {
                'title': '应用文',
                'description': '应用文是人类在长期的社会实践活动中形成的，在处理公私事务时经常使用的实用性文体。',
                'features': ['格式规范', '目的明确', '语言得体', '注重实用性'],
                'tips': ['格式规范', '目的明确', '语言得体', '注意语气']
            },
            'prac_letter_open': {
                'title': '书信开头',
                'examples': ['Dear Sir/Madam...（尊敬的先生/女士...）', 'Dear Tom...（亲爱的汤姆...）', 'I am writing to...（我写信是为了...）', 'I am glad to hear that...（我很高兴听说...）', 'Thank you for your letter...（感谢你的来信...）']
            },
            'prac_letter_close': {
                'title': '书信结尾',
                'examples': ['Looking forward to your reply.（期待你的回复）', 'Best wishes!（最美好的祝愿！）', 'Yours sincerely...（诚挚的...）', 'Please write back soon.（请尽快回信）', 'Take care!（保重！）']
            },
            'prac_notice': {
                'title': '通知表达',
                'examples': ['Attention, please!（请注意！）', 'I have an announcement to make.（我有一个通知要宣布）', 'Please be informed that...（请知悉...）', 'All students are required to...（所有学生需要...）', 'This is to notify that...（特此通知...）']
            },
            'prac_letter_fmt': {
                'title': '书信格式',
                'points': ['称呼（Salutation）：Dear XX,', '正文（Body）：开头-主体-结尾', '结束语（Closing）：Yours sincerely/truly', '署名（Signature）：你的名字', '日期（Date）：写信日期']
            },
            'prac_notice_fmt': {
                'title': '通知格式',
                'points': ['标题（Title）：NOTICE 或 具体标题', '正文（Body）：时间、地点、事件、要求', '落款（Signature）：发布单位', '日期（Date）：发布日期']
            },
            'prac_email_fmt': {
                'title': '邮件格式',
                'points': ['主题行（Subject）：简明扼要说明邮件目的', '称呼（Salutation）：Dear XX,', '正文（Body）：清晰的段落结构', '结尾敬语（Closing）：Best regards/Sincerely', '署名（Signature）：姓名+联系方式']
            },

            # ========== 三级分类节点详情 ==========
            # 记叙文分类
            'narrative_expr': {
                'title': '记叙文常见表达',
                'description': '记叙文写作中常用的时间、情感、描写类表达方式。',
                'tips': ['时间表达交代背景', '情感表达增强感染力', '描写表达使文章生动']
            },
            'narrative_format': {
                'title': '记叙文通用格式',
                'description': '记叙文的基本结构和常用时态规范。',
                'tips': ['按时间顺序或倒叙组织', '合理运用各种时态', '首尾呼应结构完整']
            },
            'narrative_topics': {
                'title': '记叙文话题推荐',
                'description': '适合写记叙文的常见话题类型。',
                'tips': ['选择亲身经历更容易写', '校园和家庭生活是常见主题', '成长故事容易引起共鸣']
            },

            # 议论文分类
            'argumentative_expr': {
                'title': '议论文常见表达',
                'description': '议论文写作中表达观点、论证、转折、结论的常用句式。',
                'tips': ['观点表达要明确', '论证表达要有力', '转折表达要自然', '结论表达要总结全文']
            },
            'argumentative_format': {
                'title': '议论文通用格式',
                'description': '议论文的基本结构和常用论证方法。',
                'tips': ['开头明确提出观点', '主体段落论证充分', '结尾总结并升华']
            },
            'argumentative_topics': {
                'title': '议论文话题推荐',
                'description': '适合写议论文的社会热点话题。',
                'tips': ['选择有争议性的话题', '关注教育、环境、科技等热点', '确保有话可说、有据可依']
            },

            # 说明文分类
            'expository_expr': {
                'title': '说明文常见表达',
                'description': '说明文写作中介绍、顺序、举例的常用表达方式。',
                'tips': ['介绍表达要简洁明了', '顺序表达要逻辑清晰', '举例表达要恰当贴切']
            },
            'expository_format': {
                'title': '说明文通用格式',
                'description': '说明文的基本结构和说明顺序。',
                'tips': ['根据说明对象选择合适的顺序', '条理清晰、层次分明', '语言准确、客观']
            },
            'expository_topics': {
                'title': '说明文话题推荐',
                'description': '适合写说明文的事物、活动、地点类话题。',
                'tips': ['选择自己熟悉的事物', '活动说明要注意步骤清晰', '地点描述要注意空间顺序']
            },

            # 应用文分类
            'practical_expr': {
                'title': '应用文常见表达',
                'description': '应用文写作中书信开头、结尾、通知的常用表达。',
                'tips': ['书信开头要礼貌得体', '书信结尾要恰当', '通知表达要简洁明确']
            },
            'practical_format': {
                'title': '应用文通用格式',
                'description': '书信、通知、邮件的基本格式规范。',
                'tips': ['格式规范是应用文的基础', '不同类型的应用文格式不同', '注意称谓和敬语的使用']
            },
            'practical_topics': {
                'title': '应用文话题推荐',
                'description': '常见的应用文类型：书信、通知、邮件。',
                'tips': ['书信是最常见的应用文类型', '通知要注意时间地点明确', '邮件要注意主题清晰']
            },

            # ========== 四级话题推荐节点详情 ==========
            # 记叙文话题
            'narr_topic_campus': {
                'title': '校园生活话题',
                'description': '记叙文校园生活类话题推荐。',
                'examples': ['My Favorite Teacher', 'A Memorable School Activity', 'My Best Friend at School', 'A Funny Thing Happened in Class', 'The School Sports Meeting']
            },
            'narr_topic_family': {
                'title': '家庭生活话题',
                'description': '记叙文家庭生活类话题推荐。',
                'examples': ['A Happy Family Dinner', 'Helping My Parents', 'A Trip with My Family', 'My Grandparents Love', 'A Special Gift from My Parents']
            },
            'narr_topic_growth': {
                'title': '个人成长话题',
                'description': '记叙文个人成长类话题推荐。',
                'examples': ['My First Success', 'Learning from Failure', 'A Challenge I Overcame', 'The Day I Grew Up', 'My Proudest Moment']
            },

            # 议论文话题
            'argu_topic_edu': {
                'title': '教育学习话题',
                'description': '议论文教育学习类话题推荐。',
                'examples': ['The Importance of Reading', 'Should Students Have Homework', 'Online Learning vs Traditional Learning', 'The Role of Extracurricular Activities', 'How to Improve Study Efficiency']
            },
            'argu_topic_env': {
                'title': '环境保护话题',
                'description': '议论文环境保护类话题推荐。',
                'examples': ['How to Protect Our Environment', 'The Importance of Recycling', 'Should We Ban Plastic Bags', 'Everyone Can Help Save the Earth', 'Climate Change and Our Responsibility']
            },
            'argu_topic_tech': {
                'title': '科技发展话题',
                'description': '议论文科技发展类话题推荐。',
                'examples': ['The Impact of Smartphones on Teenagers', 'Is AI Good for Education', 'Should Students Use Technology in Class', 'The Pros and Cons of Social Media', 'Technology Makes Life Better']
            },

            # 说明文话题
            'expo_topic_object': {
                'title': '事物介绍话题',
                'description': '说明文事物介绍类话题推荐。',
                'examples': ['My Favorite Book', 'How to Make Dumplings', 'The History of Tea', 'Introduction to Traditional Chinese Medicine', 'How Does the Internet Work']
            },
            'expo_topic_activity': {
                'title': '活动说明话题',
                'description': '说明文活动说明类话题推荐。',
                'examples': ['How to Plant a Tree', 'Steps to Learn Swimming', 'How to Prepare for an Exam', 'The Process of Making Paper', 'How to Cook a Simple Dish']
            },
            'expo_topic_place': {
                'title': '地点描述话题',
                'description': '说明文地点描述类话题推荐。',
                'examples': ['My School Campus', 'A Visit to the Museum', 'The Most Beautiful Park', 'My Hometown', 'A Famous Place in China']
            },

            # 应用文话题
            'prac_topic_letter': {
                'title': '书信类话题',
                'description': '应用文书信类话题推荐。',
                'examples': ['A Letter to My Future Self', 'Thank You Letter to Teacher', 'Invitation to a Birthday Party', 'Letter of Advice to a Friend', 'Application Letter for a Position']
            },
            'prac_topic_notice': {
                'title': '通知类话题',
                'description': '应用文通知类话题推荐。',
                'examples': ['Sports Meeting Notice', 'English Speech Contest Announcement', 'School Trip Notification', 'Library Closing Notice', 'Volunteer Activity Recruitment']
            },
            'prac_topic_email': {
                'title': '邮件类话题',
                'description': '应用文邮件类话题推荐。',
                'examples': ['Email to Request Information', 'Thank You Email After Interview', 'Email to Schedule a Meeting', 'Application Email for Scholarship', 'Email to Cancel an Appointment']
            },
        }
    }
    
    return jsonify({'success': True, 'graph': graph_data})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
