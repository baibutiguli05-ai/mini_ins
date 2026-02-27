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

# ================= 3. ERROR HANDLING (全局错误处理) =================

@app.errorhandler(400)
def bad_request(error):
    return jsonify({"error": "Bad Request", "message": str(error)}), 400

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Resource Not Found", "message": "该资源或接口不存在"}), 404

@app.errorhandler(500)
def server_error(error):
    return jsonify({"error": "Internal Server Error", "message": "服务器内部错误"}), 500

@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    return jsonify({"error": "token_expired", "message": "Token已过期，请通过 /refresh 刷新"}), 401

@jwt.unauthorized_loader
def missing_token_callback(error):
    return jsonify({"error": "authorization_required", "message": "请求头中缺少 Authorization Token"}), 401

# ================= AUTH 认证模块 =================

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data: return jsonify({"msg": "Missing JSON in request"}), 400
    
    username = data.get('username')
    # 这里注意：你在注册时存的是 password_hash 字段，建议登录时 Body 使用 'password'
    password = data.get('password') or data.get('password_hash') 
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT id, username FROM users WHERE username = %s AND password_hash = %s;', (username, password))
    user = cur.fetchone()
    cur.close()
    conn.close()
    
    if user:
        access = create_access_token(identity=str(user['id']))
        refresh = create_refresh_token(identity=str(user['id']))
        return jsonify(access_token=access, refresh_token=refresh, user_id=user['id']), 200
    return jsonify({"msg": "Invalid credentials"}), 401

@app.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    current_user = get_jwt_identity()
    return jsonify(access_token=create_access_token(identity=current_user)), 200

# ================= USERS 表 CRUD =================

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

@app.route('/users', methods=['GET'])
def get_users():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT id, username, email, bio FROM users;')
    users = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(users)

# ================= POSTS 表 CRUD (含 2. 分页功能) =================

@app.route('/posts', methods=['GET'])
def get_all_posts():
    # --- 分页逻辑实现 ---
    page = request.args.get('page', 1, type=int)   # 默认第1页
    limit = request.args.get('limit', 5, type=int) # 默认每页5条
    offset = (page - 1) * limit

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # 使用 LIMIT 和 OFFSET 实现数据库分页
    cur.execute('''
        SELECT p.*, u.username 
        FROM posts p 
        JOIN users u ON p.author_id = u.id 
        ORDER BY p.created_at DESC 
        LIMIT %s OFFSET %s;
    ''', (limit, offset))
    
    posts = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({
        "page": page,
        "limit": limit,
        "data": posts
    })

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

@app.route('/posts/<int:post_id>', methods=['PUT'])
@jwt_required()
def update_post(post_id):
    user_id = get_jwt_identity()
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('UPDATE posts SET caption = %s WHERE id = %s AND author_id = %s RETURNING *;', (data.get('caption'), post_id, user_id))
    post = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(post) if post else (jsonify({"msg":"Not found or unauthorized"}), 404)

@app.route('/posts/<int:post_id>', methods=['DELETE'])
@jwt_required()
def delete_post(post_id):
    user_id = get_jwt_identity()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM posts WHERE id = %s AND author_id = %s;', (post_id, user_id))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"msg": "Post deleted"}), 200

# ================= COMMENTS & MEDIA (保持原有逻辑) =================

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