
import os
import uuid
from datetime import datetime, timezone

from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename


# =========================
# 1. CẤU HÌNH ỨNG DỤNG
# =========================

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "vibes-development-key-change-this"
)

database_url = os.environ.get("DATABASE_URL", "sqlite:///vibes.db")

# Render có thể cung cấp URL bắt đầu bằng postgres://
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

db = SQLAlchemy(app)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading"
)


# =========================
# 2. DATABASE
# =========================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender = db.Column(db.String(80), nullable=False)
    receiver = db.Column(db.String(80), nullable=False)
    content = db.Column(db.Text, nullable=True)
    file_url = db.Column(db.String(500), nullable=True)
    file_type = db.Column(db.String(50), nullable=True)
    timestamp = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc)
    )
    is_deleted = db.Column(db.Boolean, default=False)


with app.app_context():
    db.create_all()


# =========================
# 3. HÀM HỖ TRỢ
# =========================

def get_request_data():
    return request.get_json(silent=True) or request.form


def user_to_dict(user):
    return {
        "id": user.id,
        "username": user.username
    }


def message_to_dict(message):
    return {
        "id": message.id,
        "sender": message.sender,
        "receiver": message.receiver,
        "content": message.content,
        "file_url": message.file_url,
        "file_type": message.file_type,
        "timestamp": (
            message.timestamp.isoformat()
            if message.timestamp else None
        ),
        "is_deleted": message.is_deleted
    }


def verify_password(user, entered_password):
    """
    Hỗ trợ mật khẩu đã mã hóa và tài khoản cũ
    có thể đang lưu mật khẩu dạng chữ thường.
    """

    stored_password = user.password or ""

    try:
        if check_password_hash(stored_password, entered_password):
            return True

        # Chỉ dùng để chuyển tài khoản cũ sang dạng mã hóa.
        # Không áp dụng nếu dữ liệu đã là một password hash.
        if not stored_password.startswith(("pbkdf2:", "scrypt:")):
            if stored_password == entered_password:
                user.password = generate_password_hash(entered_password)
                db.session.commit()
                return True

    except (ValueError, TypeError):
        return False

    return False


# =========================
# 4. TRANG CHỦ
# =========================

@app.route("/")
def home():
    return send_from_directory(app.root_path, "index.html")


# =========================
# 5. ĐĂNG KÝ
# =========================

@app.route("/api/register", methods=["POST"])
def register():
    data = get_request_data()

    username = str(data.get("username", "")).strip()
    password = data.get("password", "")

    if not isinstance(password, str):
        return jsonify({
            "success": False,
            "message": "Mật khẩu không hợp lệ."
        }), 400

    if not username or not password:
        return jsonify({
            "success": False,
            "message": "Vui lòng nhập tên tài khoản và mật khẩu."
        }), 400

    if len(username) > 80:
        return jsonify({
            "success": False,
            "message": "Tên tài khoản quá dài."
        }), 400

    if len(password) < 6:
        return jsonify({
            "success": False,
            "message": "Mật khẩu phải có ít nhất 6 ký tự."
        }), 400

    existing_user = User.query.filter_by(username=username).first()

    if existing_user:
        return jsonify({
            "success": False,
            "message": "Tên tài khoản đã tồn tại."
        }), 409

    try:
        new_user = User(
            username=username,
            password=generate_password_hash(password)
        )

        db.session.add(new_user)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Đăng ký thành công!",
            "user": user_to_dict(new_user)
        }), 201

    except Exception:
        db.session.rollback()
        app.logger.exception("Register error")

        return jsonify({
            "success": False,
            "message": "Không thể tạo tài khoản. Vui lòng thử lại."
        }), 500


# =========================
# 6. ĐĂNG NHẬP
# =========================

@app.route("/api/login", methods=["POST"])
def login():
    data = get_request_data()

    username = str(data.get("username", "")).strip()
    password = data.get("password", "")

    if not isinstance(password, str) or not username or not password:
        return jsonify({
            "success": False,
            "message": "Vui lòng nhập đầy đủ thông tin."
        }), 400

    user = User.query.filter_by(username=username).first()

    if not user:
        return jsonify({
            "success": False,
            "message": "Tên tài khoản hoặc mật khẩu không đúng."
        }), 401

    if not verify_password(user, password):
        return jsonify({
            "success": False,
            "message": "Tên tài khoản hoặc mật khẩu không đúng."
        }), 401

    return jsonify({
        "success": True,
        "message": "Đăng nhập thành công!",
        "user": user_to_dict(user)
    }), 200


# =========================
# 7. DANH SÁCH NGƯỜI DÙNG
# =========================

@app.route("/api/users", methods=["GET"])
def get_users():
    users = User.query.order_by(User.username.asc()).all()

    return jsonify([
        user_to_dict(user)
        for user in users
    ])


# =========================
# 8. LẤY TIN NHẮN
# =========================

@app.route("/api/messages/<target>", methods=["GET"])
def get_messages(target):
    current_user = request.args.get("user", "").strip()

    if not current_user:
        return jsonify({
            "success": False,
            "message": "Thiếu tên người dùng."
        }), 400

    messages = Message.query.filter(
        db.or_(
            db.and_(
                Message.sender == current_user,
                Message.receiver == target
            ),
            db.and_(
                Message.sender == target,
                Message.receiver == current_user
            )
        )
    ).order_by(Message.timestamp.asc()).all()

    return jsonify([
        message_to_dict(message)
        for message in messages
    ])


# =========================
# 9. TẢI ẢNH / TỆP
# =========================

@app.route("/api/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({
            "success": False,
            "message": "Không tìm thấy tệp."
        }), 400

    file = request.files["file"]

    if not file.filename:
        return jsonify({
            "success": False,
            "message": "Chưa chọn tệp."
        }), 400

    safe_name = secure_filename(file.filename)

    if not safe_name:
        return jsonify({
            "success": False,
            "message": "Tên tệp không hợp lệ."
        }), 400

    extension = os.path.splitext(safe_name)[1]
    filename = f"{uuid.uuid4().hex}{extension}"

    try:
        file.save(os.path.join(UPLOAD_FOLDER, filename))

        file_url = f"/static/uploads/{filename}"

        return jsonify({
            "success": True,
            "file_url": file_url,
            "url": file_url,
            "filename": safe_name
        })

    except Exception:
        app.logger.exception("Upload error")

        return jsonify({
            "success": False,
            "message": "Không thể tải tệp lên."
        }), 500


# =========================
# 10. SOCKET.IO
# =========================

@socketio.on("connect")
def handle_connect():
    emit("connected", {"success": True})


@socketio.on("join")
def handle_join(data):
    data = data or {}
    username = str(data.get("username", "")).strip()

    if username:
        join_room(username)


@socketio.on("send_message")
def handle_send_message(data):
    data = data or {}

    sender = str(data.get("sender", "")).strip()
    receiver = str(data.get("receiver", "")).strip()
    content = data.get("content", "")

    if not sender or not receiver:
        emit("message_error", {
            "message": "Thiếu người gửi hoặc người nhận."
        })
        return

    if not isinstance(content, str):
        content = ""

    file_url = data.get("file_url")
    file_type = data.get("file_type")

    try:
        message = Message(
            sender=sender,
            receiver=receiver,
            content=content,
            file_url=file_url,
            file_type=file_type
        )

        db.session.add(message)
        db.session.commit()

        result = message_to_dict(message)

        socketio.emit("receive_message", result, room=receiver)
        socketio.emit("receive_message", result, room=sender)

    except Exception:
        db.session.rollback()
        app.logger.exception("Send message error")

        emit("message_error", {
            "message": "Không thể gửi tin nhắn."
        })


@socketio.on("unsend_message")
def handle_unsend_message(data):
    data = data or {}

    message_id = data.get("message_id")

    try:
        message = db.session.get(Message, int(message_id))

        if not message:
            return

        message.is_deleted = True
        message.content = "Tin nhắn đã được thu hồi."
        message.file_url = None
        db.session.commit()

        result = {
            "id": message.id,
            "is_deleted": True,
            "content": message.content
        }

        socketio.emit(
            "message_unsent",
            result,
            room=message.sender
        )
        socketio.emit(
            "message_unsent",
            result,
            room=message.receiver
        )

    except (ValueError, TypeError):
        return

    except Exception:
        db.session.rollback()
        app.logger.exception("Unsend message error")


# =========================
# 11. KHỞI ĐỘNG
# =========================

if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
