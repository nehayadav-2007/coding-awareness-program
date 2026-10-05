from datetime import date, timedelta
import secrets
from functools import wraps
from flask import Blueprint, render_template, request, redirect, session, flash, abort, g
from markupsafe import Markup
from mysql.connector import Error
from werkzeug.security import generate_password_hash as H, check_password_hash as C
from db import get_db

admin_bp = Blueprint("admin", __name__)
ROLES = {"admin": ["dash", "lessons", "quiz", "users", "admins", "plans", "settings"],
         "editor": ["dash", "lessons", "quiz", "settings"],
         "support": ["dash", "users", "plans", "settings"]}
ROLENAME = {"admin": "Super admin (full access)", "editor": "Content editor (lessons, quiz)", "support": "Support (users, plans)"}
NAV = {"dash": ("Dashboard", "/admin"), "lessons": ("Lessons", "/admin/content/lessons"), "quiz": ("Quiz questions", "/admin/content/quiz_questions"),
       "users": ("Students", "/admin/users"), "admins": ("Admins", "/admin/admins"), "plans": ("Plans", "/admin/plans"), "settings": ("Settings", "/admin/settings")}
TABLES = {"lessons": "lessons", "quiz_questions": "quiz"}

def q(sql, a=(), one=False, write=False):
    db = get_db(); cur = db.cursor(dictionary=True)
    try:
        cur.execute(sql, a)
        if write: db.commit(); return cur.lastrowid
        return cur.fetchone() if one else cur.fetchall()
    finally:
        cur.close(); db.close()

# ---------- used by the student side of your site (app.py) ----------
def user_blocked(user):
    return user.get("status", "active") != "active"

def lesson_allowed(user_id, lesson):
    u = q("SELECT status,plan_id,plan_expires FROM users WHERE id=%s", (user_id,), one=True)
    if not u or u["status"] != "active": return False
    rk = lambda pid: (q("SELECT rank_no FROM plans WHERE id=%s", (pid,), one=True) or {"rank_no": 0})["rank_no"]
    mine = rk(u["plan_id"])
    if u["plan_expires"] and u["plan_expires"] < date.today():
        mine = q("SELECT MIN(rank_no) m FROM plans", one=True)["m"] or 0
    return mine >= rk(lesson.get("plan_id"))

# ---------- admin helpers ----------
@admin_bp.before_request
def csrf_check():
    session.setdefault("_t", secrets.token_hex(16))
    if request.method == "POST" and request.path.startswith("/admin") and request.form.get("_t") != session["_t"]: abort(400)

@admin_bp.app_context_processor
def inject():
    return dict(csrf=lambda: Markup('<input type="hidden" name="_t" value="%s">' % session.get("_t", "")))

def need(page):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if "user_id" not in session: return redirect("/login")
            me = q("SELECT * FROM users WHERE id=%s", (session["user_id"],), one=True)
            if not me or me["role"] not in ROLES or me.get("status", "active") != "active": abort(403)
            if page and page not in ROLES[me["role"]]: abort(403)
            g.me = me
            return f(*a, **k)
        return w
    return deco

def apage(name, **kw):
    return render_template("admin/panel.html", page=name, me=g.me, tabs=[(k,) + NAV[k] for k in ROLES[g.me["role"]]], ROLENAME=ROLENAME, NAV=NAV,
                           plans=q("SELECT * FROM plans ORDER BY rank_no"), **kw)

def editable(table):
    out = []
    for c in q("SHOW COLUMNS FROM `%s`" % table):
        ex, d, t = (c["Extra"] or "").lower(), str(c["Default"] or "").upper(), c["Type"].lower()
        if "auto_increment" in ex or "generated" in ex or "CURRENT_TIMESTAMP" in d: continue
        out.append(dict(name=c["Field"], textarea="text" in t, number="int" in t, is_plan=c["Field"] == "plan_id"))
    return out

# ---------- dashboard ----------
@admin_bp.route("/admin")
@need("dash")
def dash():
    n = lambda sql: q(sql, one=True)["n"]
    by = q("""SELECT p.name,(SELECT COUNT(*) FROM users WHERE plan_id=p.id AND role='student') u,
              (SELECT COUNT(*) FROM lessons WHERE plan_id=p.id) l FROM plans p ORDER BY rank_no""")
    return apage("dash", students=n("SELECT COUNT(*) n FROM users WHERE role='student'"), lessons=n("SELECT COUNT(*) n FROM lessons"),
                 questions=n("SELECT COUNT(*) n FROM quiz_questions"), attempts=n("SELECT COUNT(*) n FROM quiz_results"), by=by,
                 newest=q("SELECT name,email FROM users WHERE role='student' ORDER BY id DESC LIMIT 5"))

# ---------- lessons and quiz questions (works with whatever columns your tables have) ----------
@admin_bp.route("/admin/content/<table>")
@need("")
def content(table):
    if table not in TABLES or TABLES[table] not in ROLES[g.me["role"]]: abort(403)
    cols = editable(table)
    edit = q("SELECT * FROM `%s` WHERE id=%%s" % table, (request.args.get("edit", 0),), one=True)
    rows = q("SELECT * FROM `%s` ORDER BY id" % table)
    pmap = {p["id"]: p["name"] for p in q("SELECT id,name FROM plans")}
    return apage(TABLES[table], table=table, cols=cols, edit=edit, rows=rows, show=[c["name"] for c in cols][:4], pmap=pmap)

@admin_bp.post("/admin/content/<table>/save")
@need("")
def content_save(table):
    if table not in TABLES or TABLES[table] not in ROLES[g.me["role"]]: abort(403)
    f, cols = request.form, editable(table)
    vals = [None if (c["number"] and f.get(c["name"], "") == "") else f.get(c["name"], "") for c in cols]
    names = ",".join("`%s`" % c["name"] for c in cols)
    try:
        if f.get("id"):
            q("UPDATE `%s` SET %s WHERE id=%%s" % (table, ",".join("`%s`=%%s" % c["name"] for c in cols)), vals + [f["id"]], write=True)
        else:
            q("INSERT INTO `%s`(%s) VALUES(%s)" % (table, names, ",".join(["%s"] * len(cols))), vals, write=True)
        flash("Saved")
    except Error as e:
        flash("Could not save: %s" % e.msg)
    return redirect("/admin/content/" + table)

@admin_bp.post("/admin/content/<table>/<int:i>/delete")
@need("")
def content_delete(table, i):
    if table not in TABLES or TABLES[table] not in ROLES[g.me["role"]]: abort(403)
    if table == "lessons": q("DELETE FROM progress WHERE lesson_id=%s", (i,), write=True)
    q("DELETE FROM `%s` WHERE id=%%s" % table, (i,), write=True)
    flash("Deleted"); return redirect("/admin/content/" + table)

# ---------- students ----------
@admin_bp.route("/admin/users")
@need("users")
def users():
    s = request.args.get("s", "")
    rows = q("""SELECT u.id,u.name,u.email,u.status,u.plan_id,u.plan_expires,
                (SELECT COUNT(*) FROM progress WHERE user_id=u.id AND status='completed') done,
                (SELECT COALESCE(SUM(score),0) FROM quiz_results WHERE user_id=u.id) points
                FROM users u WHERE u.role='student' AND CONCAT(u.name,' ',u.email) LIKE %s ORDER BY u.id DESC""", ("%" + s + "%",))
    return apage("users", rows=rows, s=s, total=q("SELECT COUNT(*) n FROM lessons", one=True)["n"])

@admin_bp.post("/admin/users/<int:i>/<act>")
@need("users")
def user_act(i, act):
    f = request.form
    if act == "update": q("UPDATE users SET plan_id=%s,plan_expires=%s WHERE id=%s AND role='student'", (f["plan_id"], f["expires"] or None, i), write=True)
    elif act == "toggle": q("UPDATE users SET status=IF(status='active','blocked','active') WHERE id=%s AND role='student'", (i,), write=True)
    elif act == "password" and len(f["password"]) >= 6: q("UPDATE users SET password=%s WHERE id=%s AND role='student'", (H(f["password"]), i), write=True)
    elif act == "delete":
        for t in ("progress", "quiz_results"): q("DELETE FROM %s WHERE user_id=%%s" % t, (i,), write=True)
        q("DELETE FROM users WHERE id=%s AND role='student'", (i,), write=True)
    else: abort(404)
    flash("Done"); return redirect("/admin/users")

# ---------- admins ----------
@admin_bp.route("/admin/admins")
@need("admins")
def admins():
    return apage("admins", rows=q("SELECT id,name,email,role FROM users WHERE role<>'student' ORDER BY id"))

@admin_bp.post("/admin/admins/<act>")
@need("admins")
def admin_act(act):
    f = request.form; i = f.get("id")
    if act == "add":
        email = f["email"].strip().lower()
        if len(f["password"]) < 6 or f["role"] not in ROLES or q("SELECT 1 FROM users WHERE email=%s", (email,), one=True):
            flash("Need a new email, a role and a password of 6+ characters.")
        else: q("INSERT INTO users(name,email,password,role) VALUES(%s,%s,%s,%s)", (f["name"].strip() or "Admin", email, H(f["password"]), f["role"]), write=True)
    elif str(g.me["id"]) == i and act in ("role", "delete"): flash("You cannot change or remove your own account.")
    elif act == "role" and f["role"] in ROLES: q("UPDATE users SET role=%s WHERE id=%s", (f["role"], i), write=True)
    elif act == "password" and len(f["password"]) >= 6: q("UPDATE users SET password=%s WHERE id=%s", (H(f["password"]), i), write=True)
    elif act == "demote": q("UPDATE users SET role='student' WHERE id=%s", (i,), write=True)
    return redirect("/admin/admins")

# ---------- plans ----------
@admin_bp.route("/admin/plans")
@need("plans")
def plans_admin():
    return apage("plans", can_edit=g.me["role"] == "admin")

@admin_bp.post("/admin/plans/<act>")
@need("admins")
def plan_act(act):
    f = request.form
    try:
        if act == "add": q("INSERT INTO plans(name,price,rank_no) VALUES(%s,%s,%s)", (f["name"].strip(), f["price"] or 0, f["rank_no"]), write=True)
        elif act == "update": q("UPDATE plans SET name=%s,price=%s,rank_no=%s WHERE id=%s", (f["name"].strip(), f["price"] or 0, f["rank_no"], f["id"]), write=True)
        elif act == "delete":
            low = q("SELECT id FROM plans WHERE id<>%s ORDER BY rank_no LIMIT 1", (f["id"],), one=True)
            if not low: flash("Keep at least one plan.")
            else:
                for t in ("users", "lessons"): q("UPDATE %s SET plan_id=%%s WHERE plan_id=%%s" % t, (low["id"], f["id"]), write=True)
                q("DELETE FROM plans WHERE id=%s", (f["id"],), write=True)
    except Error as e: flash("Could not save: %s" % e.msg)
    return redirect("/admin/plans")

# ---------- settings ----------
@admin_bp.route("/admin/settings", methods=["GET", "POST"])
@need("settings")
def settings():
    if request.method == "POST":
        f = request.form
        if not C(g.me["password"], f["old"]) or len(f["new"]) < 6: flash("Current password is wrong, or the new one is under 6 characters.")
        else: q("UPDATE users SET password=%s WHERE id=%s", (H(f["new"]), g.me["id"]), write=True); flash("Password updated")
        return redirect("/admin/settings")
    return apage("settings")

# ---------- student side: choose a plan (demo checkout, no real payment) ----------
@admin_bp.route("/plans")
def plans_page():
    if "user_id" not in session: return redirect("/login")
    u = q("SELECT plan_id,plan_expires FROM users WHERE id=%s", (session["user_id"],), one=True)
    rows = q("SELECT p.*,(SELECT COUNT(*) FROM lessons WHERE plan_id=p.id) n FROM plans p ORDER BY rank_no")
    session.setdefault("_t", secrets.token_hex(16))
    return render_template("plans.html", rows=rows, u=u, t=session["_t"])

@admin_bp.post("/plans/choose/<int:pid>")
def plans_choose(pid):
    if "user_id" not in session or request.form.get("_t") != session.get("_t"): abort(400)
    p = q("SELECT * FROM plans WHERE id=%s", (pid,), one=True) or abort(404)
    low = q("SELECT MIN(rank_no) m FROM plans", one=True)["m"]
    exp = None if p["rank_no"] == low else date.today() + timedelta(days=30)
    q("UPDATE users SET plan_id=%s,plan_expires=%s WHERE id=%s", (pid, exp, session["user_id"]), write=True)
    return redirect("/plans?changed=" + p["name"])
