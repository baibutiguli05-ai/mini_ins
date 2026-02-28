import os
from flask import Flask, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from flask_jwt_extended import JWTManager, create_access_token, create_refresh_token, jwt_required, get_jwt_identity
import datetime

app = Flask(__name__)

# --- JWT 配置 ---
app.config["JWT_SECRET_KEY"] = "your-secret-key" 
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = datetime.timedelta(minutes=15)
app.config["JWT_REFRESH_TOKEN_EXPIRES"] = datetime.timedelta(days=7)
jwt = JWTManager(app)

# --- 数据库配置 ---
DB_CONFIG = {
    "host": "localhost",
    "database": "mini_ins", 
    "user": "postgres",
    "password": "beibit.s_05", 
    "port": "5432"
}

def get_db_connection():
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        return psycopg2.connect(db_url)
    return psycopg2.connect(**DB_CONFIG, client_encoding='utf8')

# ================= ERROR HANDLING =================

@app.errorhandler(400)
def bad_request(error):
    return jsonify({"error": "Bad Request", "message": str(error)}), 400

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Resource Not Found", "message": "接口不存在"}), 404

@app.errorhandler(500)
def server_error(error):
    return jsonify({"error": "Internal Server Error", "message": "服务器内部错误"}), 500

# ================= AUTH & USERS =================

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password') or data.get('password_hash') 
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT id FROM users WHERE username = %s AND password_hash = %s;', (username, password))
    user = cur.fetchone()
    cur.close()
    conn.close()
    
    if user:
        access = create_access_token(identity=str(user['id']))
        return jsonify(access_token=access, user_id=user['id']), 200
    return jsonify({"msg": "Invalid credentials"}), 401

@app.route('/users', methods=['POST'])
def create_user():
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute('INSERT INTO users (username, email, password_hash, bio) VALUES (%s,%s,%s,%s) RETURNING id, username;',
                    (data.get('username'), data.get('email'), data.get('password_hash'), data.get('bio', '')))
        new_user = cur.fetchone()
        conn.commit()
        return jsonify(new_user), 201
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        conn.close()

# ================= POSTS (分页) =================

@app.route('/posts', methods=['GET'])
def get_all_posts():
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 5, type=int)
    offset = (page - 1) * limit
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('''
        SELECT p.*, u.username, 
        (SELECT COUNT(*) FROM likes WHERE post_id = p.id) as likes_count
        FROM posts p 
        JOIN users u ON p.author_id = u.id 
        ORDER BY p.created_at DESC LIMIT %s OFFSET %s;
    ''', (limit, offset))
    posts = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({"page": page, "limit": limit, "data": posts})

@app.route('/posts', methods=['POST'])
@jwt_required()
def create_post():
    user_id = get_jwt_identity()
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('INSERT INTO posts (author_id, caption) VALUES (%s, %s) RETURNING *;', (user_id, data.get('caption')))
    post = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(post), 201

# ================= COMMENTS 模块 =================

@app.route('/comments', methods=['POST'])
@jwt_required()
def add_comment():
    user_id = get_jwt_identity()
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('INSERT INTO comments (post_id, author_id, text) VALUES (%s, %s, %s) RETURNING *;', 
                (data.get('post_id'), user_id, data.get('text')))
    comment = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(comment), 201

@app.route('/posts/<int:post_id>/comments', methods=['GET'])
def get_comments(post_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT c.*, u.username FROM comments c JOIN users u ON c.author_id = u.id WHERE c.post_id = %s;', (post_id,))
    comments = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(comments)

# ================= LIKES 模块 (新增) =================

@app.route('/likes', methods=['POST'])
@jwt_required()
def toggle_like():
    user_id = get_jwt_identity()
    data = request.get_json()
    post_id = data.get('post_id')
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 检查是否已点赞
    cur.execute('SELECT id FROM likes WHERE post_id = %s AND user_id = %s;', (post_id, user_id))
    like = cur.fetchone()
    
    if like:
        cur.execute('DELETE FROM likes WHERE post_id = %s AND user_id = %s;', (post_id, user_id))
        msg = "Unliked"
    else:
        cur.execute('INSERT INTO likes (post_id, user_id) VALUES (%s, %s);', (post_id, user_id))
        msg = "Liked"
        
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"msg": msg}), 200

# ================= MEDIA 模块 =================

@app.route('/media', methods=['POST'])
def add_media():
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('INSERT INTO media (post_id, media_type, url) VALUES (%s, %s, %s) RETURNING *;',
                (data.get('post_id'), data.get('media_type'), data.get('url')))
    media = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(media), 201

if __name__ == '__main__':
    app.run(debug=True, port=5000)