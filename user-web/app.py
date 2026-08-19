"""
V&B App — Flask 主应用 (v2) · 多方式登录 + UI 升级
"""
import base64, binascii, json, secrets, string, io, re, sys, os, uuid
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response, g, send_from_directory, abort
from werkzeug.security import generate_password_hash, check_password_hash

from database import DB_PATH, init_db, get_db
from food_db import seed_food_library
try:
    from recognition_adapter import RecognitionUnavailable, analyze_image
except ImportError:
    try:
        # The desktop web app and Android app share one recognition adapter.
        from health_diet_app.recognition_adapter import RecognitionUnavailable, analyze_image
    except ImportError:
        class RecognitionUnavailable(RuntimeError):
            pass

        def analyze_image(_image):
            raise RecognitionUnavailable("网页版识别服务尚未配置，请安装食物识别依赖后重试")

RESOURCE_DIR = os.environ.get("HEALTH_RESOURCE_DIR")
app = Flask(
    __name__,
    template_folder=(os.path.join(RESOURCE_DIR, "templates") if RESOURCE_DIR else "templates"),
    static_folder=(os.path.join(RESOURCE_DIR, "static") if RESOURCE_DIR else "static"),
)
def load_session_secret():
    configured = os.environ.get("HEALTH_SECRET_KEY")
    if configured:
        return configured
    db_path = os.environ.get("HEALTH_DB_PATH", DB_PATH)
    secret_path = os.path.join(os.path.dirname(db_path), ".health-session-secret")
    os.makedirs(os.path.dirname(os.path.abspath(secret_path)), exist_ok=True)
    try:
        with open(secret_path, "r", encoding="ascii") as secret_file:
            value = secret_file.read().strip()
            if len(value) >= 32:
                return value
    except OSError:
        pass
    value = secrets.token_hex(32)
    try:
        with open(secret_path, "x", encoding="ascii") as secret_file:
            secret_file.write(value)
    except FileExistsError:
        with open(secret_path, "r", encoding="ascii") as secret_file:
            value = secret_file.read().strip()
    return value


app.secret_key = load_session_secret()
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

MOTIVATIONAL_QUOTES = (
    "每一次选择，都在塑造更好的自己",
    "今天的坚持，是明天轻盈的底气",
    "照顾好身体，也是在认真生活",
    "小小的进步，也值得被看见",
    "规律一点，健康就近一点",
    "不必完美，持续前进就很好",
    "认真吃饭，好好生活",
    "把健康变成每天温柔的习惯",
)

UPLOAD_DIR = os.environ.get(
    "HEALTH_UPLOAD_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".workspace", "data", "user-web", "uploads"),
)
os.makedirs(UPLOAD_DIR, exist_ok=True)
DIET_UPLOAD_DIR = os.path.join(os.path.dirname(UPLOAD_DIR), "diet")
os.makedirs(DIET_UPLOAD_DIR, exist_ok=True)


def _avatar_extension(header):
    if header.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    return None


def save_avatar(upload):
    if upload is None or not upload.filename:
        return ""
    header = upload.stream.read(16)
    upload.stream.seek(0)
    extension = _avatar_extension(header)
    if extension is None:
        raise ValueError("头像仅支持 JPG、PNG、WebP 或 GIF 图片")
    filename = f"{uuid.uuid4().hex}.{extension}"
    upload.save(os.path.join(UPLOAD_DIR, filename))
    return url_for("uploaded_avatar", filename=filename)


def remove_managed_avatar(avatar_url):
    prefix = "/uploads/avatars/"
    if not avatar_url or not avatar_url.startswith(prefix):
        return
    filename = os.path.basename(avatar_url)
    path = os.path.join(UPLOAD_DIR, filename)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def save_diet_image(data_url):
    """Validate and persist a food image supplied as a browser data URL."""
    if not data_url:
        return ""
    match = re.fullmatch(
        r"data:image/(jpeg|jpg|png|webp);base64,([A-Za-z0-9+/=\r\n]+)",
        data_url.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError("食物图片格式无效，请使用 JPG、PNG 或 WebP 图片")
    try:
        content = base64.b64decode(match.group(2), validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("食物图片无法解码，请重新选择") from error
    if not content or len(content) > 4 * 1024 * 1024:
        raise ValueError("食物图片不能超过 4 MB")
    extension = _avatar_extension(content[:16])
    if extension not in ("jpg", "png", "webp"):
        raise ValueError("食物图片仅支持 JPG、PNG 或 WebP 格式")
    filename = f"{uuid.uuid4().hex}.{extension}"
    with open(os.path.join(DIET_UPLOAD_DIR, filename), "xb") as image_file:
        image_file.write(content)
    return f"/uploads/diet/{filename}"


def remove_managed_diet_image(image_url):
    prefix = "/uploads/diet/"
    if not image_url or not image_url.startswith(prefix):
        return
    filename = os.path.basename(image_url)
    path = os.path.join(DIET_UPLOAD_DIR, filename)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def clean_recognition_suggestions(raw):
    """Keep only the small, useful part of a recognition response."""
    if not raw:
        return []
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if isinstance(value, dict):
        value = value.get("foods", [])
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value[:8]:
        if not isinstance(item, dict):
            continue
        food_name = str(item.get("record_food_name") or item.get("food_name") or "").strip()[:80]
        display_name = str(item.get("name") or food_name).strip()[:80]
        if not food_name:
            continue
        try:
            weight = float(item.get("estimated_weight_g") or item.get("weight_grams") or 0)
        except (TypeError, ValueError):
            weight = 0
        try:
            confidence = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0
        cleaned.append({
            "food_name": food_name,
            "display_name": display_name or food_name,
            "weight_grams": round(weight, 1) if 0.5 <= weight <= 5000 else None,
            "confidence": max(0, min(1, confidence)),
        })
    return cleaned


def encode_recognition_suggestions(raw):
    suggestions = clean_recognition_suggestions(raw)
    return json.dumps(suggestions, ensure_ascii=False, separators=(",", ":")) if suggestions else ""


def diet_image_data_url(image_url):
    if not image_url or not image_url.startswith("/uploads/diet/"):
        return ""
    filename = os.path.basename(image_url)
    path = os.path.join(DIET_UPLOAD_DIR, filename)
    if not os.path.isfile(path):
        return ""
    extension = os.path.splitext(filename)[1].lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(extension)
    if not mime:
        return ""
    with open(path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


@app.errorhandler(413)
def upload_too_large(error):
    flash("上传内容不能超过 8 MB", "error")
    return redirect(request.referrer or url_for("diet"))


@app.route("/uploads/avatars/<path:filename>")
def uploaded_avatar(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/uploads/diet/<path:filename>")
def uploaded_diet_image(filename):
    current_user_id = session.get("user_id")
    if not current_user_id:
        abort(403)
    image_url = f"/uploads/diet/{os.path.basename(filename)}"
    record = db().execute(
        "SELECT user_id FROM diet_records WHERE image_url=? ORDER BY id DESC LIMIT 1",
        (image_url,),
    ).fetchone()
    if not record:
        abort(404)
    if record["user_id"] != current_user_id and not can_view_shared(current_user_id, record["user_id"], "diet"):
        abort(403)
    return send_from_directory(DIET_UPLOAD_DIR, filename)

# ── 初始化 ──────────────────────────────────────────────
with app.app_context():
    init_db()
    conn = get_db()
    seed_food_library(conn)
    conn.close()


@app.teardown_appcontext
def close_db(error):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def db():
    if "db" not in g:
        g.db = get_db()
    return g.db


@app.before_request
def protect_post_requests():
    if "user_id" in session:
        current = db().execute("SELECT id,active,last_active_at FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if not current or not current["active"]:
            session.clear()
            flash("账号已被禁用，请联系管理员。", "error")
            if request.endpoint != "login":
                return redirect(url_for("login"))
        elif not current["last_active_at"] or current["last_active_at"] < (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"):
            db().execute("UPDATE users SET last_active_at=CURRENT_TIMESTAMP WHERE id=?", (current["id"],))
            db().commit()
    if request.method != "POST":
        return None
    expected = session.get("csrf_token", "")
    supplied = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        abort(400, description="请求已失效，请刷新页面后重试")
    return None


try:
    import qrcode
    from qrcode.image.pure import PyPNGImage
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False


# ── 工具函数 ────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("请先登录")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def get_user():
    if "user_id" not in session:
        return None
    return db().execute("SELECT * FROM users WHERE id=? AND active=1", (session["user_id"],)).fetchone()


def start_user_session(user):
    if not user["active"]:
        flash("账号已被禁用，请联系管理员。", "error")
        return False
    session["user_id"] = user["id"]
    session["role"] = user["role"]
    db().execute("UPDATE users SET last_active_at=CURRENT_TIMESTAMP WHERE id=?", (user["id"],))
    db().commit()
    return True


@app.context_processor
def inject_user():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {"current_user": get_user(), "csrf_token": session["csrf_token"]}


def generate_bind_code():
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def validate_password(pw):
    if len(pw) < 8: return False, "密码至少 8 位"
    if not any(c.isupper() for c in pw): return False, "密码需包含大写字母"
    if not any(c.islower() for c in pw): return False, "密码需包含小写字母"
    if not any(c.isdigit() for c in pw): return False, "密码需包含数字"
    return True, ""


def calc_bmr(gender, weight, height, age):
    if gender == "male": return 10 * weight + 6.25 * height - 5 * age + 5
    else: return 10 * weight + 6.25 * height - 5 * age - 161


def calc_nutrition(gender, weight, tdee, health_goal):
    """基于中国 DRIs 2023 + WHO/FAO + DASH 标准计算每日营养目标"""
    is_male = (gender == "male")

    # ── 蛋白质 (g) ──
    if health_goal == "weight_management":
        protein_g = round(weight * 1.2, 1)
    elif health_goal == "blood_sugar":
        protein_g = round(weight * 0.9, 1)
    else:
        protein_g = round(weight * 1.0, 1)
    protein_cal = round(protein_g * 4)

    # ── 脂肪 (g) ──
    if health_goal == "weight_management":
        fat_pct = 0.25
    elif health_goal == "blood_sugar":
        fat_pct = 0.30
    else:
        fat_pct = 0.25
    fat_cal = round(tdee * fat_pct)
    fat_g = round(fat_cal / 9, 1)

    # ── 碳水 (g) ──
    carbs_cal = tdee - protein_cal - fat_cal
    carbs_g = round(carbs_cal / 4, 1)
    if health_goal == "blood_sugar":
        max_carbs_cal = round(tdee * 0.50)
        max_carbs_g = round(max_carbs_cal / 4, 1)
        carbs_g = min(carbs_g, max_carbs_g)
    carbs_g = max(carbs_g, 50)

    # ── 膳食纤维 (g) ──
    if health_goal == "blood_sugar":
        fiber_g = 35 if is_male else 30
    else:
        fiber_g = 30 if is_male else 25

    # ── 水 (ml) ──
    water_ml = round(weight * 35) if health_goal in ("blood_sugar", "blood_pressure") else round(weight * 30)
    water_ml = min(water_ml, 3000)

    # ── 微量元素目标（所有人群） ──
    micro_targets = {
        "sodium_mg": 2000,          # WHO ≤2000mg（钠上限）
        "potassium_mg": 2000,       # 中国 AI（充足摄入量）
        "calcium_mg": 800,          # 中国 RNI（推荐摄入量）
        "magnesium_mg": 330,        # 中国 RNI
        "iron_mg": 12 if is_male else 20,  # 中国 RNI：男12，女20
    }

    # ── 专项：血压管理 (DASH) ──
    dash = None
    if health_goal == "blood_pressure":
        dash = {
            "sodium_mg": 2000,
            "potassium_mg": 4700,
            "calcium_mg": 1000,
            "magnesium_mg": 420 if is_male else 320,
        }
        # DASH 覆盖通用目标
        micro_targets.update(dash)

    # ── 专项：血糖管理 ──
    if health_goal == "blood_sugar":
        # 血糖人群补镁更关键
        micro_targets["magnesium_mg"] = 350

    # ── 专项：体重管理 ──
    if health_goal == "weight_management":
        # 减脂期钙需求偏高（防骨质流失）
        micro_targets["calcium_mg"] = 1000

    return {
        "protein_g": protein_g, "protein_cal": protein_cal,
        "fat_g": fat_g, "fat_cal": fat_cal,
        "carbs_g": carbs_g, "carbs_cal": carbs_cal,
        "fiber_g": fiber_g,
        "water_ml": water_ml,
        "dash": dash,
        "micro_targets": micro_targets,
        "sugar_extra": {"fiber_boost": "+5g（较普通人群）", "gi_note": "优先低 GI：全谷物、豆类、非淀粉蔬菜"}
        if health_goal == "blood_sugar" else None,
    }


def get_connection_rows(user_id, status="active"):
    where_status = " AND uc.status=?" if status else ""
    params = [user_id] * 11
    if status:
        params.append(status)
    return db().execute(
        "SELECT uc.*, other.id AS other_id, other.nickname AS other_nickname, "
        "other.avatar_url AS other_avatar_url, other.phone AS other_phone, "
        "other.health_goal AS other_health_goal, "
        "CASE WHEN uc.user_a_id=? THEN uc.a_remark_for_b ELSE uc.b_remark_for_a END AS my_remark, "
        "CASE WHEN uc.user_a_id=? THEN uc.b_remark_for_a ELSE uc.a_remark_for_b END AS their_remark, "
        "CASE WHEN uc.user_a_id=? THEN uc.a_share_diet ELSE uc.b_share_diet END AS my_share_diet, "
        "CASE WHEN uc.user_a_id=? THEN uc.b_share_diet ELSE uc.a_share_diet END AS other_share_diet, "
        "CASE WHEN uc.user_a_id=? THEN uc.a_share_goal ELSE uc.b_share_goal END AS my_share_goal, "
        "CASE WHEN uc.user_a_id=? THEN uc.b_share_goal ELSE uc.a_share_goal END AS other_share_goal, "
        "CASE WHEN uc.user_a_id=? THEN uc.a_share_profile ELSE uc.b_share_profile END AS my_share_profile, "
        "CASE WHEN uc.user_a_id=? THEN uc.b_share_profile ELSE uc.a_share_profile END AS other_share_profile "
        "FROM user_connections uc JOIN users other ON other.id="
        "CASE WHEN uc.user_a_id=? THEN uc.user_b_id ELSE uc.user_a_id END "
        "WHERE (uc.user_a_id=? OR uc.user_b_id=?)" + where_status + " ORDER BY uc.updated_at DESC, uc.id DESC",
        params,
    ).fetchall()


def get_connection(user_id, other_id=None, connection_id=None, status=None):
    clauses = ["(user_a_id=? OR user_b_id=?)"]
    params = [user_id, user_id]
    if other_id is not None:
        clauses.append("(user_a_id=? OR user_b_id=?)")
        params.extend([other_id, other_id])
    if connection_id is not None:
        clauses.append("id=?")
        params.append(connection_id)
    if status:
        clauses.append("status=?")
        params.append(status)
    return db().execute(
        "SELECT * FROM user_connections WHERE " + " AND ".join(clauses), params
    ).fetchone()


def can_view_shared(viewer_id, owner_id, permission):
    if viewer_id == owner_id:
        return True
    connection = get_connection(viewer_id, other_id=owner_id, status="active")
    if not connection:
        return False
    owner_prefix = "a" if connection["user_a_id"] == owner_id else "b"
    return bool(connection[f"{owner_prefix}_share_{permission}"])


def sharing_flags():
    return tuple(1 if request.form.get(name) == "1" else 0
                 for name in ("share_diet", "share_goal", "share_profile"))


def is_valid_email(s):
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s) is not None


def is_valid_phone(s):
    """中国大陆手机号：11 位，1 开头，第二位为 3-9。"""
    return re.fullmatch(r"1[3-9]\d{9}", s or "") is not None


def generate_verify_code():
    return "".join(secrets.choice(string.digits) for _ in range(6))


def can_send_verify_code(conn, phone="", email=""):
    column, value = ("phone", phone) if phone else ("email", email)
    conn.execute("DELETE FROM verify_codes WHERE created_at < datetime('now', '-1 day')")
    recent = conn.execute(
        f"SELECT COUNT(*) AS c FROM verify_codes WHERE {column}=? AND created_at >= datetime('now', '-10 minutes')",
        (value,),
    ).fetchone()["c"]
    latest = conn.execute(
        f"SELECT 1 FROM verify_codes WHERE {column}=? AND created_at >= datetime('now', '-60 seconds') LIMIT 1",
        (value,),
    ).fetchone()
    return not latest and recent < 5


def parse_number(raw, label, minimum, maximum, integer=False, required=False):
    value = (raw or "").strip()
    if not value:
        if required:
            raise ValueError(f"请填写{label}")
        return None
    try:
        parsed = int(value) if integer else float(value)
    except ValueError as error:
        raise ValueError(f"{label}格式不正确") from error
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{label}应在 {minimum}–{maximum} 之间")
    return parsed


# ── 首页 ────────────────────────────────────────────────
@app.route("/")
def index():
    return redirect(url_for("goal") if "user_id" in session else url_for("login"))


# ── 登录 ────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        mode = request.form.get("mode", "password")
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        code = request.form.get("code", "").strip()

        # 密码登录
        if mode == "password":
            account = phone or email
            if not account:
                flash("请输入手机号或邮箱"); return redirect(url_for("login"))
            if account.isdigit() and not is_valid_phone(account):
                flash("请输入正确的中国大陆手机号"); return redirect(url_for("login"))
            c = db()
            user = c.execute("SELECT * FROM users WHERE phone=? OR email=?", (account, account)).fetchone()
            if not user:
                flash("账号未注册"); return redirect(url_for("login"))
            if not check_password_hash(user["password_hash"], password):
                flash("密码错误"); return redirect(url_for("login"))
            if not start_user_session(user):
                return redirect(url_for("login"))
            return redirect(url_for("goal"))

        # 短信验证码登录
        if mode == "sms":
            if not is_valid_phone(phone):
                flash("请输入正确的手机号"); return redirect(url_for("login"))
            if not re.fullmatch(r"\d{6}", code):
                flash("请输入验证码"); return redirect(url_for("login"))
            c = db()
            row = c.execute(
                "SELECT id FROM verify_codes WHERE phone=? AND code=? AND used=0 "
                "AND created_at >= datetime('now', '-5 minutes') ORDER BY created_at DESC LIMIT 1",
                (phone, code)).fetchone()
            if not row:
                flash("验证码错误或已过期"); return redirect(url_for("login"))
            c.execute("UPDATE verify_codes SET used=1 WHERE id=?", (row["id"],)); c.commit()
            user = c.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
            if not user:
                flash("手机号未注册"); return redirect(url_for("login"))
            if not start_user_session(user):
                return redirect(url_for("login"))
            return redirect(url_for("goal"))

        # 邮箱验证码登录
        if mode == "email":
            if not email or not is_valid_email(email):
                flash("请输入正确的邮箱"); return redirect(url_for("login"))
            if not re.fullmatch(r"\d{6}", code):
                flash("请输入验证码"); return redirect(url_for("login"))
            c = db()
            row = c.execute(
                "SELECT id FROM verify_codes WHERE email=? AND code=? AND used=0 "
                "AND created_at >= datetime('now', '-5 minutes') ORDER BY created_at DESC LIMIT 1",
                (email, code)).fetchone()
            if not row:
                flash("验证码错误或已过期"); return redirect(url_for("login"))
            c.execute("UPDATE verify_codes SET used=1 WHERE id=?", (row["id"],)); c.commit()
            user = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if not user:
                flash("邮箱未注册"); return redirect(url_for("login"))
            if not start_user_session(user):
                return redirect(url_for("login"))
            return redirect(url_for("goal"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear(); flash("已退出登录"); return redirect(url_for("login"))


# ── 发送验证码 ──────────────────────────────────────────
@app.route("/send_code", methods=["POST"])
def send_code():
    phone = request.form.get("phone", "").strip()
    email = request.form.get("email", "").strip()
    c = db()
    verify_code = generate_verify_code()

    if phone:
        if not is_valid_phone(phone):
            return jsonify({"ok": False, "msg": "手机号格式错误"}), 400
        if c.execute("SELECT id FROM users WHERE phone=?", (phone,)).fetchone():
            return jsonify({"ok": False, "msg": "该手机号已注册"}), 400
        if not can_send_verify_code(c, phone=phone):
            return jsonify({"ok": False, "msg": "发送过于频繁，请稍后再试"}), 429
        c.execute("INSERT INTO verify_codes (phone, code) VALUES (?,?)", (phone, verify_code))
        c.commit()
        session["mock_sms_phone"] = phone; session["mock_sms_code"] = verify_code
        return jsonify({"ok": True, "code": verify_code, "phone": phone})

    if email:
        if not is_valid_email(email):
            return jsonify({"ok": False, "msg": "邮箱格式错误"}), 400
        if c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            return jsonify({"ok": False, "msg": "该邮箱已注册"}), 400
        if not can_send_verify_code(c, email=email):
            return jsonify({"ok": False, "msg": "发送过于频繁，请稍后再试"}), 429
        c.execute("INSERT INTO verify_codes (email, code) VALUES (?,?)", (email, verify_code))
        c.commit()
        session["mock_email"] = email; session["mock_email_code"] = verify_code
        return jsonify({"ok": True, "code": verify_code, "email": email})

    return jsonify({"ok": False, "msg": "缺少手机号或邮箱"}), 400


# ── 登录用验证码（已注册用户） ─────────────────────────
@app.route("/send_login_code", methods=["POST"])
def send_login_code():
    phone = request.form.get("phone", "").strip()
    email = request.form.get("email", "").strip()
    verify_code = generate_verify_code()
    c = db()

    if phone:
        if not is_valid_phone(phone):
            return jsonify({"ok": False, "msg": "手机号格式错误"}), 400
        if not c.execute("SELECT id FROM users WHERE phone=?", (phone,)).fetchone():
            return jsonify({"ok": False, "msg": "手机号未注册"}), 400
        if not can_send_verify_code(c, phone=phone):
            return jsonify({"ok": False, "msg": "发送过于频繁，请稍后再试"}), 429
        c.execute("INSERT INTO verify_codes (phone, code) VALUES (?,?)", (phone, verify_code))
        c.commit()
        return jsonify({"ok": True, "code": verify_code, "phone": phone})

    if email:
        if not is_valid_email(email):
            return jsonify({"ok": False, "msg": "邮箱格式错误"}), 400
        if not c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            return jsonify({"ok": False, "msg": "邮箱未注册"}), 400
        if not can_send_verify_code(c, email=email):
            return jsonify({"ok": False, "msg": "发送过于频繁，请稍后再试"}), 429
        c.execute("INSERT INTO verify_codes (email, code) VALUES (?,?)", (email, verify_code))
        c.commit()
        return jsonify({"ok": True, "code": verify_code, "email": email})

    return jsonify({"ok": False}), 400


# ── 注册 ────────────────────────────────────────────────
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        code = request.form.get("code", "").strip()
        password = request.form.get("password", "")
        nickname = request.form.get("nickname", "").strip()
        avatar_file = request.files.get("avatar")
        height = request.form.get("height", "").strip()
        weight = request.form.get("weight", "").strip()
        age = request.form.get("age", "").strip()
        gender = request.form.get("gender", "").strip()
        health_goal = request.form.get("health_goal", "weight_management").strip()
        step = request.form.get("step", "1")

        c = db()

        if step == "1" and not code:
            if not is_valid_phone(phone):
                flash("请输入正确的中国大陆手机号"); return redirect(url_for("register"))
            if c.execute("SELECT id FROM users WHERE phone=?", (phone,)).fetchone():
                flash("该手机号已注册"); return redirect(url_for("register"))
            if not can_send_verify_code(c, phone=phone):
                flash("验证码发送过于频繁，请稍后再试"); return redirect(url_for("register"))
            verify_code = generate_verify_code()
            c.execute("INSERT INTO verify_codes (phone, code) VALUES (?,?)", (phone, verify_code))
            c.commit()
            session["mock_sms_phone"] = phone; session["mock_sms_code"] = verify_code
            flash(f"验证码已发送至 {phone}（模拟：{verify_code}）", "sms")
            return render_template("register.html", step="1", phone=phone)

        if step == "1" and code:
            if not is_valid_phone(phone) or not re.fullmatch(r"\d{6}", code):
                flash("手机号或验证码格式不正确"); return redirect(url_for("register"))
            row = c.execute(
                "SELECT id FROM verify_codes WHERE phone=? AND code=? AND used=0 "
                "AND created_at >= datetime('now', '-5 minutes') ORDER BY created_at DESC LIMIT 1",
                (phone, code)).fetchone()
            if not row:
                flash("验证码错误或已过期"); return redirect(url_for("register"))
            c.execute("UPDATE verify_codes SET used=1 WHERE id=?", (row["id"],)); c.commit()
            session["registration_phone"] = phone
            session["registration_verified_at"] = int(datetime.now().timestamp())
            return render_template("register.html", step="2", phone=phone, verified=True)

        if step == "2":
            verified_phone = session.get("registration_phone", "")
            verified_at = session.get("registration_verified_at", 0)
            if (phone != verified_phone or not is_valid_phone(phone)
                    or int(datetime.now().timestamp()) - verified_at > 600):
                session.pop("registration_phone", None)
                session.pop("registration_verified_at", None)
                flash("手机号验证已失效，请重新验证", "error")
                return redirect(url_for("register"))
            ok, msg = validate_password(password)
            if not ok: flash(msg); return render_template("register.html", step="2", phone=phone, verified=True)
            if not nickname: flash("请输入昵称"); return render_template("register.html", step="2", phone=phone, verified=True)
            if email and not is_valid_email(email): flash("邮箱格式不正确"); return render_template("register.html", step="2", phone=phone, verified=True)
            if email and c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
                flash("该邮箱已注册"); return render_template("register.html", step="2", phone=phone, verified=True)
            if c.execute("SELECT id FROM users WHERE phone=?", (phone,)).fetchone():
                flash("该手机号已注册，请直接登录"); return redirect(url_for("login"))

            password_hash = generate_password_hash(password)

            sup_code = generate_bind_code()
            while c.execute("SELECT id FROM users WHERE supervisor_code=?", (sup_code,)).fetchone():
                sup_code = generate_bind_code()
            sub_code = generate_bind_code()
            while c.execute("SELECT id FROM users WHERE supervisee_code=?", (sub_code,)).fetchone():
                sub_code = generate_bind_code()
            share_code = generate_bind_code()
            while c.execute(
                    "SELECT id FROM users WHERE share_code=? OR supervisor_code=? OR supervisee_code=?",
                    (share_code, share_code, share_code)).fetchone():
                share_code = generate_bind_code()

            try:
                h = parse_number(height, "身高", 80, 250, required=True)
                w = parse_number(weight, "体重", 20, 400, required=True)
                a = parse_number(age, "年龄", 6, 120, integer=True, required=True)
            except ValueError as error:
                flash(str(error), "error")
                return render_template("register.html", step="2", phone=phone, verified=True)
            if gender not in ("male", "female"):
                flash("请选择性别", "error")
                return render_template("register.html", step="2", phone=phone, verified=True)
            g = gender
            if health_goal not in ("weight_management", "blood_sugar", "blood_pressure"):
                flash("请选择有效的健康目标", "error")
                return render_template("register.html", step="2", phone=phone, verified=True)

            try:
                avatar = save_avatar(avatar_file)
            except ValueError as error:
                flash(str(error), "error")
                return render_template("register.html", step="2", phone=phone, verified=True)

            c.execute(
                "INSERT INTO users (phone, email, password_hash, role, nickname, avatar_url, "
                "supervisor_code, supervisee_code, share_code, bound_to, height, weight, age, gender, health_goal) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (phone, email or None, password_hash, "supervisee", nickname, avatar,
                 sup_code, sub_code, share_code, None, h, w, a, g, health_goal))
            c.commit()
            session.pop("registration_phone", None)
            session.pop("registration_verified_at", None)
            flash("注册成功，请登录"); return redirect(url_for("login"))

    return render_template("register.html", step="1")


# ── QR ──────────────────────────────────────────────────
@app.route("/qrcode/<code>")
def qrcode_image(code):
    if not QR_AVAILABLE: return "QR library not installed", 500
    buf = io.BytesIO(); img = qrcode.make(code, border=2, image_factory=PyPNGImage); img.save(buf); buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png")


# ── 目标看板 ────────────────────────────────────────────
@app.route("/goal")
@login_required
def goal():
    user = get_user()
    if not all([user["height"], user["weight"], user["age"], user["gender"]]):
        return render_template("goal_setup.html", user=user)
    bmr = calc_bmr(user["gender"], user["weight"], user["height"], user["age"]); tdee = round(bmr * 1.2)
    nutrition = calc_nutrition(user["gender"], user["weight"], tdee, user["health_goal"])
    today = datetime.now().strftime("%Y-%m-%d")
    c = db()
    row = c.execute("SELECT SUM(calories) as total FROM diet_records WHERE user_id=? AND date(intake_time)=?",
                       (user["id"], today)).fetchone()
    today_cal = row["total"] or 0

    # ── 今日微量元素实际摄入 ──
    micro_row = c.execute("""
        SELECT
            COALESCE(SUM(dr.weight_grams * fl.sodium_mg / 100.0), 0) as sodium,
            COALESCE(SUM(dr.weight_grams * fl.potassium_mg / 100.0), 0) as potassium,
            COALESCE(SUM(dr.weight_grams * fl.calcium_mg / 100.0), 0) as calcium,
            COALESCE(SUM(dr.weight_grams * fl.magnesium_mg / 100.0), 0) as magnesium,
            COALESCE(SUM(dr.weight_grams * fl.iron_mg / 100.0), 0) as iron
        FROM diet_records dr
        JOIN food_library fl ON dr.food_name = fl.name
        WHERE dr.user_id=? AND date(dr.intake_time)=?
    """, (user["id"], today)).fetchone()
    micro_intake = {
        "sodium_mg": round(micro_row["sodium"], 1),
        "potassium_mg": round(micro_row["potassium"], 1),
        "calcium_mg": round(micro_row["calcium"], 1),
        "magnesium_mg": round(micro_row["magnesium"], 1),
        "iron_mg": round(micro_row["iron"], 1),
    }

    return render_template("goal.html", user=user, bmr=round(bmr), tdee=tdee,
                           today_cal=today_cal, now=datetime.now(), nutrition=nutrition,
                           micro_intake=micro_intake,
                           motivational_quote=secrets.choice(MOTIVATIONAL_QUOTES))


@app.route("/goal/setup", methods=["POST"])
@login_required
def goal_setup():
    user = get_user()
    h, w, a, g = request.form.get("height"), request.form.get("weight"), request.form.get("age"), request.form.get("gender")
    hg = request.form.get("health_goal", "weight_management").strip()
    if not all([h, w, a, g]): flash("请填写所有身体指标"); return redirect(url_for("goal"))
    if g not in ("male", "female") or hg not in ("weight_management", "blood_sugar", "blood_pressure"):
        flash("身体指标选项无效", "error"); return redirect(url_for("goal"))
    try:
        height_value = parse_number(h, "身高", 80, 250, required=True)
        weight_value = parse_number(w, "体重", 20, 400, required=True)
        age_value = parse_number(a, "年龄", 6, 120, integer=True, required=True)
    except ValueError as error:
        flash(str(error), "error"); return redirect(url_for("goal"))
    c = db(); c.execute("UPDATE users SET height=?,weight=?,age=?,gender=?,health_goal=? WHERE id=?",
                        (height_value, weight_value, age_value, g, hg, user["id"])); c.commit()
    flash("身体指标设置成功"); return redirect(url_for("goal"))


# ── 饮食 ────────────────────────────────────────────────
@app.route("/diet")
@login_required
def diet():
    user = get_user(); c = db()
    foods = c.execute("SELECT * FROM food_library ORDER BY category, name").fetchall()
    connections = get_connection_rows(user["id"])
    selected_user_id = request.args.get("user_id", type=int) or user["id"]
    if selected_user_id != user["id"] and not can_view_shared(user["id"], selected_user_id, "diet"):
        abort(403, description="对方未授权你查看饮食记录")
    viewed_user = c.execute("SELECT * FROM users WHERE id=?", (selected_user_id,)).fetchone()
    if not viewed_user:
        abort(404)
    records = c.execute(
        "SELECT dr.*, u.nickname FROM diet_records dr JOIN users u ON dr.user_id=u.id "
        "WHERE dr.user_id=? ORDER BY dr.intake_time DESC LIMIT 200", (selected_user_id,)
    ).fetchall()
    today_text = datetime.now().strftime("%Y-%m-%d")
    today_records = [record for record in records if record["intake_time"] and record["intake_time"][:10] == today_text]
    history_records = [record for record in records if not record["intake_time"] or record["intake_time"][:10] != today_text]
    active_tab = request.args.get("tab", "today")
    if active_tab not in ("today", "history"):
        active_tab = "today"
    correction_record = None
    correction_suggestions = []
    correction_id = request.args.get("correct", type=int)
    if correction_id and selected_user_id == user["id"]:
        correction_record = c.execute(
            "SELECT * FROM diet_records WHERE id=? AND user_id=?",
            (correction_id, user["id"]),
        ).fetchone()
        if correction_record:
            correction_suggestions = clean_recognition_suggestions(correction_record["recognition_suggestions"])
    return render_template("diet.html", user=user, viewed_user=viewed_user, foods=foods,
                           records=records, today_records=today_records, history_records=history_records,
                           connections=connections, now=datetime.now(), active_tab=active_tab,
                           correction_record=correction_record,
                           correction_suggestions=correction_suggestions)


@app.route("/recognition")
@login_required
def recognition():
    foods = db().execute("SELECT * FROM food_library ORDER BY category, name").fetchall()
    return render_template("recognition.html", user=get_user(), foods=foods)


@app.route("/diet/record", methods=["POST"])
@login_required
def diet_record():
    user = get_user(); fn = request.form.get("food_name", "").strip(); w = request.form.get("weight_grams", "").strip()
    it = request.form.get("intake_time", "").strip()
    if not fn or not w: flash("请选择食物并输入克重"); return redirect(url_for("diet"))
    try:
        weight_value = parse_number(w, "克重", 0.5, 5000, required=True)
    except ValueError as error:
        flash(str(error), "error"); return redirect(url_for("diet"))
    if it:
        try:
            intake = datetime.strptime(it, "%Y-%m-%dT%H:%M")
        except ValueError:
            flash("摄入时间格式不正确", "error"); return redirect(url_for("diet"))
        if intake > datetime.now():
            flash("摄入时间不能晚于当前时间", "error"); return redirect(url_for("diet"))
        it = intake.strftime("%Y-%m-%d %H:%M")
    c = db(); food = c.execute("SELECT * FROM food_library WHERE name=?", (fn,)).fetchone()
    if not food: flash("食物不在库中"); return redirect(url_for("diet"))
    cal = round(food["calories_per_100g"] * weight_value / 100, 1)
    factor = weight_value / 100.0
    protein = round(food["protein_g"] * factor, 1)
    fat = round(food["fat_g"] * factor, 1)
    carbs = round(food["carbs_g"] * factor, 1)
    fiber = round(food["fiber_g"] * factor, 1)
    meal_type = request.form.get("meal_type", "").strip()
    if meal_type not in ("", "breakfast", "lunch", "dinner", "snack"):
        meal_type = ""
    description = request.form.get("description", "").strip()
    if not it: it = datetime.now().strftime("%Y-%m-%d %H:%M")
    source_type = request.form.get("source_type", "manual").strip()
    if source_type not in ("manual", "image_recognition", "glasses"):
        source_type = "manual"
    image_url = ""
    try:
        image_url = save_diet_image(request.form.get("image_data", "").strip())
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("recognition") if source_type != "manual" else url_for("diet"))
    suggestions_json = encode_recognition_suggestions(request.form.get("recognition_suggestions", ""))
    try:
        c.execute(
            "INSERT INTO diet_records "
            "(user_id,food_name,weight_grams,calories,protein_g,fat_g,carbs_g,fiber_g,meal_type,description,"
            "intake_time,image_url,source_type,recognition_suggestions) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (user["id"], fn, weight_value, cal, protein, fat, carbs, fiber, meal_type, description,
             it, image_url, source_type, suggestions_json),
        )
        c.commit()
    except Exception:
        remove_managed_diet_image(image_url)
        raise
    flash(f"已记录：{fn} {weight_value}g = {cal}kcal")
    return redirect(url_for("diet", tab="today"))


@app.route("/api/recognition/analyze", methods=["POST"])
@login_required
def recognition_analyze():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "请求体必须是 JSON"}), 400
    try:
        result = analyze_image(payload.get("image"))
    except RecognitionUnavailable as error:
        return jsonify({"ok": False, "error": str(error), "code": "recognition_unavailable"}), 503
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error), "code": "invalid_image"}), 400
    except Exception:
        app.logger.exception("Food recognition failed")
        return jsonify({"ok": False, "error": "图像识别失败，请更换清晰图片后重试"}), 500
    return jsonify({"ok": True, **result})


@app.route("/api/video-intake/import", methods=["POST"])
@login_required
def video_intake_import():
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("session_id", "")).strip()
    if not session_id or not re.fullmatch(r"sess_[0-9_a-f]+", session_id):
        return jsonify({"ok": False, "error": "session_id 无效"}), 400

    import json as _json
    import ssl
    import urllib.request

    backend = os.environ.get("VIDEO_BACKEND_URL", "https://127.0.0.1:8000")
    cert_path = os.environ.get(
        "VIDEO_BACKEND_CA",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "services", "recognition", "cert.pem"),
    )
    if os.path.exists(cert_path):
        ctx = ssl.create_default_context(cafile=cert_path)
        ctx.check_hostname = False
    else:
        ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(f"{backend}/api/sessions/{session_id}/state", context=ctx, timeout=10) as resp:
            state = _json.loads(resp.read())
    except Exception:
        return jsonify({"ok": False, "error": "无法连接视频后端或会话不存在"}), 502

    try:
        from recognition_adapter import RECORD_NAME_BY_PROFILE
    except ImportError:
        RECORD_NAME_BY_PROFILE = {}

    user = get_user()
    c = db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    imported, skipped = [], []
    for food in state.get("foods", []):
        weight = float(food.get("intake_weight_sum_g") or 0)
        if weight < 1:
            continue
        name = RECORD_NAME_BY_PROFILE.get(food.get("profile_key")) or food.get("name")
        lib = c.execute("SELECT * FROM food_library WHERE name=?", (name,)).fetchone()
        if not lib:
            skipped.append({"name": name, "weight_g": round(weight, 1), "reason": "不在食物库"})
            continue
        cal = round(lib["calories_per_100g"] * weight / 100, 1)
        c.execute(
            "INSERT INTO diet_records (user_id,food_name,weight_grams,calories,intake_time) VALUES (?,?,?,?,?)",
            (user["id"], name, round(weight, 1), cal, now),
        )
        imported.append({"name": name, "weight_g": round(weight, 1), "calories": cal})
    c.commit()
    total_cal = round(sum(item["calories"] for item in imported), 1)
    return jsonify({"ok": True, "imported": imported, "skipped": skipped, "total_calories": total_cal})
@app.route("/api/diet/<int:rid>/recommendations", methods=["POST"])
@login_required
def diet_recommendations(rid):
    user = get_user(); c = db()
    record = c.execute(
        "SELECT * FROM diet_records WHERE id=? AND user_id=?", (rid, user["id"])
    ).fetchone()
    if not record:
        abort(404)
    image_data = diet_image_data_url(record["image_url"])
    if not image_data:
        return jsonify({"ok": False, "error": "这条记录没有可重新分析的原始图片"}), 400
    try:
        result = analyze_image(image_data)
    except RecognitionUnavailable as error:
        return jsonify({"ok": False, "error": str(error), "code": "recognition_unavailable"}), 503
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error), "code": "invalid_image"}), 400
    except Exception:
        app.logger.exception("Diet recommendation refresh failed")
        return jsonify({"ok": False, "error": "图片重新识别失败，请稍后重试"}), 500
    suggestions_json = encode_recognition_suggestions(result.get("foods", []))
    c.execute("UPDATE diet_records SET recognition_suggestions=? WHERE id=?", (suggestions_json, rid))
    c.commit()
    return jsonify({"ok": True, **result})


@app.route("/diet/correct/<int:rid>", methods=["POST"])
@login_required
def diet_correct(rid):
    user = get_user(); c = db()
    record = c.execute(
        "SELECT * FROM diet_records WHERE id=? AND user_id=?", (rid, user["id"])
    ).fetchone()
    if not record:
        abort(404)
    food_name = request.form.get("food_name", "").strip()
    weight_raw = request.form.get("weight_grams", "").strip()
    try:
        weight_value = parse_number(weight_raw, "克重", 0.5, 5000, required=True)
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("diet", tab=request.form.get("return_tab", "today"), correct=rid))
    food = c.execute("SELECT * FROM food_library WHERE name=?", (food_name,)).fetchone()
    if not food:
        flash("请选择食物库中的食物", "error")
        return redirect(url_for("diet", tab=request.form.get("return_tab", "today"), correct=rid))
    calories = round(food["calories_per_100g"] * weight_value / 100, 1)
    factor = weight_value / 100.0
    protein = round(food["protein_g"] * factor, 1)
    fat = round(food["fat_g"] * factor, 1)
    carbs = round(food["carbs_g"] * factor, 1)
    fiber = round(food["fiber_g"] * factor, 1)
    new_image_data = request.form.get("image_data", "").strip()
    new_image_url = ""
    if new_image_data:
        try:
            new_image_url = save_diet_image(new_image_data)
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("diet", tab=request.form.get("return_tab", "today"), correct=rid))
    suggestions_json = encode_recognition_suggestions(request.form.get("recognition_suggestions", ""))
    image_url = new_image_url or record["image_url"]
    if not suggestions_json:
        suggestions_json = record["recognition_suggestions"] or ""
    try:
        c.execute(
            "UPDATE diet_records SET food_name=?,weight_grams=?,calories=?,protein_g=?,fat_g=?,carbs_g=?,fiber_g=?,image_url=?,"
            "recognition_suggestions=?,original_food_name=COALESCE(original_food_name,?),"
            "original_weight_grams=COALESCE(original_weight_grams,?),corrected_at=? "
            "WHERE id=? AND user_id=?",
            (food_name, weight_value, calories, protein, fat, carbs, fiber, image_url, suggestions_json,
             record["food_name"], record["weight_grams"],
             datetime.now().strftime("%Y-%m-%d %H:%M"), rid, user["id"]),
        )
        c.commit()
    except Exception:
        remove_managed_diet_image(new_image_url)
        raise
    if new_image_url and record["image_url"] != new_image_url:
        remove_managed_diet_image(record["image_url"])
    flash(f"已修正为：{food_name} {weight_value}g = {calories}kcal")
    return redirect(url_for("diet", tab=request.form.get("return_tab", "today")))


@app.route("/diet/delete/<int:rid>", methods=["POST"])
@login_required
def diet_delete(rid):
    u = get_user(); c = db()
    record = c.execute("SELECT image_url FROM diet_records WHERE id=? AND user_id=?", (rid, u["id"])).fetchone()
    c.execute("DELETE FROM diet_records WHERE id=? AND user_id=?", (rid, u["id"])); c.commit()
    if record:
        remove_managed_diet_image(record["image_url"])
    flash("记录已删除")
    return redirect(url_for("diet", tab=request.form.get("return_tab", "today")))


# ── 绑定 ────────────────────────────────────────────────
@app.route("/bind", methods=["GET", "POST"])
@login_required
def bind():
    user = get_user()
    if request.method == "POST":
        mode = request.form.get("mode", "code"); bind_code = request.form.get("bind_code", "").strip()
        scan_data = request.form.get("scan_data", "").strip()
        c = db(); code = scan_data if (mode == "scan" and scan_data) else bind_code
        if not code: flash("请输入或扫描绑定码"); return redirect(url_for("bind"))
        code = code.upper()
        target = c.execute(
            "SELECT id,nickname FROM users WHERE share_code=? OR supervisor_code=? OR supervisee_code=?",
            (code, code, code),
        ).fetchone()
        if not target:
            flash("绑定码无效", "error"); return redirect(url_for("bind"))
        if target["id"] == user["id"]:
            flash("不能绑定自己", "error"); return redirect(url_for("bind"))
        remark = request.form.get("remark", "").strip()[:40]
        share_diet, share_goal, share_profile = sharing_flags()
        existing = get_connection(user["id"], other_id=target["id"])
        if existing and existing["status"] == "active":
            flash(f"你已经和 {target['nickname']} 建立了共享关系"); return redirect(url_for("profile"))
        if existing and existing["requested_by"] != user["id"]:
            flash(f"{target['nickname']} 已向你发出请求，请在个人主页确认", "warning")
            return redirect(url_for("profile"))
        user_a_id, user_b_id = sorted((user["id"], target["id"]))
        if not existing:
            c.execute(
                "INSERT INTO user_connections (user_a_id,user_b_id,requested_by,status) VALUES (?,?,?,'pending')",
                (user_a_id, user_b_id, user["id"]),
            )
            connection_id = c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        else:
            connection_id = existing["id"]
        prefix = "a" if user["id"] == user_a_id else "b"
        c.execute(
            f"UPDATE user_connections SET {prefix}_remark_for_{'b' if prefix == 'a' else 'a'}=?, "
            f"{prefix}_share_diet=?, {prefix}_share_goal=?, {prefix}_share_profile=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (remark, share_diet, share_goal, share_profile, connection_id),
        )
        c.commit()
        flash(f"已向 {target['nickname']} 发送绑定请求")
        return redirect(url_for("profile"))
    return render_template("bind.html", user=user)


@app.route("/connections/<int:connection_id>/respond", methods=["POST"])
@login_required
def connection_respond(connection_id):
    user = get_user()
    connection = get_connection(user["id"], connection_id=connection_id, status="pending")
    if not connection or connection["requested_by"] == user["id"]:
        abort(404)
    c = db()
    if request.form.get("action") != "accept":
        c.execute("DELETE FROM user_connections WHERE id=?", (connection_id,))
        c.commit(); flash("已拒绝绑定请求"); return redirect(url_for("profile"))
    prefix = "a" if connection["user_a_id"] == user["id"] else "b"
    other_prefix = "b" if prefix == "a" else "a"
    remark = request.form.get("remark", "").strip()[:40]
    share_diet, share_goal, share_profile = sharing_flags()
    c.execute(
        f"UPDATE user_connections SET {prefix}_remark_for_{other_prefix}=?, "
        f"{prefix}_share_diet=?, {prefix}_share_goal=?, {prefix}_share_profile=?, "
        "status='active', accepted_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (remark, share_diet, share_goal, share_profile, connection_id),
    )
    c.commit()
    flash("绑定已确认，双方现在可以按授权范围查看数据")
    return redirect(url_for("profile"))


@app.route("/connections/<int:connection_id>/settings", methods=["POST"])
@login_required
def connection_settings(connection_id):
    user = get_user(); connection = get_connection(user["id"], connection_id=connection_id, status="active")
    if not connection:
        abort(404)
    prefix = "a" if connection["user_a_id"] == user["id"] else "b"
    other_prefix = "b" if prefix == "a" else "a"
    remark = request.form.get("remark", "").strip()[:40]
    share_diet, share_goal, share_profile = sharing_flags()
    c = db(); c.execute(
        f"UPDATE user_connections SET {prefix}_remark_for_{other_prefix}=?, "
        f"{prefix}_share_diet=?, {prefix}_share_goal=?, {prefix}_share_profile=?, "
        "updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (remark, share_diet, share_goal, share_profile, connection_id),
    ); c.commit()
    flash("备注与共享权限已更新")
    return redirect(url_for("profile"))


@app.route("/connections/<int:connection_id>/unbind", methods=["POST"])
@login_required
def connection_unbind(connection_id):
    user = get_user(); connection = get_connection(user["id"], connection_id=connection_id)
    if not connection:
        abort(404)
    c = db(); c.execute("DELETE FROM user_connections WHERE id=?", (connection_id,)); c.commit()
    flash("已解除绑定，双方共享权限同时撤销")
    return redirect(url_for("profile"))


# ── 个人主页 ────────────────────────────────────────────
@app.route("/profile")
@login_required
def profile():
    user = get_user(); c = db()
    connections = get_connection_rows(user["id"], "active")
    pending = get_connection_rows(user["id"], "pending")
    pending_received = [row for row in pending if row["requested_by"] != user["id"]]
    pending_sent = [row for row in pending if row["requested_by"] == user["id"]]
    tr = c.execute("SELECT COUNT(*) as c FROM diet_records WHERE user_id=?", (user["id"],)).fetchone()["c"]
    td = c.execute("SELECT COUNT(DISTINCT date(intake_time)) as c FROM diet_records WHERE user_id=?", (user["id"],)).fetchone()["c"]
    return render_template("profile.html", user=user, connections=connections,
                           pending_received=pending_received, pending_sent=pending_sent,
                           total_records=tr, total_days=td, QR_AVAILABLE=QR_AVAILABLE)


@app.route("/shared/<int:owner_id>")
@login_required
def shared_profile(owner_id):
    user = get_user(); c = db()
    if owner_id == user["id"]:
        return redirect(url_for("profile"))
    connection = get_connection(user["id"], other_id=owner_id, status="active")
    if not connection:
        abort(403)
    owner = c.execute("SELECT * FROM users WHERE id=?", (owner_id,)).fetchone()
    if not owner:
        abort(404)
    allow_goal = can_view_shared(user["id"], owner_id, "goal")
    allow_profile = can_view_shared(user["id"], owner_id, "profile")
    allow_diet = can_view_shared(user["id"], owner_id, "diet")
    if not any((allow_goal, allow_profile, allow_diet)):
        abort(403, description="对方尚未向你开放任何资料")
    today_calories = c.execute(
        "SELECT COALESCE(SUM(calories),0) AS total FROM diet_records "
        "WHERE user_id=? AND date(intake_time)=date('now','localtime')", (owner_id,),
    ).fetchone()["total"]
    return render_template("shared_profile.html", user=user, owner=owner, connection=connection,
                           allow_goal=allow_goal, allow_profile=allow_profile,
                           allow_diet=allow_diet, today_calories=today_calories)


@app.route("/profile/edit", methods=["POST"])
@login_required
def profile_edit():
    u = get_user(); n = request.form.get("nickname","").strip()
    h = request.form.get("height","").strip(); w = request.form.get("weight","").strip()
    a = request.form.get("age","").strip(); g = request.form.get("gender","").strip()
    hg = request.form.get("health_goal","").strip()
    if not n: flash("昵称不能为空"); return redirect(url_for("profile"))
    old_avatar = u["avatar_url"] or ""
    av = old_avatar
    avatar_file = request.files.get("avatar")
    remove_avatar = request.form.get("remove_avatar") == "1"
    if avatar_file and avatar_file.filename:
        try:
            av = save_avatar(avatar_file)
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("profile"))
    elif remove_avatar:
        av = ""
    try:
        height_value = parse_number(h, "身高", 80, 250) if h else u["height"]
        weight_value = parse_number(w, "体重", 20, 400) if w else u["weight"]
        age_value = parse_number(a, "年龄", 6, 120, integer=True) if a else u["age"]
    except ValueError as error:
        flash(str(error), "error"); return redirect(url_for("profile"))
    if hg and hg not in ("weight_management", "blood_sugar", "blood_pressure"):
        flash("健康目标无效", "error"); return redirect(url_for("profile"))
    c = db(); c.execute(
        "UPDATE users SET nickname=?,avatar_url=?,height=?,weight=?,age=?,gender=?,health_goal=? WHERE id=?",
        (n, av, height_value, weight_value, age_value, g if g in ("male","female") else u["gender"],
         hg if hg else u["health_goal"], u["id"])); c.commit()
    if av != old_avatar:
        remove_managed_avatar(old_avatar)
    flash("个人信息已更新"); return redirect(url_for("profile"))


@app.route("/profile/change-password", methods=["POST"])
@login_required
def change_password():
    u = get_user(); op = request.form.get("old_password",""); np = request.form.get("new_password","")
    if not check_password_hash(u["password_hash"], op): flash("原密码错误"); return redirect(url_for("profile"))
    ok, msg = validate_password(np)
    if not ok: flash(msg); return redirect(url_for("profile"))
    c = db(); c.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(np), u["id"])); c.commit()
    flash("密码已修改"); return redirect(url_for("profile"))


@app.route("/profile/switch-mode", methods=["POST"])
@login_required
def switch_mode():
    u = get_user(); g = request.form.get("health_goal","").strip()
    if g not in ("weight_management","blood_sugar","blood_pressure"): flash("无效的模式"); return redirect(url_for("profile"))
    c = db(); c.execute("UPDATE users SET health_goal=? WHERE id=?", (g, u["id"])); c.commit()
    names = {"weight_management":"体重管理","blood_sugar":"血糖管理","blood_pressure":"血压管理"}
    flash(f"已切换到「{names[g]}」模式"); return redirect(url_for("profile"))


@app.route("/help")
@login_required
def help_center():
    return render_template("help.html")


if __name__ == "__main__":
    runtime_dir = os.environ.get(
        "HEALTH_RUNTIME_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".workspace", "run", "user-web"),
    )
    os.makedirs(runtime_dir, exist_ok=True)
    pid_path = os.path.join(runtime_dir, ".health-server.pid")
    with open(pid_path, "w", encoding="ascii") as pid_file:
        pid_file.write(str(os.getpid()))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    print("\n◆  V&B App 启动中...\n   访问 http://127.0.0.1:5000\n")
    try:
        app.run(debug=False, use_reloader=False, host="127.0.0.1", port=5000)
    finally:
        try:
            os.remove(pid_path)
        except OSError:
            pass
