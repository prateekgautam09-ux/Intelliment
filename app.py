from flask import Flask, render_template, request, redirect, flash, session
import mysql.connector
import os
from groq import Groq
import json
from flask_mail import Mail, Message
import random
import time


# ===============================
# FLASK SETUP
# ===============================
app = Flask(__name__)
app.secret_key = "secret123"

# ===============================
# MAIL CONFIG (OTP SYSTEM)
# ===============================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USERNAME'] = 'intelliment1@gmail.com'
app.config['MAIL_PASSWORD'] = 'uroqrgckcfgdgruo'
app.config['MAIL_DEFAULT_SENDER'] = 'intelliment1@gmail.com'

mail = Mail(app)


# ===============================
# AI CLIENT
# ===============================
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ===============================
# OTP GENERATOR
# ===============================
def generate_otp():
    return str(random.randint(100000, 999999))


# ===============================
# DATABASE
# ===============================
db = mysql.connector.connect( host="localhost", user="root", password="", database="ai_viva_examiner" )
# ===============================
# AI – VIVA QUESTION
# ===============================
def generate_ai_question(course, domain, difficulty):
    prompt = f"""
Ask ONE {difficulty} viva question for {course} student.
Domain: {domain}
Only question. No explanation.
"""
    response = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()

# ===============================
# AI – APTI MCQs
# ===============================

def generate_apti_mcqs(session_id, difficulty, quant, reasoning, verbal):

    sections = {
        "Quantitative Aptitude": quant,
        "Reasoning": reasoning,
        "Verbal Ability": verbal
    }

    cur = db.cursor()

    for section, count in sections.items():

        if count == 0:
            continue

        prompt = f"""
You are a professional exam question generator.

STRICT RULES:
1. Generate EXACTLY {count} questions.
2. Difficulty must be strictly {difficulty}.
3. Questions must belong ONLY to {section}.
4. Do NOT generate more or fewer than {count}.
5. Do NOT include explanations.
6. Return ONLY valid JSON array.

JSON format:
[
  {{
    "question": "text",
    "options": {{
      "A": "option",
      "B": "option",
      "C": "option",
      "D": "option"
    }},
    "answer": "A"
  }}
]
"""

        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = response.choices[0].message.content.strip()

        # 🔥 Extract only JSON
        start = raw.find("[")
        end = raw.rfind("]") + 1
        raw_json = raw[start:end]

        try:
            mcqs = json.loads(raw_json)
        except Exception as e:
            print("JSON Parse Error:", e)
            continue

        # 🔥 Force exact count
        mcqs = mcqs[:count]

        for mcq in mcqs:

            cur.execute("""
                INSERT INTO apti_questions
                (session_id, section, question,
                 option_a, option_b, option_c, option_d, correct_option)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                session_id,
                section,
                mcq["question"],
                mcq["options"]["A"],
                mcq["options"]["B"],
                mcq["options"]["C"],
                mcq["options"]["D"],
                mcq["answer"]
            ))

    db.commit()
    cur.close()

# ===============================
# HOME / REGISTER
# ===============================
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        account_type = request.form["account_type"]

        cur = db.cursor()
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        existing = cur.fetchone()
        cur.close()

        # 🔴 DUPLICATE EMAIL CHECK
        if existing:
            flash("⚠ Email already registered. Please login.")
            return redirect("/register")

        hashed_password = password

        otp = generate_otp()

        session["temp_user"] = {
            "name": name,
            "email": email,
            "password": hashed_password,
            "account_type": account_type
        }

        session["otp"] = otp
        session["otp_time"] = time.time()   # ⏳ expiry timer start

        try:
            msg = Message(
                "Your IntelliMent OTP Code",
                recipients=[email]
            )
            msg.body = f"""
Hello {name},

Your IntelliMent Registration OTP is:

{otp}

This OTP is valid for 5 minutes.
"""
            mail.send(msg)

            flash("📩 OTP sent to your email.")
            return redirect("/verify_otp")

        except Exception as e:
            print("Mail Error:", e)
            flash("⚠ Unable to send OTP.")
            return redirect("/register")

    return render_template("register.html")
# ===============================
# VERIFY OTP
# ===============================
@app.route("/verify_otp", methods=["GET", "POST"])
def verify_otp():

    if request.method == "POST":

        user_otp = request.form.get("otp")

        saved_otp = session.get("otp")
        otp_time = session.get("otp_time")
        temp_user = session.get("temp_user")

        # ❌ Session missing
        if not saved_otp or not otp_time or not temp_user:
            flash("⚠ Session expired. Please register again.")
            return redirect("/register")

        # ⏳ OTP Expiry (5 minutes = 300 sec)
        if time.time() - otp_time > 300:
            session.pop("otp", None)
            session.pop("temp_user", None)
            session.pop("otp_time", None)

            flash("⏳ OTP expired. Please register again.")
            return redirect("/register")

        # ❌ Wrong OTP
        if user_otp != saved_otp:
            flash("❌ Invalid OTP. Try again.")
            return redirect("/verify_otp")

        # ✅ Correct OTP → Save user (PLAIN PASSWORD)
        try:
            cur = db.cursor()
            cur.execute("""
                INSERT INTO users (name, email, password, account_type)
                VALUES (%s, %s, %s, %s)
            """, (
                temp_user["name"],
                temp_user["email"],
                temp_user["password"],   # plain password save hoga
                temp_user["account_type"]
            ))
            db.commit()
            cur.close()

        except Exception as e:
            print("Database Error:", e)
            flash("⚠ Something went wrong. Try again.")
            return redirect("/register")

        # 🔥 Clear session
        session.pop("otp", None)
        session.pop("temp_user", None)
        session.pop("otp_time", None)

        flash("🎉 Registration Successful! Please login.")
        return redirect("/student_login")

    return render_template("verify_otp.html")
@app.route("/resend_otp")
def resend_otp():

    temp_user = session.get("temp_user")

    if not temp_user:
        flash("⚠ Session expired. Register again.")
        return redirect("/register")

    new_otp = generate_otp()

    session["otp"] = new_otp
    session["otp_time"] = time.time()

    try:
        msg = Message(
            "Your New IntelliMent OTP Code",
            recipients=[temp_user["email"]]
        )
        msg.body = f"""
Hello {temp_user["name"]},

Your new OTP is:

{new_otp}

Valid for 5 minutes.
"""
        mail.send(msg)

        flash("🔁 New OTP sent to your email.")
        return redirect("/verify_otp")

    except Exception as e:
        print("Resend OTP Error:", e)
        flash("⚠ Could not resend OTP.")
        return redirect("/verify_otp")

# ===============================
# ADMIN LOGIN
# ===============================
@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        print("Entered Email:", email)
        print("Entered Password:", password)

        cur = db.cursor(dictionary=True)
        cur.execute(
            "SELECT * FROM users WHERE email=%s AND account_type='admin'",
            (email,)
        )
        admin = cur.fetchone()
        cur.close()

        print("DB Result:", admin)

        if admin:
            print("Stored Password:", admin["password"])
            print("Password Check:", admin["password"] == password)

            if admin["password"] == password:
                session["admin_name"] = admin["name"]
                session["email"] = admin["email"]
                session["role"] = "admin"
                return redirect("/admin_dashboard")
            else:
                flash("Wrong Password")
        else:
            flash("Admin not found")

    return render_template("admin_login.html")

@app.route("/admin_dashboard")
def admin_dashboard():
    if "admin_name" not in session:
        return redirect("/admin_login")
    return render_template("admin_dashboard.html")

@app.route("/admin_apti_results")
def admin_apti_results():

    if "admin_name" not in session:
        return redirect("/admin_login")

    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT 
            student_name,
            session_id,
            score,
            total_questions,
            quant_score,
            reasoning_score,
            verbal_score,
            submitted_at
        FROM apti_results
        ORDER BY submitted_at DESC
    """)
    results = cur.fetchall()
    cur.close()

    return render_template("admin_apti_results.html", results=results)

# ===============================
# ADMIN – INTELLIVIVA
# ===============================
@app.route("/intelliviva")
def intelliviva():
    if "admin_name" not in session:
        return redirect("/admin_login")
    return render_template("create_viva_session.html")

@app.route("/create_viva_session", methods=["POST"])
def create_viva_session():
    cur = db.cursor()
    cur.execute("""
        INSERT INTO viva_sessions
        (session_id, session_password, course, syllabus, difficulty, total_questions, duration)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (
        request.form["session_id"],
        request.form["session_password"],
        request.form["course"],
        request.form["syllabus"],
        request.form["difficulty"],
        request.form["total_questions"],
        request.form["duration"]
    ))
    db.commit()
    cur.close()

    flash("IntelliViva Session Created Successfully ✅")
    return redirect("/admin_dashboard")

# ===============================
# ADMIN – INTELLIAPTI
# ===============================
@app.route("/intelliapti")
def intelliapti():
    if "admin_name" not in session:
        return redirect("/admin_login")
    return render_template("create_apti_session.html")

@app.route("/create_apti_session", methods=["POST"])
def create_apti_session():

    data = request.form
    cur = db.cursor()

    # 🔥 STEP 2 FIX — REMOVE OLD QUESTIONS OF SAME SESSION
    cur.execute("DELETE FROM apti_questions WHERE session_id=%s", (data["session_id"],))

    # Insert new session
    cur.execute("""
        INSERT INTO apti_sessions
        (session_id, session_password, course, difficulty,
         quant_questions, reasoning_questions, verbal_questions, duration)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        data["session_id"],
        data["session_password"],
        data["course"],
        data["difficulty"],
        data["quant_questions"],
        data["reasoning_questions"],
        data["verbal_questions"],
        data["duration"]
    ))

    db.commit()
    cur.close()

    # Generate new questions
    generate_apti_mcqs(
        data["session_id"],
        data["difficulty"],
        int(data["quant_questions"]),
        int(data["reasoning_questions"]),
        int(data["verbal_questions"])
    )

    flash("✅ IntelliApti Session Created Successfully")
    return redirect("/admin_dashboard")

# ===============================
# STUDENT LOGIN
# ===============================
@app.route("/student_login", methods=["GET", "POST"])
def student_login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        cur = db.cursor(dictionary=True)
        cur.execute("SELECT * FROM users WHERE email=%s AND account_type='student'", (email,))
        user = cur.fetchone()
        cur.close()

        if user:
            if user["password"] == password:
                session["student_name"] = user["name"]
                session["email"] = user["email"]
                session["role"] = "student"
                return redirect("/student_dashboard")
            else:
                flash("❌ Wrong Password")
        else:
            flash("❌ User not found")

    return render_template("student_login.html")
@app.route("/student_dashboard")
def student_dashboard():

    if "student_name" not in session:
        return redirect("/student_login")

    name = session["student_name"]

    cur = db.cursor(dictionary=True)

    # 🔹 Total Tests
    cur.execute("""
        SELECT COUNT(*) as total_tests
        FROM apti_results
        WHERE student_name = %s
    """, (name,))
    total_tests = cur.fetchone()["total_tests"]

    # 🔹 Best Score
    cur.execute("""
        SELECT MAX(score) as best_score
        FROM apti_results
        WHERE student_name = %s
    """, (name,))
    best_score = cur.fetchone()["best_score"] or 0

    # 🔹 Average Score
    cur.execute("""
        SELECT AVG(score) as avg_score
        FROM apti_results
        WHERE student_name = %s
    """, (name,))
    avg_score = cur.fetchone()["avg_score"]
    avg_score = round(avg_score, 2) if avg_score else 0

    cur.close()

    return render_template(
        "student_dashboard.html",
        name=name,
        total_tests=total_tests,
        best_score=best_score,
        avg_score=avg_score
    )

# ===============================
# JOIN VIVA
# ===============================
@app.route("/join_session", methods=["GET", "POST"])
def join_session():
    if request.method == "POST":
        cur = db.cursor(buffered=True)   # ✅ IMPORTANT FIX

        cur.execute(
            "SELECT * FROM viva_sessions WHERE session_id=%s AND session_password=%s",
            (request.form["session_id"], request.form["session_password"])
        )

        s = cur.fetchone()
        cur.close()

        if not s:
            flash("Invalid Session")
            return redirect("/join_session")

        session["course"] = s[3]
        session["difficulty"] = s[5]
        return redirect("/start_viva")

    return render_template("join_session.html")


@app.route("/start_viva")
def start_viva():
    if "course" not in session:
        return redirect("/student_dashboard")

    q = generate_ai_question(
        session["course"], "Viva", session["difficulty"]
    )
    return render_template("ai_interview.html", question=q)

# ===============================
# JOIN INTELLIAPTI
# ===============================
@app.route("/join_apti_session", methods=["GET", "POST"])
def join_apti_session():

    if "student_name" not in session:
        return redirect("/student_login")

    if request.method == "POST":
        session_id = request.form["session_id"]
        session_password = request.form["session_password"]

        cur = db.cursor(dictionary=True, buffered=True)  # ✅ FIX

        cur.execute("""
            SELECT * FROM apti_sessions
            WHERE session_id=%s AND session_password=%s
        """, (session_id, session_password))

        apti = cur.fetchone()
        cur.close()

        if not apti:
            flash("❌ Invalid IntelliApti Session")
            return redirect("/join_apti_session")

        session["apti_session_id"] = session_id
        return redirect("/apti_exam")

    return render_template("join_apti_session.html")

# ===============================
# SUBMIT MOCK INTERVIEW ANSWER
# ===============================
# ===============================
# SUBMIT MOCK INTERVIEW ANSWER (REAL AI)
# ===============================
@app.route("/submit_answer", methods=["POST"])
def submit_answer():

    if "student_name" not in session:
        return redirect("/student_login")

    answer = request.form.get("answer")

    question = session.get("current_question", "Interview Question")
    domain = session.get("mock_domain", "General")
    course = session.get("mock_course", "General")

    try:

        # 🚫 EMPTY ANSWER CHECK
        if not answer or answer.strip() == "":
            technical = clarity = communication = confidence = total = 0
            feedback = "No answer was provided. Please attempt the question seriously."

        else:
            # 🧠 AI EVALUATION
            prompt = f"""
You are a strict professional interview evaluator.

Question:
{question}

Candidate Answer:
{answer}

If the answer is weak, unclear, or incorrect, give LOW marks.

Evaluate on a scale of 0 to 10 for:
1. Technical Knowledge
2. Clarity of Explanation
3. Communication Skills
4. Confidence

Return ONLY valid JSON:
{{
  "technical": number,
  "clarity": number,
  "communication": number,
  "confidence": number,
  "feedback": "short professional feedback"
}}
"""

            response = groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}]
            )

            raw = response.choices[0].message.content.strip()

            # 🛡 JSON Safe Parsing
            start = raw.find("{")
            end = raw.rfind("}") + 1

            if start == -1 or end == -1:
                raise ValueError("Invalid JSON from AI")

            analysis = json.loads(raw[start:end])

            technical = analysis.get("technical", 0)
            clarity = analysis.get("clarity", 0)
            communication = analysis.get("communication", 0)
            confidence = analysis.get("confidence", 0)
            feedback = analysis.get("feedback", "No feedback generated.")

            total = technical + clarity + communication + confidence

    except Exception as e:
        print("⚠️ AI Evaluation Error:", e)

        # Safe fallback values
        technical = clarity = communication = confidence = total = 0
        feedback = "⚠️ AI Evaluation temporarily unavailable. Please try again later."

    # ✅ SAVE INTELLIVIVA RESULT FOR ADMIN
    try:
        cur = db.cursor()
        cur.execute("""
            INSERT INTO viva_results
            (student_name, course, domain,
             technical, clarity, communication, confidence,
             total, feedback)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            session["student_name"],
            course,
            domain,
            technical,
            clarity,
            communication,
            confidence,
            total,
            feedback
        ))
        db.commit()
        cur.close()
    except Exception as db_error:
        print("⚠️ Database Save Error:", db_error)

    # 🎯 SHOW SCORECARD
    return render_template(
        "mock_scorecard.html",
        technical=technical,
        clarity=clarity,
        communication=communication,
        confidence=confidence,
        total=total,
        feedback=feedback
    )

@app.route("/admin_viva_results")
def admin_viva_results():

    if "admin_name" not in session:
        return redirect("/admin_login")

    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT *
        FROM viva_results
        ORDER BY submitted_at DESC
    """)
    results = cur.fetchall()
    cur.close()

    return render_template("admin_viva_results.html", results=results)


@app.route("/submit_mock", methods=["POST"])
def submit_mock():
    return "Mock submitted"


@app.route("/apti_exam")
def apti_exam():

    if "apti_session_id" not in session:
        return redirect("/student_dashboard")

    cur = db.cursor(dictionary=True)

    cur.execute("""
        SELECT id, section, question,
               option_a, option_b, option_c, option_d
        FROM apti_questions
        WHERE session_id=%s
        ORDER BY section
    """, (session["apti_session_id"],))

    questions = cur.fetchall()
    cur.close()

    # 🔥 Section wise grouping
    grouped_questions = {
        "Quantitative Aptitude": [],
        "Reasoning": [],
        "Verbal Ability": []
    }

    for q in questions:
        grouped_questions[q["section"]].append(q)

    return render_template(
    "apti_exam.html",
    questions=questions,
    student_name=session.get("student_name"),
    session_id=session.get("apti_session_id")
)

@app.route("/start_mock_interview", methods=["POST"])
def start_mock_interview():

    if "student_name" not in session:
        return redirect("/student_login")

    job_description = request.form["job_description"]
    domain = request.form["domain"]
    course = request.form["course"]

    question = f"Explain your skills related to {domain}."

    session["mock_domain"] = domain
    session["mock_course"] = course
    session["current_question"] = question

    return render_template(
        "ai_interview.html",
        question=question,
        domain=domain,
        course=course,
        difficulty="Medium",
        q_no=1
    )

@app.route("/mock_interview")
def mock_interview():

    if "student_name" not in session:
        return redirect("/student_login")

    return render_template("mock_interview.html")

@app.route("/student_apti_results")
def student_apti_results():

    if "student_name" not in session:
        return redirect("/student_login")

    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT 
            session_id,
            score,
            total_questions,
            quant_score,
            reasoning_score,
            verbal_score,
            submitted_at
        FROM apti_results
        WHERE student_name = %s
        ORDER BY submitted_at DESC
    """, (session["student_name"],))

    results = cur.fetchall()
    cur.close()

    return render_template(
        "student_apti_results.html",
        results=results,
        name=session["student_name"]
    )
# ===============================
# SUBMIT INTELLIAPTI EXAM ✅
# ===============================
# ===============================
# SUBMIT INTELLIAPTI EXAM (STEP-4)
# ===============================
@app.route("/submit_apti", methods=["POST"])
def submit_apti():

    if "apti_session_id" not in session:
        return redirect("/student_dashboard")

    cur = db.cursor(dictionary=True)

    cur.execute("""
        SELECT id, correct_option, section
        FROM apti_questions
        WHERE session_id = %s
    """, (session["apti_session_id"],))

    questions = cur.fetchall()
    cur.close()

    total = len(questions)
    score = 0

    # ✅ SECTION-WISE COUNTERS
    quant_score = 0
    reasoning_score = 0
    verbal_score = 0

    for q in questions:
        qid = str(q["id"])
        selected = request.form.get(f"q{qid}")

        if selected and selected == q["correct_option"]:
            score += 1

            if q["section"] == "Quantitative Aptitude":
                quant_score += 1
            elif q["section"] == "Reasoning":
                reasoning_score += 1
            elif q["section"] == "Verbal Ability":
                verbal_score += 1

    # ✅ SAVE RESULT WITH SECTION-WISE MARKS
    cur = db.cursor()
    cur.execute("""
        INSERT INTO apti_results
        (student_name, session_id, score, total_questions,
         quant_score, reasoning_score, verbal_score)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (
        session["student_name"],
        session["apti_session_id"],
        score,
        total,
        quant_score,
        reasoning_score,
        verbal_score
    ))
    db.commit()
    cur.close()

    return render_template(
    "apti_result.html",
    score=score,
    total=total,
    quant_score=quant_score,
    reasoning_score=reasoning_score,
    verbal_score=verbal_score
)

# ===============================
# GLOBAL ERROR HANDLERS
# ===============================

@app.errorhandler(404)
def not_found_error(error):
    return render_template("error.html",
                           error_code=404,
                           message="Page Not Found"), 404


@app.errorhandler(500)
def internal_error(error):
    db.rollback()
    return render_template("error.html",
                           error_code=500,
                           message="Something went wrong. Please try again."), 500


@app.route("/intellibot", methods=["POST"])
def intellibot():
    try:
        data = request.get_json()
        user_msg = data.get("message")
        role = data.get("role", "guest")

        user_email = session.get("email", "guest")
        name = session.get("name", "User")

        cur = db.cursor()

        # Fetch history
        cur.execute("""
        SELECT sender, message FROM chatbot_logs
        WHERE user_email = %s
        ORDER BY id DESC LIMIT 5
        """, (user_email,))
        history = cur.fetchall()

        system_prompt = f"""
        You are Intellibot.
        User name: {name}
        User role: {role}
        Be helpful and context-aware.
        """

        messages = [{"role": "system", "content": system_prompt}]

        for sender, msg in reversed(history):
            messages.append({
                "role": "assistant" if sender == "bot" else "user",
                "content": msg
            })

        messages.append({"role": "user", "content": user_msg})

        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages
        )

        bot_reply = response.choices[0].message.content.strip()

        # Save messages
        cur.execute("""
        INSERT INTO chatbot_logs (user_email, role, message, sender)
        VALUES (%s, %s, %s, %s)
        """, (user_email, role, user_msg, "user"))

        cur.execute("""
        INSERT INTO chatbot_logs (user_email, role, message, sender)
        VALUES (%s, %s, %s, %s)
        """, (user_email, role, bot_reply, "bot"))

        db.commit()
        cur.close()

        return {"reply": bot_reply}

    except Exception as e:
        print("Intellibot Error:", e)
        return {"reply": "⚠️ Intellibot is temporarily unavailable."}

# ===============================
# LOGOUT
# ===============================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ===============================
# RUN
# ===============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)