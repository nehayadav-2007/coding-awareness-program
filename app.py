from flask import Flask, render_template, request, redirect, url_for, session, flash
from mysql.connector import Error
from werkzeug.security import generate_password_hash, check_password_hash

from db import get_db
from admin import admin_bp, lesson_allowed, user_blocked, ROLES

app = Flask(__name__)
app.secret_key = "codebuddy-dev-secret-change-me"
app.register_blueprint(admin_bp)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if not name or not email or not password:
            flash("Please fill all fields.")
            return redirect(url_for("register"))

        db = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            cur.close(); db.close()
            flash("Email already registered.")
            return redirect(url_for("register"))

        hashed = generate_password_hash(password)
        cur.execute("INSERT INTO users (name,email,password,role,plan_id) VALUES (%s,%s,%s,'student',(SELECT id FROM plans ORDER BY rank_no LIMIT 1))",
                    (name, email, hashed))
        db.commit()
        cur.close(); db.close()
        flash("Registration successful. Please login.")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        db = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cur.fetchone()
        cur.close(); db.close()

        if user and check_password_hash(user["password"], password):
            if user_blocked(user):
                flash("This account is blocked. Please contact support.")
                return redirect(url_for("login"))
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["role"] = user["role"]
            if user["role"] in ROLES:          # admin, editor or support -> admin panel
                return redirect("/admin")
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.")
    return render_template("login.html")

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form["email"].strip().lower()

        db = get_db()
        cur = db.cursor(dictionary=True)

        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        user = cur.fetchone()

        if not user:
            cur.close()
            db.close()
            flash("Email not found.")
            return redirect(url_for("forgot_password"))

        cur.close()
        db.close()

        session["reset_email"] = email
        return redirect(url_for("reset_password"))

    return render_template("forgot_password.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if "reset_email" not in session:
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        if password != confirm_password:
            flash("Passwords do not match.")
            return redirect(url_for("reset_password"))

        hashed_password = generate_password_hash(password)

        db = get_db()
        cur = db.cursor()

        cur.execute(
            "UPDATE users SET password=%s WHERE email=%s",
            (hashed_password, session["reset_email"])
        )

        db.commit()
        cur.close()
        db.close()

        session.pop("reset_email", None)

        flash("Password changed successfully. Please login.")
        return redirect(url_for("login"))

    return render_template("reset_password.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT COUNT(*) AS total FROM lessons")
    total_lessons = cur.fetchone()["total"]
    cur.execute("SELECT COUNT(*) AS completed FROM progress WHERE user_id=%s AND status='completed'",
                (session["user_id"],))
    completed = cur.fetchone()["completed"]
    cur.execute("SELECT COALESCE(SUM(score),0) AS points FROM quiz_results WHERE user_id=%s",
                (session["user_id"],))
    points = cur.fetchone()["points"]
    cur.close(); db.close()

    return render_template("dashboard.html", total_lessons=total_lessons,
                           completed=completed, points=points)

@app.route("/lessons")
def lessons():
    if "user_id" not in session:
        return redirect(url_for("login"))
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT l.*, COALESCE(p.status,'not_started') AS status
        FROM lessons l
        LEFT JOIN progress p ON l.id=p.lesson_id AND p.user_id=%s
        ORDER BY l.id
    """, (session["user_id"],))
    data = cur.fetchall()
    cur.close(); db.close()
    for l in data:                      # lets lessons.html show a lock: {% if l.locked %}
        l["locked"] = not lesson_allowed(session["user_id"], l)
    return render_template("lessons.html", lessons=data)

@app.route("/lesson/<int:lesson_id>", methods=["GET", "POST"])
def lesson(lesson_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM lessons WHERE id=%s", (lesson_id,))
    item = cur.fetchone()

    if not item:
        cur.close(); db.close()
        return "Lesson not found", 404

    if not lesson_allowed(session["user_id"], item):    # plan / blocked check
        cur.close(); db.close()
        return redirect("/plans?need=1")

    if request.method == "POST":
        cur.execute("""
            INSERT INTO progress(user_id, lesson_id, status)
            VALUES(%s,%s,'completed')
            ON DUPLICATE KEY UPDATE status='completed', completed_at=CURRENT_TIMESTAMP
        """, (session["user_id"], lesson_id))
        db.commit()
        cur.close(); db.close()
        return redirect(url_for("lessons"))

    cur.close(); db.close()
    return render_template("lesson.html", lesson=item)

@app.route("/quiz", methods=["GET", "POST"])
def quiz():
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM quiz_questions ORDER BY id")
    questions = cur.fetchall()

    if request.method == "POST":
        score = 0
        for q in questions:
            if request.form.get(f"q{q['id']}") == q["answer"]:
                score += 10

        cur.execute("INSERT INTO quiz_results(user_id,score,total_questions) VALUES(%s,%s,%s)",
                    (session["user_id"], score, len(questions)))
        db.commit()
        cur.close(); db.close()
        return render_template("result.html", score=score, total=len(questions)*10)

    cur.close(); db.close()
    return render_template("quiz.html", questions=questions)

@app.route("/progress")
def progress():
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT l.title, p.status, p.completed_at
        FROM progress p JOIN lessons l ON p.lesson_id=l.id
        WHERE p.user_id=%s ORDER BY l.id
    """, (session["user_id"],))
    lessons_data = cur.fetchall()
    cur.execute("""
        SELECT score,total_questions,attempted_at
        FROM quiz_results WHERE user_id=%s ORDER BY attempted_at DESC
    """, (session["user_id"],))
    quiz_data = cur.fetchall()
    cur.close(); db.close()
    return render_template("progress.html", lessons=lessons_data, quizzes=quiz_data)

if __name__ == "__main__":
    app.run(debug=True)
