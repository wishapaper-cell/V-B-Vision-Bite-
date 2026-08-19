import csv
import hashlib
import io
import os
import re
import secrets
import sqlite3
import string
import sys
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, Response, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from admin_database import ADMIN_DB_PATH, USER_DB_PATH, admin_db, init_admin_db, init_user_db, user_db


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STARTED_AT = time.time()
BACKUP_DIR = os.environ.get(
    "ADMIN_BACKUP_DIR",
    os.path.join(os.path.dirname(os.path.abspath(ADMIN_DB_PATH)), "backups"),
)


def load_secret():
    configured = os.environ.get("ADMIN_SECRET_KEY")
    if configured:
        return configured
    runtime_dir = os.environ.get("ADMIN_RUNTIME_DIR", os.path.dirname(os.path.abspath(ADMIN_DB_PATH)))
    os.makedirs(runtime_dir, exist_ok=True)
    path = os.path.join(runtime_dir, ".admin-session-secret")
    try:
        with open(path, "r", encoding="ascii") as file:
            value = file.read().strip()
            if len(value) >= 32:
                return value
    except OSError:
        pass
    value = secrets.token_hex(32)
    try:
        with open(path, "x", encoding="ascii") as file:
            file.write(value)
    except FileExistsError:
        with open(path, "r", encoding="ascii") as file:
            value = file.read().strip()
    return value


app = Flask(__name__)
app.secret_key = load_secret()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)
init_admin_db()
init_user_db()


def adb():
    if "admin_db" not in g:
        g.admin_db = admin_db()
    return g.admin_db


def udb():
    if "user_db" not in g:
        g.user_db = user_db()
    return g.user_db


@app.teardown_appcontext
def close_connections(error=None):
    for key in ("admin_db", "user_db"):
        connection = g.pop(key, None)
        if connection is not None:
            connection.close()


def first_admin_exists():
    return adb().execute("SELECT 1 FROM admins LIMIT 1").fetchone() is not None


def current_admin():
    admin_id = session.get("admin_id")
    if not admin_id:
        return None
    return adb().execute("SELECT * FROM admins WHERE id=? AND active=1", (admin_id,)).fetchone()


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_admin():
            session.clear()
            flash("请先登录管理端", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def super_admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        admin = current_admin()
        if not admin:
            session.clear()
            flash("请先登录管理端", "warning")
            return redirect(url_for("login"))
        if admin["role"] != "super_admin":
            abort(403, description="仅超级管理员可以管理管理员账号")
        return view(*args, **kwargs)
    return wrapped


@app.before_request
def security_checks():
    if request.method == "POST":
        expected = session.get("csrf_token", "")
        supplied = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
        if not expected or not supplied or not secrets.compare_digest(expected, supplied):
            abort(400, description="请求已失效，请刷新页面后重试")


@app.context_processor
def shared_context():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {
        "admin": current_admin(),
        "csrf_token": session["csrf_token"],
        "user_db_path": USER_DB_PATH,
    }


def audit(action, target_type, target_id="", detail=""):
    admin = current_admin()
    connection = adb()
    connection.execute(
        "INSERT INTO audit_logs (admin_id,admin_name,action,target_type,target_id,detail,ip_address) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            admin["id"] if admin else None,
            admin["display_name"] if admin else "系统",
            action,
            target_type,
            str(target_id or ""),
            detail,
            request.remote_addr or "",
        ),
    )
    connection.commit()


def validate_password(password):
    return (
        len(password) >= 10
        and any(char.isupper() for char in password)
        and any(char.islower() for char in password)
        and any(char.isdigit() for char in password)
    )


def generate_bind_code():
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def normalize_invite_code(code):
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def hash_invite_code(code):
    return hashlib.sha256(normalize_invite_code(code).encode("ascii")).hexdigest()


def csv_download(filename, headers, rows):
    stream = io.StringIO()
    stream.write("\ufeff")
    writer = csv.writer(stream)
    if headers:
        writer.writerow(headers)
    writer.writerows(rows)
    return Response(
        stream.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route("/")
def index():
    if not first_admin_exists():
        return redirect(url_for("setup"))
    return redirect(url_for("dashboard") if current_admin() else url_for("login"))


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if first_admin_exists():
        return redirect(url_for("login"))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        display_name = request.form.get("display_name", "").strip()
        password = request.form.get("password", "")
        if not re.fullmatch(r"[a-zA-Z0-9_]{4,30}", username):
            flash("账号须为 4–30 位字母、数字或下划线", "error")
        elif not display_name or len(display_name) > 30:
            flash("请输入 1–30 位管理员名称", "error")
        elif not validate_password(password):
            flash("密码至少 10 位，并包含大小写字母和数字", "error")
        else:
            connection = adb()
            connection.execute(
                "INSERT INTO admins (username,password_hash,display_name) VALUES (?,?,?)",
                (username, generate_password_hash(password), display_name),
            )
            connection.commit()
            flash("超级管理员创建成功，请登录", "success")
            return redirect(url_for("login"))
    return render_template("setup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if not first_admin_exists():
        return redirect(url_for("setup"))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        connection = adb()
        failures = connection.execute(
            "SELECT COUNT(*) AS c FROM login_attempts WHERE username=? AND success=0 "
            "AND created_at >= datetime('now', '-15 minutes')",
            (username,),
        ).fetchone()["c"]
        if failures >= 5:
            flash("登录失败次数过多，请 15 分钟后再试", "error")
            return render_template("login.html")
        admin = connection.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
        credentials_valid = bool(admin and check_password_hash(admin["password_hash"], password))
        connection.execute("INSERT INTO login_attempts (username,success) VALUES (?,?)", (username, int(credentials_valid)))
        connection.commit()
        if not credentials_valid:
            flash("管理员账号或密码错误", "error")
            return render_template("login.html")
        if admin["approval_status"] == "pending":
            flash("账号正在等待超级管理员审核，审核通过后才能登录。", "warning")
            return render_template("login.html")
        if admin["approval_status"] == "rejected":
            flash("管理员注册申请未通过，请联系超级管理员。", "error")
            return render_template("login.html")
        if not admin["active"]:
            flash("管理员账号已被禁用，请联系超级管理员。", "error")
            return render_template("login.html")
        session.clear()
        session["admin_id"] = admin["id"]
        session["csrf_token"] = secrets.token_urlsafe(32)
        connection.execute("UPDATE admins SET last_login_at=CURRENT_TIMESTAMP WHERE id=?", (admin["id"],))
        connection.commit()
        audit("登录管理端", "admin", admin["id"])
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register_admin():
    if not first_admin_exists():
        return redirect(url_for("setup"))
    if current_admin():
        return redirect(url_for("dashboard"))
    invite_code = request.form.get("invite_code", "").strip() if request.method == "POST" else request.args.get("code", "").strip()
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        display_name = request.form.get("display_name", "").strip()
        email = request.form.get("email", "").strip() or None
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")
        normalized_code = normalize_invite_code(invite_code)
        connection = adb()
        invitation = connection.execute(
            "SELECT * FROM admin_invitations WHERE code_hash=? AND used_at IS NULL AND revoked_at IS NULL "
            "AND expires_at>CURRENT_TIMESTAMP",
            (hash_invite_code(normalized_code),),
        ).fetchone() if normalized_code else None
        if not invitation:
            flash("邀请码无效、已使用或已经过期。", "error")
        elif not re.fullmatch(r"[a-zA-Z0-9_]{4,30}", username):
            flash("账号须为 4–30 位字母、数字或下划线。", "error")
        elif not display_name or len(display_name) > 30:
            flash("请输入 1–30 位管理员名称。", "error")
        elif email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            flash("邮箱格式无效。", "error")
        elif not validate_password(password):
            flash("密码至少 10 位，并包含大小写字母和数字。", "error")
        elif password != password_confirm:
            flash("两次输入的密码不一致。", "error")
        elif connection.execute("SELECT 1 FROM admins WHERE username=?", (username,)).fetchone():
            flash("管理员账号已经存在。", "error")
        else:
            try:
                cursor = connection.execute(
                    "INSERT INTO admins (username,password_hash,display_name,role,active,approval_status,email,approved_by,approved_at) "
                    "VALUES (?,?,?,'admin',1,'approved',?,?,CURRENT_TIMESTAMP)",
                    (username, generate_password_hash(password), display_name, email, invitation["created_by"]),
                )
                admin_id = cursor.lastrowid
                connection.execute(
                    "UPDATE admin_invitations SET used_at=CURRENT_TIMESTAMP,used_by=? WHERE id=? AND used_at IS NULL",
                    (admin_id, invitation["id"]),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            audit("完成受邀管理员注册", "admin", admin_id, f"账号：{username}")
            return redirect(url_for("login"))
    return render_template("register_admin.html", invite_code=invite_code)


@app.route("/logout", methods=["POST"])
@admin_required
def logout():
    audit("退出管理端", "admin", session.get("admin_id"))
    session.clear()
    return redirect(url_for("login"))


@app.route("/admins", methods=["GET", "POST"])
@super_admin_required
def admin_accounts():
    connection = adb()
    if request.method == "POST":
        invitee_name = request.form.get("invitee_name", "").strip()
        invitee_contact = request.form.get("invitee_contact", "").strip()
        try:
            expiry_hours = int(request.form.get("expiry_hours", "24"))
        except ValueError:
            expiry_hours = 0
        if not invitee_name or len(invitee_name) > 50:
            flash("请输入 1–50 位受邀人名称。", "error")
        elif len(invitee_contact) > 100:
            flash("联系方式不能超过 100 个字符。", "error")
        elif expiry_hours not in (24, 72, 168):
            flash("邀请码有效期无效。", "error")
        else:
            alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
            raw_code = "".join(secrets.choice(alphabet) for _ in range(16))
            invite_code = "-".join(raw_code[index:index + 4] for index in range(0, 16, 4))
            connection.execute(
                "INSERT INTO admin_invitations (code_hash,invitee_name,invitee_contact,created_by,expires_at) "
                "VALUES (?,?,?,?,datetime('now',?))",
                (hash_invite_code(invite_code), invitee_name, invitee_contact, current_admin()["id"], f"+{expiry_hours} hours"),
            )
            connection.commit()
            audit("生成管理员邀请码", "admin_invitation", "", f"受邀人：{invitee_name}；有效期：{expiry_hours} 小时")
            session["new_admin_invite_code"] = invite_code
            flash("邀请码已生成，请立即复制并发送给受邀人。", "success")
            return redirect(url_for("admin_accounts"))
    admins = connection.execute("SELECT * FROM admins ORDER BY approval_status='pending' DESC,created_at DESC,id DESC").fetchall()
    invitations = connection.execute("""
        SELECT i.*,creator.display_name AS creator_name,used.display_name AS used_by_name,
               CASE WHEN i.revoked_at IS NOT NULL THEN 'revoked'
                    WHEN i.used_at IS NOT NULL THEN 'used'
                    WHEN i.expires_at<=CURRENT_TIMESTAMP THEN 'expired'
                    ELSE 'active' END AS invite_status
        FROM admin_invitations i
        LEFT JOIN admins creator ON creator.id=i.created_by
        LEFT JOIN admins used ON used.id=i.used_by
        ORDER BY i.created_at DESC,i.id DESC LIMIT 100
    """).fetchall()
    new_invite_code = session.pop("new_admin_invite_code", None)
    return render_template(
        "admins.html", admins=admins, invitations=invitations, new_invite_code=new_invite_code,
    )


@app.route("/admins/<int:admin_id>/approve", methods=["POST"])
@super_admin_required
def approve_admin(admin_id):
    connection = adb()
    target = connection.execute("SELECT * FROM admins WHERE id=?", (admin_id,)).fetchone()
    if not target:
        abort(404)
    if target["approval_status"] != "pending":
        flash("该管理员申请已经处理。", "warning")
    else:
        connection.execute(
            "UPDATE admins SET approval_status='approved',active=1,approved_by=?,approved_at=CURRENT_TIMESTAMP WHERE id=?",
            (current_admin()["id"], admin_id),
        )
        connection.commit()
        audit("审核通过管理员", "admin", admin_id, f"账号：{target['username']}")
        flash("管理员申请已通过。", "success")
    return redirect(url_for("admin_accounts"))


@app.route("/admins/<int:admin_id>/reject", methods=["POST"])
@super_admin_required
def reject_admin(admin_id):
    connection = adb()
    target = connection.execute("SELECT * FROM admins WHERE id=?", (admin_id,)).fetchone()
    if not target:
        abort(404)
    if target["approval_status"] != "pending":
        flash("该管理员申请已经处理。", "warning")
    else:
        connection.execute("UPDATE admins SET approval_status='rejected',active=0 WHERE id=?", (admin_id,))
        connection.commit()
        audit("拒绝管理员申请", "admin", admin_id, f"账号：{target['username']}")
        flash("管理员申请已拒绝。", "success")
    return redirect(url_for("admin_accounts"))


@app.route("/admins/<int:admin_id>/status", methods=["POST"])
@super_admin_required
def toggle_admin_status(admin_id):
    connection = adb()
    target = connection.execute("SELECT * FROM admins WHERE id=?", (admin_id,)).fetchone()
    if not target:
        abort(404)
    if target["id"] == current_admin()["id"]:
        flash("不能禁用当前正在使用的管理员账号。", "error")
        return redirect(url_for("admin_accounts"))
    if target["approval_status"] != "approved":
        flash("只有审核通过的管理员才能启用或禁用。", "warning")
        return redirect(url_for("admin_accounts"))
    if target["role"] == "super_admin" and target["active"]:
        active_super_admins = connection.execute(
            "SELECT COUNT(*) AS c FROM admins WHERE role='super_admin' AND active=1 AND approval_status='approved'"
        ).fetchone()["c"]
        if active_super_admins <= 1:
            flash("系统必须至少保留一个启用的超级管理员。", "error")
            return redirect(url_for("admin_accounts"))
    new_status = 0 if target["active"] else 1
    connection.execute("UPDATE admins SET active=? WHERE id=?", (new_status, admin_id))
    connection.commit()
    audit("启用管理员" if new_status else "禁用管理员", "admin", admin_id, f"账号：{target['username']}")
    flash("管理员账号已启用。" if new_status else "管理员账号已禁用。", "success")
    return redirect(url_for("admin_accounts"))


@app.route("/admin-invitations/<int:invitation_id>/revoke", methods=["POST"])
@super_admin_required
def revoke_admin_invitation(invitation_id):
    connection = adb()
    invitation = connection.execute("SELECT * FROM admin_invitations WHERE id=?", (invitation_id,)).fetchone()
    if not invitation:
        abort(404)
    if invitation["used_at"] or invitation["revoked_at"]:
        flash("该邀请码已经使用或撤销。", "warning")
    else:
        connection.execute("UPDATE admin_invitations SET revoked_at=CURRENT_TIMESTAMP WHERE id=?", (invitation_id,))
        connection.commit()
        audit("撤销管理员邀请码", "admin_invitation", invitation_id, invitation["invitee_name"])
        flash("邀请码已撤销。", "success")
    return redirect(url_for("admin_accounts"))


@app.route("/dashboard")
@admin_required
def dashboard():
    connection = udb()
    stats = {
        "users": connection.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"],
        "active_7d": connection.execute(
            "SELECT COUNT(*) AS c FROM users WHERE active=1 AND last_active_at>=datetime('now','-7 days')"
        ).fetchone()["c"],
        "disabled": connection.execute("SELECT COUNT(*) AS c FROM users WHERE active=0").fetchone()["c"],
        "supervisors": connection.execute("SELECT COUNT(*) AS c FROM users WHERE role='supervisor'").fetchone()["c"],
        "bound": connection.execute("SELECT COUNT(*) AS c FROM users WHERE role='supervisee' AND bound_to IS NOT NULL").fetchone()["c"],
        "today_records": connection.execute("SELECT COUNT(*) AS c FROM diet_records WHERE date(intake_time)=date('now','localtime')").fetchone()["c"],
        "total_records": connection.execute("SELECT COUNT(*) AS c FROM diet_records").fetchone()["c"],
    }
    goals = connection.execute(
        "SELECT health_goal,COUNT(*) AS count FROM users GROUP BY health_goal ORDER BY count DESC"
    ).fetchall()
    trend = connection.execute("""
        WITH RECURSIVE dates(day) AS (
            SELECT date('now','localtime','-6 days')
            UNION ALL SELECT date(day,'+1 day') FROM dates WHERE day < date('now','localtime')
        )
        SELECT dates.day,COUNT(dr.id) AS count,COALESCE(SUM(dr.calories),0) AS calories
        FROM dates LEFT JOIN diet_records dr ON date(dr.intake_time)=dates.day
        GROUP BY dates.day ORDER BY dates.day
    """).fetchall()
    recent = connection.execute(
        "SELECT dr.*,u.nickname FROM diet_records dr JOIN users u ON u.id=dr.user_id "
        "ORDER BY dr.created_at DESC LIMIT 8"
    ).fetchall()
    nutrition = connection.execute("""
        SELECT COALESCE(SUM(calories),0) AS calories,
               COALESCE(SUM(protein_g),0) AS protein,
               COALESCE(SUM(fat_g),0) AS fat,
               COALESCE(SUM(carbs_g),0) AS carbs,
               COALESCE(SUM(fiber_g),0) AS fiber
        FROM diet_records WHERE intake_time>=datetime('now','-7 days')
    """).fetchone()
    health_risks = connection.execute(
        "SELECT risk_level,COUNT(*) AS count FROM users GROUP BY risk_level ORDER BY count DESC"
    ).fetchall()
    completion = connection.execute("""
        WITH daily AS (
            SELECT dr.user_id,date(dr.intake_time) AS day,SUM(dr.calories) AS consumed,
                   COALESCE(u.daily_calorie_target,2000) AS target
            FROM diet_records dr JOIN users u ON u.id=dr.user_id
            WHERE dr.intake_time>=datetime('now','-30 days')
            GROUP BY dr.user_id,date(dr.intake_time)
        )
        SELECT COUNT(*) AS days,
               COALESCE(AVG(CASE WHEN consumed BETWEEN target*0.9 AND target*1.1 THEN 100.0 ELSE 0 END),0) AS rate
        FROM daily
    """).fetchone()
    return render_template(
        "dashboard.html", stats=stats, goals=goals, trend=trend, recent=recent,
        nutrition=nutrition, health_risks=health_risks, completion=completion,
    )


@app.route("/users/<int:user_id>/export.csv")
@admin_required
def export_user(user_id):
    connection = udb()
    user = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        abort(404)
    records = connection.execute(
        "SELECT meal_type,food_name,weight_grams,calories,protein_g,fat_g,carbs_g,fiber_g,"
        "description,image_url,intake_time FROM diet_records WHERE user_id=? ORDER BY intake_time DESC",
        (user_id,),
    ).fetchall()
    daily = connection.execute("""
        SELECT date(intake_time) AS day,COUNT(*) AS record_count,
               COALESCE(SUM(calories),0) AS calories,COALESCE(SUM(protein_g),0) AS protein,
               COALESCE(SUM(fat_g),0) AS fat,COALESCE(SUM(carbs_g),0) AS carbs,
               COALESCE(SUM(fiber_g),0) AS fiber
        FROM diet_records WHERE user_id=? AND intake_time>=date('now','-29 days')
        GROUP BY date(intake_time) ORDER BY day
    """, (user_id,)).fetchall()
    daily_map = {row["day"]: row for row in daily}
    start_day = datetime.now().date() - timedelta(days=29)
    export_trend = []
    for offset in range(30):
        day = start_day + timedelta(days=offset)
        row = daily_map.get(day.isoformat())
        export_trend.append({
            "day": day.isoformat(),
            "record_count": row["record_count"] if row else 0,
            "calories": row["calories"] if row else 0,
            "protein": row["protein"] if row else 0,
            "fat": row["fat"] if row else 0,
            "carbs": row["carbs"] if row else 0,
            "fiber": row["fiber"] if row else 0,
        })
    target = float(user["daily_calorie_target"] or 2000)
    logged_days = len(daily)
    target_days = sum(1 for row in daily if target * 0.9 <= row["calories"] <= target * 1.1)
    totals = {
        "records": sum(row["record_count"] for row in daily),
        "calories": sum(row["calories"] for row in daily),
        "protein": sum(row["protein"] for row in daily),
        "fat": sum(row["fat"] for row in daily),
        "carbs": sum(row["carbs"] for row in daily),
        "fiber": sum(row["fiber"] for row in daily),
    }
    profile = (
        user["id"], user["nickname"], user["phone"], user["email"] or "",
        "监督人" if user["role"] == "supervisor" else "被监督人", "已启用" if user["active"] else "已禁用",
        user["height"], user["weight"], user["age"], {"male": "男", "female": "女"}.get(user["gender"], ""),
        {"weight_management": "体重管理", "blood_sugar": "血糖管理", "blood_pressure": "血压管理"}.get(user["health_goal"], ""),
        {"low": "低风险", "medium": "中风险", "high": "高风险"}.get(user["risk_level"], ""),
        user["medical_history"] or "", user["allergies"] or "", user["diet_preferences"] or "",
        user["dietary_restrictions"] or "", user["chronic_conditions"] or "", user["health_notes"] or "",
        user["daily_calorie_target"],
    )
    rows = [
        ["用户档案"],
        ["用户ID", "昵称", "手机号", "邮箱", "身份", "账号状态", "身高(cm)", "体重(kg)", "年龄", "性别",
         "健康目标", "风险等级", "既往病史", "过敏信息", "饮食偏好", "忌口与限制", "慢病信息",
         "健康备注", "每日热量目标(kcal)"],
        profile,
        [],
        ["近30天营养与计划分析"],
        ["饮食记录数", "有记录天数", "饮食计划完成率", "热量达标率", "热量(kcal)", "蛋白质(g)",
         "脂肪(g)", "碳水(g)", "纤维(g)"],
        [totals["records"], logged_days, f"{logged_days / 30 * 100:.1f}%",
         f"{target_days / logged_days * 100:.1f}%" if logged_days else "0.0%", round(totals["calories"], 1),
         round(totals["protein"], 1), round(totals["fat"], 1), round(totals["carbs"], 1), round(totals["fiber"], 1)],
        [],
        ["近30天热量达标趋势"],
        ["日期", "记录数", "热量(kcal)", "每日目标(kcal)", "是否达标", "蛋白质(g)", "脂肪(g)", "碳水(g)", "纤维(g)"],
    ]
    rows.extend([
        [row["day"], row["record_count"], round(row["calories"], 1), target,
         "达标" if target * 0.9 <= row["calories"] <= target * 1.1 else "未达标",
         round(row["protein"], 1), round(row["fat"], 1), round(row["carbs"], 1), round(row["fiber"], 1)]
        for row in export_trend
    ])
    rows.extend([
        [],
        ["全部饮食记录"],
        ["餐次", "食物", "克重(g)", "热量(kcal)", "蛋白质(g)", "脂肪(g)", "碳水(g)", "纤维(g)",
         "饮食描述", "照片地址", "摄入时间"],
    ])
    rows.extend([tuple(record) for record in records])
    return csv_download(f"user-{user_id}-diet-analysis.csv", [], rows)


@app.route("/users")
@admin_required
def users():
    query = request.args.get("q", "").strip()
    role = request.args.get("role", "").strip()
    status = request.args.get("status", "").strip()
    sql = "SELECT u.*,s.nickname AS supervisor_name FROM users u LEFT JOIN users s ON s.id=u.bound_to WHERE 1=1"
    params = []
    if query:
        sql += " AND (u.nickname LIKE ? OR u.phone LIKE ? OR COALESCE(u.email,'') LIKE ?)"
        pattern = f"%{query}%"
        params.extend([pattern, pattern, pattern])
    if role in ("supervisor", "supervisee"):
        sql += " AND u.role=?"
        params.append(role)
    if status in ("active", "disabled"):
        sql += " AND u.active=?"
        params.append(1 if status == "active" else 0)
    sql += " ORDER BY u.created_at DESC,u.id DESC"
    rows = udb().execute(sql, params).fetchall()
    return render_template("users.html", users=rows, query=query, role=role, status=status)


@app.route("/users/<int:user_id>")
@admin_required
def user_detail(user_id):
    connection = udb()
    user = connection.execute(
        "SELECT u.*,s.nickname AS supervisor_name FROM users u LEFT JOIN users s ON s.id=u.bound_to WHERE u.id=?",
        (user_id,),
    ).fetchone()
    if not user:
        abort(404)
    records = connection.execute(
        "SELECT * FROM diet_records WHERE user_id=? ORDER BY intake_time DESC LIMIT 50", (user_id,)
    ).fetchall()
    supervisees = connection.execute(
        "SELECT id,nickname,phone FROM users WHERE bound_to=? ORDER BY nickname", (user_id,)
    ).fetchall()
    return render_template("user_detail.html", user=user, records=records, supervisees=supervisees)


@app.route("/users/<int:user_id>/edit", methods=["POST"])
@admin_required
def edit_user(user_id):
    connection = udb()
    user = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        abort(404)

    nickname = request.form.get("nickname", "").strip()
    phone = request.form.get("phone", "").strip()
    email = request.form.get("email", "").strip() or None
    role = request.form.get("role", "").strip()
    gender = request.form.get("gender", "").strip() or None
    health_goal = request.form.get("health_goal", "").strip() or "weight_management"
    risk_level = request.form.get("risk_level", "low").strip()

    if not nickname or not phone:
        flash("昵称和手机号不能为空。", "error")
        return redirect(url_for("user_detail", user_id=user_id))
    if role not in ("supervisor", "supervisee"):
        flash("用户身份无效。", "error")
        return redirect(url_for("user_detail", user_id=user_id))
    if gender not in (None, "male", "female"):
        flash("性别选项无效。", "error")
        return redirect(url_for("user_detail", user_id=user_id))
    if health_goal not in ("weight_management", "blood_sugar", "blood_pressure"):
        flash("健康目标无效。", "error")
        return redirect(url_for("user_detail", user_id=user_id))
    if risk_level not in ("low", "medium", "high"):
        flash("风险等级无效。", "error")
        return redirect(url_for("user_detail", user_id=user_id))

    def optional_number(name, integer=False):
        value = request.form.get(name, "").strip()
        if not value:
            return None
        return int(value) if integer else float(value)

    try:
        height = optional_number("height")
        weight = optional_number("weight")
        age = optional_number("age", integer=True)
        daily_target = optional_number("daily_calorie_target")
    except ValueError:
        flash("身高、体重、年龄和热量目标必须是有效数字。", "error")
        return redirect(url_for("user_detail", user_id=user_id))

    if height is not None and not 80 <= height <= 250:
        flash("身高应在 80–250 cm 之间。", "error")
        return redirect(url_for("user_detail", user_id=user_id))
    if weight is not None and not 20 <= weight <= 400:
        flash("体重应在 20–400 kg 之间。", "error")
        return redirect(url_for("user_detail", user_id=user_id))
    if age is not None and not 1 <= age <= 120:
        flash("年龄应在 1–120 岁之间。", "error")
        return redirect(url_for("user_detail", user_id=user_id))
    if daily_target is not None and not 500 <= daily_target <= 10000:
        flash("每日热量目标应在 500–10000 kcal 之间。", "error")
        return redirect(url_for("user_detail", user_id=user_id))

    values = (
        phone, email, role, nickname, height, weight, age, gender, health_goal,
        request.form.get("medical_history", "").strip(),
        request.form.get("allergies", "").strip(),
        request.form.get("diet_preferences", "").strip(),
        request.form.get("dietary_restrictions", "").strip(),
        request.form.get("chronic_conditions", "").strip(),
        risk_level,
        request.form.get("health_notes", "").strip(),
        daily_target,
        user_id,
    )
    try:
        connection.execute("""
            UPDATE users SET phone=?,email=?,role=?,nickname=?,height=?,weight=?,age=?,gender=?,health_goal=?,
                medical_history=?,allergies=?,diet_preferences=?,dietary_restrictions=?,chronic_conditions=?,
                risk_level=?,health_notes=?,daily_calorie_target=? WHERE id=?
        """, values)
        connection.commit()
    except Exception as error:
        connection.rollback()
        flash(f"保存失败：{error}", "error")
        return redirect(url_for("user_detail", user_id=user_id))

    audit("编辑用户与健康档案", "user", user_id, f"用户：{nickname}")
    flash("用户信息和健康档案已保存。", "success")
    return redirect(url_for("user_detail", user_id=user_id))


@app.route("/users/<int:user_id>/status", methods=["POST"])
@admin_required
def toggle_user_status(user_id):
    connection = udb()
    user = connection.execute("SELECT id,nickname,active FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        abort(404)
    active = 0 if user["active"] else 1
    connection.execute("UPDATE users SET active=? WHERE id=?", (active, user_id))
    connection.commit()
    action = "启用用户账号" if active else "禁用用户账号"
    audit(action, "user", user_id, f"用户：{user['nickname']}")
    flash(f"账号已{'启用' if active else '禁用'}。", "success")
    return redirect(request.referrer or url_for("users"))


@app.route("/users/<int:user_id>/unbind", methods=["POST"])
@admin_required
def admin_unbind(user_id):
    connection = udb()
    user = connection.execute("SELECT id,nickname,bound_to FROM users WHERE id=?", (user_id,)).fetchone()
    if not user or not user["bound_to"]:
        flash("该用户当前没有监督关系", "warning")
    else:
        connection.execute("UPDATE users SET bound_to=NULL WHERE id=?", (user_id,))
        connection.commit()
        audit("解除监督关系", "user", user_id, f"用户：{user['nickname']}")
        flash("监督关系已解除", "success")
    return redirect(request.referrer or url_for("users"))


@app.route("/users/<int:user_id>/regenerate-code", methods=["POST"])
@admin_required
def regenerate_code(user_id):
    connection = udb()
    user = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        abort(404)
    column = "supervisor_code" if user["role"] == "supervisor" else "supervisee_code"
    while True:
        code = generate_bind_code()
        if not connection.execute(f"SELECT 1 FROM users WHERE {column}=?", (code,)).fetchone():
            break
    connection.execute(f"UPDATE users SET {column}=? WHERE id=?", (code, user_id))
    connection.commit()
    audit("重置绑定码", "user", user_id, f"用户：{user['nickname']}")
    flash(f"新绑定码：{code}", "success")
    return redirect(url_for("user_detail", user_id=user_id))


@app.route("/bindings")
@admin_required
def bindings():
    rows = udb().execute("""
        SELECT sub.id,sub.nickname,sub.phone,sub.supervisee_code,sub.bound_to,
               sup.nickname AS supervisor_name,sup.phone AS supervisor_phone
        FROM users sub LEFT JOIN users sup ON sup.id=sub.bound_to
        WHERE sub.role='supervisee' ORDER BY sub.bound_to IS NULL DESC,sub.nickname
    """).fetchall()
    return render_template("bindings.html", bindings=rows)


@app.route("/diets")
@admin_required
def diets():
    query = request.args.get("q", "").strip()
    sql = """
        SELECT u.id,u.nickname,u.phone,u.active,u.health_goal,u.risk_level,u.daily_calorie_target,
               COUNT(dr.id) AS record_count,MAX(dr.intake_time) AS latest_intake,
               COALESCE(SUM(CASE WHEN dr.intake_time>=datetime('now','-30 days') THEN dr.calories ELSE 0 END),0) AS calories_30d
        FROM users u LEFT JOIN diet_records dr ON dr.user_id=u.id WHERE 1=1
    """
    params = []
    if query:
        pattern = f"%{query}%"
        sql += " AND (u.nickname LIKE ? OR u.phone LIKE ?)"
        params.extend([pattern, pattern])
    sql += " GROUP BY u.id ORDER BY latest_intake IS NULL,latest_intake DESC,u.id DESC"
    users = udb().execute(sql, params).fetchall()
    return render_template("diets.html", users=users, query=query)


@app.route("/diets/users/<int:user_id>")
@admin_required
def user_diets(user_id):
    connection = udb()
    user = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        abort(404)
    date = request.args.get("date", "").strip()
    record_sql = "SELECT * FROM diet_records WHERE user_id=?"
    params = [user_id]
    if date:
        record_sql += " AND date(intake_time)=?"
        params.append(date)
    record_sql += " ORDER BY intake_time DESC LIMIT 500"
    records = connection.execute(record_sql, params).fetchall()
    daily_rows = connection.execute("""
        SELECT date(intake_time) AS day,COUNT(*) AS record_count,
               COALESCE(SUM(calories),0) AS calories,COALESCE(SUM(protein_g),0) AS protein,
               COALESCE(SUM(fat_g),0) AS fat,COALESCE(SUM(carbs_g),0) AS carbs,
               COALESCE(SUM(fiber_g),0) AS fiber
        FROM diet_records WHERE user_id=? AND intake_time>=date('now','-29 days')
        GROUP BY date(intake_time) ORDER BY day
    """, (user_id,)).fetchall()
    daily_map = {row["day"]: row for row in daily_rows}
    target = float(user["daily_calorie_target"] or 2000)
    start_day = datetime.now().date() - timedelta(days=29)
    trend = []
    for offset in range(30):
        day = start_day + timedelta(days=offset)
        key = day.isoformat()
        row = daily_map.get(key)
        calories = float(row["calories"] if row else 0)
        trend.append({
            "day": key,
            "label": day.strftime("%m-%d"),
            "calories": calories,
            "record_count": int(row["record_count"] if row else 0),
            "status": "hit" if target * 0.9 <= calories <= target * 1.1 else ("high" if calories > target * 1.1 else "low"),
        })
    logged_days = len(daily_rows)
    target_days = sum(1 for row in daily_rows if target * 0.9 <= row["calories"] <= target * 1.1)
    stats = {
        "records": sum(row["record_count"] for row in daily_rows),
        "calories": sum(row["calories"] for row in daily_rows),
        "protein": sum(row["protein"] for row in daily_rows),
        "fat": sum(row["fat"] for row in daily_rows),
        "carbs": sum(row["carbs"] for row in daily_rows),
        "fiber": sum(row["fiber"] for row in daily_rows),
        "plan_rate": logged_days / 30 * 100,
        "target_rate": target_days / logged_days * 100 if logged_days else 0,
        "target": target,
    }
    maximum = max([item["calories"] for item in trend] + [target, 1])
    return render_template(
        "user_diets.html", user=user, records=records, date=date, stats=stats, trend=trend, maximum=maximum,
    )


@app.route("/diets/<int:record_id>", methods=["GET", "POST"])
@admin_required
def diet_detail(record_id):
    connection = udb()
    record = connection.execute(
        "SELECT dr.*,u.nickname,u.phone FROM diet_records dr JOIN users u ON u.id=dr.user_id WHERE dr.id=?",
        (record_id,),
    ).fetchone()
    if not record:
        abort(404)

    if request.method == "POST":
        food_name = request.form.get("food_name", "").strip()
        meal_type = request.form.get("meal_type", "").strip()
        intake_time = request.form.get("intake_time", "").strip().replace("T", " ")
        description = request.form.get("description", "").strip()
        image_url = request.form.get("image_url", "").strip()
        try:
            weight = float(request.form.get("weight_grams", ""))
        except ValueError:
            flash("克重必须是有效数字。", "error")
            return redirect(url_for("diet_detail", record_id=record_id))
        if not food_name or not 0 < weight <= 5000:
            flash("请选择食物并填写 0–5000g 的有效克重。", "error")
            return redirect(url_for("diet_detail", record_id=record_id))
        if meal_type not in ("", "breakfast", "lunch", "dinner", "snack"):
            flash("餐次选项无效。", "error")
            return redirect(url_for("diet_detail", record_id=record_id))
        food = connection.execute("SELECT * FROM food_library WHERE name=?", (food_name,)).fetchone()
        if not food:
            flash("食物库中不存在该食物。", "error")
            return redirect(url_for("diet_detail", record_id=record_id))
        factor = weight / 100.0
        calories = round(food["calories_per_100g"] * factor, 1)
        protein = round(food["protein_g"] * factor, 1)
        fat = round(food["fat_g"] * factor, 1)
        carbs = round(food["carbs_g"] * factor, 1)
        fiber = round(food["fiber_g"] * factor, 1)
        connection.execute("""
            UPDATE diet_records SET food_name=?,weight_grams=?,calories=?,protein_g=?,fat_g=?,carbs_g=?,fiber_g=?,
                meal_type=?,description=?,image_url=?,intake_time=?,corrected_at=CURRENT_TIMESTAMP WHERE id=?
        """, (food_name, weight, calories, protein, fat, carbs, fiber, meal_type, description, image_url,
              intake_time or record["intake_time"], record_id))
        connection.commit()
        audit("编辑饮食记录", "diet_record", record_id, f"{food_name} / {weight}g")
        flash("饮食记录已更新。", "success")
        return redirect(url_for("diet_detail", record_id=record_id))

    foods = connection.execute("SELECT * FROM food_library WHERE active=1 ORDER BY category,name").fetchall()
    return render_template("diet_detail.html", record=record, foods=foods)


@app.route("/diets/<int:record_id>/delete", methods=["POST"])
@admin_required
def delete_diet(record_id):
    connection = udb()
    record = connection.execute("SELECT * FROM diet_records WHERE id=?", (record_id,)).fetchone()
    if not record:
        abort(404)
    connection.execute("DELETE FROM diet_records WHERE id=?", (record_id,))
    connection.commit()
    audit("删除饮食记录", "diet_record", record_id, f"{record['food_name']} / {record['calories']} kcal")
    flash("饮食记录已删除", "success")
    return redirect(request.referrer or url_for("diets"))


@app.route("/foods-legacy", methods=["GET", "POST"])
@admin_required
def foods_legacy():
    connection = udb()
    if request.method == "POST":
        food_id = request.form.get("food_id", "").strip()
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        try:
            calories = float(request.form.get("calories", ""))
            sodium = float(request.form.get("sodium", "0") or 0)
            potassium = float(request.form.get("potassium", "0") or 0)
            calcium = float(request.form.get("calcium", "0") or 0)
            magnesium = float(request.form.get("magnesium", "0") or 0)
            iron = float(request.form.get("iron", "0") or 0)
        except ValueError:
            flash("营养数值格式不正确", "error")
            return redirect(url_for("foods"))
        if not name or not category or calories < 0 or any(v < 0 for v in (sodium, potassium, calcium, magnesium, iron)):
            flash("请填写有效的食物名称、分类和非负营养数值", "error")
            return redirect(url_for("foods"))
        values = (name, calories, category, sodium, potassium, calcium, magnesium, iron)
        try:
            if food_id:
                connection.execute(
                    "UPDATE food_library SET name=?,calories_per_100g=?,category=?,sodium_mg=?,potassium_mg=?,calcium_mg=?,magnesium_mg=?,iron_mg=? WHERE id=?",
                    values + (int(food_id),),
                )
                action = "修改食物"
            else:
                cursor = connection.execute(
                    "INSERT INTO food_library (name,calories_per_100g,category,sodium_mg,potassium_mg,calcium_mg,magnesium_mg,iron_mg) VALUES (?,?,?,?,?,?,?,?)",
                    values,
                )
                food_id = cursor.lastrowid
                action = "新增食物"
            connection.commit()
        except Exception as error:
            connection.rollback()
            flash(f"保存失败：{error}", "error")
            return redirect(url_for("foods"))
        audit(action, "food", food_id, name)
        flash("食物资料已保存", "success")
        return redirect(url_for("foods"))
    rows = [dict(row) for row in connection.execute("SELECT * FROM food_library ORDER BY category,name").fetchall()]
    return render_template("foods.html", foods=rows)


@app.route("/foods", methods=["GET", "POST"])
@admin_required
def foods():
    connection = udb()
    if request.method == "POST":
        food_id = request.form.get("food_id", "").strip()
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        unit = request.form.get("unit", "g").strip() or "g"
        substitutes = request.form.get("substitutes", "").strip()
        number_fields = ("calories", "protein", "fat", "carbs", "fiber", "sodium", "potassium", "calcium", "magnesium", "iron")
        try:
            numbers = {field: float(request.form.get(field, "0") or 0) for field in number_fields}
        except ValueError:
            flash("营养数据必须是有效数字。", "error")
            return redirect(url_for("foods"))
        if not name or not category or any(value < 0 for value in numbers.values()):
            flash("请填写食物名称、分类和非负营养数据。", "error")
            return redirect(url_for("foods"))
        values = (
            name, numbers["calories"], category, unit, numbers["protein"], numbers["fat"], numbers["carbs"],
            numbers["fiber"], substitutes, numbers["sodium"], numbers["potassium"], numbers["calcium"],
            numbers["magnesium"], numbers["iron"],
        )
        try:
            if food_id:
                connection.execute("""
                    UPDATE food_library SET name=?,calories_per_100g=?,category=?,unit=?,protein_g=?,fat_g=?,
                        carbs_g=?,fiber_g=?,substitutes=?,sodium_mg=?,potassium_mg=?,calcium_mg=?,magnesium_mg=?,iron_mg=?
                    WHERE id=?
                """, values + (int(food_id),))
                action = "编辑食物"
            else:
                cursor = connection.execute("""
                    INSERT INTO food_library
                    (name,calories_per_100g,category,unit,protein_g,fat_g,carbs_g,fiber_g,substitutes,
                     sodium_mg,potassium_mg,calcium_mg,magnesium_mg,iron_mg)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, values)
                food_id = cursor.lastrowid
                action = "新增食物"
            connection.commit()
        except Exception as error:
            connection.rollback()
            flash(f"保存失败：{error}", "error")
            return redirect(url_for("foods"))
        audit(action, "food", food_id, name)
        flash("食物资料已保存。", "success")
        return redirect(url_for("foods"))
    rows = [dict(row) for row in connection.execute("SELECT * FROM food_library ORDER BY active DESC,category,name")]
    return render_template("foods.html", foods=rows)


@app.route("/foods/<int:food_id>/status", methods=["POST"])
@admin_required
def toggle_food_status(food_id):
    connection = udb()
    food = connection.execute("SELECT id,name,active FROM food_library WHERE id=?", (food_id,)).fetchone()
    if not food:
        abort(404)
    active = 0 if food["active"] else 1
    connection.execute("UPDATE food_library SET active=? WHERE id=?", (active, food_id))
    connection.commit()
    audit("启用食物" if active else "停用食物", "food", food_id, food["name"])
    flash(f"食物已{'启用' if active else '停用'}。", "success")
    return redirect(url_for("foods"))


@app.route("/exports/foods.csv")
@admin_required
def export_foods():
    rows = udb().execute("""
        SELECT id,name,category,unit,calories_per_100g,protein_g,fat_g,carbs_g,fiber_g,
               sodium_mg,potassium_mg,calcium_mg,magnesium_mg,iron_mg,substitutes,active
        FROM food_library ORDER BY category,name
    """).fetchall()
    headers = ["ID","名称","分类","单位","热量/100g","蛋白质","脂肪","碳水","纤维","钠","钾","钙","镁","铁","替代品","启用"]
    return csv_download("foods.csv", headers, [tuple(row) for row in rows])


@app.route("/recipes", methods=["GET", "POST"])
@admin_required
def recipes():
    connection = udb()
    if request.method == "POST":
        recipe_id = request.form.get("recipe_id", "").strip()
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        try:
            servings = int(request.form.get("servings", "1") or 1)
            calories = float(request.form.get("calories", "0") or 0)
            protein = float(request.form.get("protein", "0") or 0)
            fat = float(request.form.get("fat", "0") or 0)
            carbs = float(request.form.get("carbs", "0") or 0)
            fiber = float(request.form.get("fiber", "0") or 0)
        except ValueError:
            flash("份数和营养数据必须是有效数字。", "error")
            return redirect(url_for("recipes"))
        if not name or servings < 1 or any(v < 0 for v in (calories, protein, fat, carbs, fiber)):
            flash("请填写菜谱名称、有效份数和非负营养数据。", "error")
            return redirect(url_for("recipes"))
        values = (
            name, category, request.form.get("description", "").strip(),
            request.form.get("instructions", "").strip(), servings, calories, protein, fat, carbs, fiber,
            request.form.get("suitable_for", "").strip(), request.form.get("avoid_for", "").strip(),
            request.form.get("image_url", "").strip(),
        )
        try:
            if recipe_id:
                connection.execute("""
                    UPDATE recipes SET name=?,category=?,description=?,instructions=?,servings=?,calories_per_serving=?,
                        protein_g=?,fat_g=?,carbs_g=?,fiber_g=?,suitable_for=?,avoid_for=?,image_url=?,
                        updated_at=CURRENT_TIMESTAMP WHERE id=?
                """, values + (int(recipe_id),))
                rid = int(recipe_id)
                connection.execute("DELETE FROM recipe_ingredients WHERE recipe_id=?", (rid,))
                action = "编辑菜谱"
            else:
                cursor = connection.execute("""
                    INSERT INTO recipes
                    (name,category,description,instructions,servings,calories_per_serving,protein_g,fat_g,carbs_g,
                     fiber_g,suitable_for,avoid_for,image_url) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, values)
                rid = cursor.lastrowid
                action = "新增菜谱"
            for line in request.form.get("ingredients", "").splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = [part.strip() for part in line.split("|")]
                ingredient_name = parts[0]
                amount = float(parts[1]) if len(parts) > 1 and parts[1] else 0
                unit = parts[2] if len(parts) > 2 and parts[2] else "g"
                notes = parts[3] if len(parts) > 3 else ""
                food = connection.execute("SELECT id FROM food_library WHERE name=?", (ingredient_name,)).fetchone()
                connection.execute(
                    "INSERT INTO recipe_ingredients (recipe_id,food_id,ingredient_name,amount,unit,notes) VALUES (?,?,?,?,?,?)",
                    (rid, food["id"] if food else None, ingredient_name, amount, unit, notes),
                )
            connection.commit()
        except Exception as error:
            connection.rollback()
            flash(f"保存失败：{error}", "error")
            return redirect(url_for("recipes"))
        audit(action, "recipe", rid, name)
        flash("菜谱已保存。", "success")
        return redirect(url_for("recipes"))

    rows = [dict(row) for row in connection.execute("SELECT * FROM recipes ORDER BY active DESC,updated_at DESC,name")]
    for row in rows:
        ingredients = connection.execute(
            "SELECT ingredient_name,amount,unit,notes FROM recipe_ingredients WHERE recipe_id=? ORDER BY id", (row["id"],)
        ).fetchall()
        row["ingredients_text"] = "\n".join(
            f"{item['ingredient_name']}|{item['amount']}|{item['unit']}|{item['notes']}" for item in ingredients
        )
    return render_template("recipes.html", recipes=rows)


@app.route("/recipes/<int:recipe_id>/status", methods=["POST"])
@admin_required
def toggle_recipe_status(recipe_id):
    connection = udb()
    recipe = connection.execute("SELECT id,name,active FROM recipes WHERE id=?", (recipe_id,)).fetchone()
    if not recipe:
        abort(404)
    active = 0 if recipe["active"] else 1
    connection.execute("UPDATE recipes SET active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (active, recipe_id))
    connection.commit()
    audit("发布菜谱" if active else "下架菜谱", "recipe", recipe_id, recipe["name"])
    flash(f"菜谱已{'发布' if active else '下架'}。", "success")
    return redirect(url_for("recipes"))


@app.route("/recipes/<int:recipe_id>/delete", methods=["POST"])
@admin_required
def delete_recipe(recipe_id):
    connection = udb()
    recipe = connection.execute("SELECT id,name FROM recipes WHERE id=?", (recipe_id,)).fetchone()
    if not recipe:
        abort(404)
    connection.execute("DELETE FROM recipes WHERE id=?", (recipe_id,))
    connection.commit()
    audit("删除菜谱", "recipe", recipe_id, recipe["name"])
    flash("菜谱已删除。", "success")
    return redirect(url_for("recipes"))


@app.route("/exports/recipes.csv")
@admin_required
def export_recipes():
    rows = udb().execute("""
        SELECT id,name,category,servings,calories_per_serving,protein_g,fat_g,carbs_g,fiber_g,
               suitable_for,avoid_for,active,updated_at FROM recipes ORDER BY name
    """).fetchall()
    headers = ["ID","菜谱","分类","份数","每份热量","蛋白质","脂肪","碳水","纤维","适合人群","不适合人群","发布","更新时间"]
    return csv_download("recipes.csv", headers, [tuple(row) for row in rows])


@app.route("/feedback", methods=["GET", "POST"])
@admin_required
def feedback():
    connection = udb()
    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        content = request.form.get("content", "").strip()
        category = request.form.get("category", "feedback").strip()
        priority = request.form.get("priority", "normal").strip()
        user_id = request.form.get("user_id", "").strip()
        if not subject or not content:
            flash("主题和内容不能为空。", "error")
            return redirect(url_for("feedback"))
        if category not in ("feedback", "consultation", "complaint", "account", "technical"):
            category = "feedback"
        if priority not in ("low", "normal", "high", "urgent"):
            priority = "normal"
        connection.execute("""
            INSERT INTO feedback_tickets (user_id,category,subject,content,contact,priority)
            VALUES (?,?,?,?,?,?)
        """, (int(user_id) if user_id else None, category, subject, content,
              request.form.get("contact", "").strip(), priority))
        ticket_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        connection.commit()
        audit("创建反馈工单", "feedback", ticket_id, subject)
        flash("反馈工单已创建。", "success")
        return redirect(url_for("feedback"))

    status = request.args.get("status", "").strip()
    category = request.args.get("category", "").strip()
    query = request.args.get("q", "").strip()
    sql = """
        SELECT f.*,u.nickname,u.phone FROM feedback_tickets f
        LEFT JOIN users u ON u.id=f.user_id WHERE 1=1
    """
    params = []
    if status in ("open", "processing", "resolved", "closed"):
        sql += " AND f.status=?"
        params.append(status)
    if category in ("feedback", "consultation", "complaint", "account", "technical"):
        sql += " AND f.category=?"
        params.append(category)
    if query:
        pattern = f"%{query}%"
        sql += " AND (f.subject LIKE ? OR f.content LIKE ? OR COALESCE(u.nickname,'') LIKE ? OR COALESCE(u.phone,'') LIKE ?)"
        params.extend([pattern, pattern, pattern, pattern])
    sql += " ORDER BY CASE f.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,f.created_at DESC"
    tickets = connection.execute(sql, params).fetchall()
    users = connection.execute("SELECT id,nickname,phone FROM users ORDER BY nickname").fetchall()
    return render_template("feedback.html", tickets=tickets, users=users, status=status, category=category, query=query)


@app.route("/feedback/<int:ticket_id>/update", methods=["POST"])
@admin_required
def update_feedback(ticket_id):
    connection = udb()
    ticket = connection.execute("SELECT * FROM feedback_tickets WHERE id=?", (ticket_id,)).fetchone()
    if not ticket:
        abort(404)
    status = request.form.get("status", "open").strip()
    priority = request.form.get("priority", "normal").strip()
    if status not in ("open", "processing", "resolved", "closed"):
        status = "open"
    if priority not in ("low", "normal", "high", "urgent"):
        priority = "normal"
    resolved = "CURRENT_TIMESTAMP" if status in ("resolved", "closed") else "NULL"
    connection.execute(f"""
        UPDATE feedback_tickets SET status=?,priority=?,admin_reply=?,updated_at=CURRENT_TIMESTAMP,
            resolved_at={resolved} WHERE id=?
    """, (status, priority, request.form.get("admin_reply", "").strip(), ticket_id))
    connection.commit()
    audit("处理反馈工单", "feedback", ticket_id, f"状态：{status}")
    flash("工单处理结果已保存。", "success")
    return redirect(url_for("feedback"))


@app.route("/exports/feedback.csv")
@admin_required
def export_feedback():
    rows = udb().execute("""
        SELECT f.id,u.nickname,u.phone,f.category,f.subject,f.content,f.contact,f.status,f.priority,
               f.admin_reply,f.created_at,f.updated_at,f.resolved_at
        FROM feedback_tickets f LEFT JOIN users u ON u.id=f.user_id ORDER BY f.created_at DESC
    """).fetchall()
    headers = ["ID","用户","手机号","分类","主题","内容","联系方式","状态","优先级","回复","创建时间","更新时间","完成时间"]
    return csv_download("feedback.csv", headers, [tuple(row) for row in rows])


def database_backup(source_path, destination_path):
    source = sqlite3.connect(source_path, timeout=10)
    destination = sqlite3.connect(destination_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()


@app.route("/system")
@admin_required
def system_page():
    connection = udb()
    tables = {}
    for table in ("users", "diet_records", "food_library", "recipes", "feedback_tickets"):
        tables[table] = connection.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
    backups = []
    if os.path.isdir(BACKUP_DIR):
        for name in sorted(os.listdir(BACKUP_DIR), reverse=True)[:30]:
            path = os.path.join(BACKUP_DIR, name)
            if os.path.isfile(path):
                backups.append({"name": name, "size": os.path.getsize(path), "modified": datetime.fromtimestamp(os.path.getmtime(path))})
    info = {
        "python": sys.version.split()[0],
        "uptime_minutes": round((time.time() - STARTED_AT) / 60, 1),
        "user_db_size": os.path.getsize(USER_DB_PATH) if os.path.isfile(USER_DB_PATH) else 0,
        "admin_db_size": os.path.getsize(ADMIN_DB_PATH) if os.path.isfile(ADMIN_DB_PATH) else 0,
        "user_db_path": USER_DB_PATH,
        "admin_db_path": ADMIN_DB_PATH,
    }
    return render_template("system.html", info=info, tables=tables, backups=backups)


@app.route("/system/backup", methods=["POST"])
@admin_required
def create_backup():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    user_target = os.path.join(BACKUP_DIR, f"health-{stamp}.db")
    admin_target = os.path.join(BACKUP_DIR, f"admin-{stamp}.db")
    try:
        database_backup(USER_DB_PATH, user_target)
        database_backup(ADMIN_DB_PATH, admin_target)
    except Exception as error:
        for path in (user_target, admin_target):
            if os.path.exists(path):
                os.remove(path)
        flash(f"备份失败：{error}", "error")
        return redirect(url_for("system_page"))
    audit("创建系统备份", "system", stamp, "用户数据库与管理数据库")
    flash("数据库备份已创建。", "success")
    return redirect(url_for("system_page"))


@app.route("/audit")
@admin_required
def audit_page():
    rows = adb().execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 500").fetchall()
    return render_template("audit.html", logs=rows)


@app.errorhandler(FileNotFoundError)
def missing_user_database(error):
    return render_template("database_error.html", message=str(error)), 503


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5100, debug=False, use_reloader=False)
