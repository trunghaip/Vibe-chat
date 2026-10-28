import os
os.environ["DISABLE_SQLALCHEMY_CEXT"] = "1"

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'vibes-secret-key-10th-grade'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///vibes.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender = db.Column(db.String(80), nullable=False)
    receiver = db.Column(db.String(80), nullable=False)
    content = db.Column(db.Text, nullable=False)
    file_url = db.Column(db.String(300), nullable=True)
    file_type = db.Column(db.String(20), nullable=True)
    timestamp = db.Column(db.String(50), nullable=False)
    is_deleted = db.Column(db.Boolean, default=False)

with app.app_context():
    db.create_all()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        return jsonify({'success': False, 'message': 'Vui lòng nhập đầy đủ thông tin!'})
    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'message': 'Tên tài khoản này đã tồn tại!'})
    hashed_password = generate_password_hash(password)
    new_user = User(username=username, password=hashed_password)
    db.session.add(new_user)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Đăng ký thành công!'})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password, password):
        return jsonify({'success': True, 'username': user.username})
    return jsonify({'success': False, 'message': 'Sai tài khoản hoặc mật khẩu!'})

@app.route('/api/users', methods=['GET'])
def get_users():
    users = User.query.all()
    return jsonify([u.username for u in users])

@app.route('/api/messages/<target>', methods=['GET'])
def get_messages(target):
    msgs = Message.query.filter(
        ((Message.sender == request.args.get('user')) & (Message.receiver == target)) |
        ((Message.sender == target) & (Message.receiver == request.args.get('user'))) |
        (Message.receiver == target)
    ).order_by(Message.id.asc()).all()

    result = []
    for m in msgs:
        result.append({
            'id': m.id,
            'sender': m.sender,
            'receiver': m.receiver,
            'content': '[Tin nhắn đã bị thu hồi]' if m.is_deleted else m.content,
            'file_url': None if m.is_deleted else m.file_url,
            'file_type': None if m.is_deleted else m.file_type,
            'timestamp': m.timestamp,
            'is_deleted': m.is_deleted
        })
    return jsonify(result)

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'Không tìm thấy file!'})
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'Chưa chọn file!'})
    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        file_type = 'image' if filename.lower().endswith(('png', 'jpg', 'jpeg', 'gif', 'webp')) else 'file'
        return jsonify({
            'success': True,
            'url': f'/static/uploads/{filename}',
            'file_type': file_type,
            'filename': filename
        })
    return jsonify({'success': False, 'message': 'Lỗi tải file lên!'})

@socketio.on('send_message')
def handle_message(data):
    new_msg = Message(
        sender=data['sender'],
        receiver=data['receiver'],
        content=data.get('content', ''),
        file_url=data.get('file_url'),
        file_type=data.get('file_type'),
        timestamp=data['timestamp']
    )
    db.session.add(new_msg)
    db.session.commit()
    socketio.emit('receive_message', {
        'id': new_msg.id,
        'sender': new_msg.sender,
        'receiver': new_msg.receiver,
        'content': new_msg.content,
        'file_url': new_msg.file_url,
        'file_type': new_msg.file_type,
        'timestamp': new_msg.timestamp,
        'is_deleted': False
    })

@socketio.on('unsend_message')
def handle_unsend(data):
    msg_id = data.get('id')
    msg = Message.query.get(msg_id)
    if msg:
        msg.is_deleted = True
        db.session.commit()
        socketio.emit('message_unsent', {'id': msg_id})

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)