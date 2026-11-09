
import os
from datetime import datetime

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename


# =========================
# CAU HINH UNG DUNG
# =========================

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "vibes-secret-key-change-this"
)

database_url = os.environ.get(
    "DATABASE_URL",
    "sqlite:///vibes.db"
)

# Render/PostgreSQL compatibility
if database_url.startswith("postgres://"):
    database_url = database_url.replace(
        "postgres://",
        "postgresql://",
        1
    )

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

app.config["UPLOAD_FOLDER"] = os.path.join(
    app.root_path,
    "static",
    "uploads"
)

app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db = SQLAlchemy(app)

socketio = SocketIO(
    app,
    cors_allowed_origins="*"
)


# =========================
# DATABASE MODELS
# =========================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(
        db.String(80),
        unique=True,
        nullable=False
    )

    password = db.Column(
        db.String(255),
        nullable=False
    )


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    sender = db.Column(
        db.String(80),
        nullable=False
    )

    receiver = db.Column(
        db.String(80),
        nullable=False
    )

    content = db.Column(
        db.Text,
        nullable=False,
        default=""
    )

    file_url = db.Column(
        db.String(500),
        nullable=True
    )

    file_type = db.Column(
        db.String(20),
        nullable=True
    )

    timestamp = db.Column(
        db.String(50),
        nullable=False
    )

    is_deleted = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )


# =========================
# TAO DATABASE
# =========================

with app.app_context():
    db.create_all()


# =========================
# TRANG CHU
# =========================

@app.route("/")
def index():
    return render_template("index.html")


# =========================
# DANG KY
# =========================

@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}

    username = data.get("username", "")
    password = data.get("password", "")

    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify({
            "success": False,
            "message": "Thông tin không hợp lệ!"
        }), 400

    username = username.strip()

    # Khong trim password, vi khoang trang co the la mot phan mat khau
    if not username or not password:
        return jsonify({
            "success": False,
            "message": "Vui lòng nhập đầy đủ tài khoản và mật khẩu!"
        }), 400

    if len(username) > 80:
        return jsonify({
            "success": False,
            "message": "Tên tài khoản quá dài!"
        }), 400

    if len(password) < 6:
        return jsonify({
            "success": False,
            "message": "Mật khẩu cần ít nhất 6 ký tự!"
        }), 400

    existing_user = User.query.filter_by(
        username=username
    ).first()

    if existing_user:
        return jsonify({
            "success": False,
            "message": "Tên tài khoản này đã tồn tại!"
        }), 409

    hashed_password = generate_password_hash(password)

    new_user = User(
        username=username,
        password=hashed_password
    )

    try:
        db.session.add(new_user)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Đăng ký thành công!",
            "username": new_user.username
        })

    except Exception:
        db.session.rollback()

        return jsonify({
            "success": False,
            "message": "Không thể tạo tài khoản. Vui lòng thử lại!"
        }), 500


# =========================
# DANG NHAP
# =========================

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}

    username = data.get("username", "")
    password = data.get("password", "")

    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify({
            "success": False,
            "message": "Thông tin không hợp lệ!"
        }), 400

    username = username.strip()

    if not username or not password:
        return jsonify({
            "success": False,
            "message": "Vui lòng nhập tài khoản và mật khẩu!"
        }), 400

    user = User.query.filter_by(
        username=username
    ).first()

    if user is None:
        return jsonify({
            "success": False,
            "message": "Sai tài khoản hoặc mật khẩu!"
        }), 401

    try:
        password_is_correct = check_password_hash(
            user.password,
            password
        )
    except (ValueError, TypeError):
        password_is_correct = False

    if not password_is_correct:
        return jsonify({
            "success": False,
            "message": "Sai tài khoản hoặc mật khẩu!"
        }), 401

    return jsonify({
        "success": True,
        "message": "Đăng nhập thành công!",
        "username": user.username
    })


# =========================
# DANH SACH USER
# =========================

@app.route("/api/users", methods=["GET"])
def get_users():
    users = User.query.order_by(
        User.username.asc()
    ).all()

    return jsonify([
        user.username for user in users
    ])


# =========================
# LAY TIN NHAN
# =========================

@app.route("/api/messages/<target>", methods=["GET"])
def get_messages(target):
    current_user = request.args.get("user", "").strip()

    if not current_user:
        return jsonify({
            "success": False,
            "message": "Thiếu tên người dùng!"
        }), 400

    messages = Message.query.filter(
        (
            (Message.sender == current_user)
            & (Message.receiver == target)
        )
        |
        (
            (Message.sender == target)
            & (Message.receiver == current_user)
        )
    ).order_by(
        Message.id.asc()
    ).all()

    result = []

    for message in messages:
        result.append({
            "id": message.id,
            "sender": message.sender,
            "receiver": message.receiver,
            "content": (
                "[Tin nhắn đã bị thu hồi]"
                if message.is_deleted
                else message.content
            ),
            "file_url": (
                None
                if message.is_deleted
                else message.file_url
            ),
            "file_type": (
                None
                if message.is_deleted
                else message.file_type
            ),
            "timestamp": message.timestamp,
            "is_deleted": message.is_deleted
        })

    return jsonify(result)


# =========================
# UPLOAD FILE
# =========================

@app.route("/api/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({
            "success": False,
            "message": "Không tìm thấy file!"
        }), 400

    file = request.files["file"]

    if not file.filename:
        return jsonify({
            "success": False,
            "message": "Bạn chưa chọn file!"
        }), 400

    filename = secure_filename(file.filename)

    if not filename:
        return jsonify({
            "success": False,
            "message": "Tên file không hợp lệ!"
        }), 400

    # Them ten duy nhat de tranh ghi de file
    unique_filename = (
        datetime.now().strftime("%Y%m%d%H%M%S%f")
        + "_"
        + filename
    )

    filepath = os.path.join(
        app.config["UPLOAD_FOLDER"],
        unique_filename
    )

    try:
        file.save(filepath)

        file_type = (
            "image"
            if unique_filename.lower().endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".webp")
            )
            else "file"
        )

        return jsonify({
            "success": True,
            "url": f"/static/uploads/{unique_filename}",
            "file_type": file_type,
            "filename": filename
        })

    except Exception:
        return jsonify({
            "success": False,
            "message": "Không thể tải file lên!"
        }), 500


# =========================
# SOCKET.IO - GUI TIN NHAN
# =========================

@socketio.on("send_message")
def handle_message(data):
    if not isinstance(data, dict):
        return

    sender = data.get("sender")
    receiver = data.get("receiver")

    if not sender or not receiver:
        return

    new_message = Message(
        sender=str(sender),
        receiver=str(receiver),
        content=str(data.get("content", "")),
        file_url=data.get("file_url"),
        file_type=data.get("file_type"),
        timestamp=str(
            data.get(
                "timestamp",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        )
    )

    try:
        db.session.add(new_message)
        db.session.commit()

        message_data = {
            "id": new_message.id,
            "sender": new_message.sender,
            "receiver": new_message.receiver,
            "content": new_message.content,
            "file_url": new_message.file_url,
            "file_type": new_message.file_type,
            "timestamp": new_message.timestamp,
            "is_deleted": False
        }

        socketio.emit(
            "receive_message",
            message_data
        )

    except Exception:
        db.session.rollback()
        emit("error", {
            "message": "Không thể gửi tin nhắn!"
        })


# =========================
# SOCKET.IO - THU HOI TIN NHAN
# =========================

@socketio.on("unsend_message")
def handle_unsend(data):
    if not isinstance(data, dict):
        return

    message_id = data.get("id")

    if not message_id:
        return

    message = db.session.get(
        Message,
        message_id
    )

    if message:
        message.is_deleted = True

        try:
            db.session.commit()

            socketio.emit(
                "message_unsent",
                {"id": message_id}
            )

        except Exception:
            db.session.rollback()


# =========================
# CHAY UNG DUNG
# =========================

if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        debug=True
    )
