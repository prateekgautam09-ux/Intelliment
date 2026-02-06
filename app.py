from flask import Flask, render_template, request, redirect, flash, session
import mysql.connector
import os
from groq import Groq
import json

# ===============================
# FLASK SETUP
# ===============================
app = Flask(__name__)
app.secret_key = "secret123"

# ===============================
# AI CLIENT
# ===============================
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ===============================
# DATABASE
# ===============================
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",
    database="ai_viva_examiner"
)

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
Generate EXACTLY {count} {difficulty} {section} MCQs.

Return ONLY JSON:
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
            messages=[{"role": "user", "content": prompt}]
        )

        raw = response.choices[0].message.content.strip()
        start = raw.find("[")
        end = raw.rfind("]") + 1
        mcqs = json.loads(raw[start:end])

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
        account_type = request.form["account_type"]  # student / admin

        cur = db.cursor(buffered=True)

        cur.execute("""
            INSERT INTO users (name, email, password, account_type)
            VALUES (%s, %s, %s, %s)
        """, (name, email, password, account_type))

        db.commit()
        cur.close()

        flash("✅ Registration successful. Please login.")
        return redirect("/student_login")

    return render_template("register.html")

# ===============================
# ADMIN LOGIN
# ===============================
@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        cur = db.cursor(buffered=True)   # ✅ FIX
        cur.execute(
            "SELECT * FROM users WHERE email=%s AND password=%s AND account_type='admin'",
            (request.form["email"], request.form["password"])
        )
        admin = cur.fetchone()
        cur.close()

        if admin:
            session["admin_name"] = admin[1]
            return redirect("/admin_dashboard")

        flash("Invalid Admin Credentials")

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
        cur = db.cursor()
        cur.execute(
            "SELECT * FROM users WHERE email=%s AND password=%s AND account_type='student'",
            (request.form["email"], request.form["password"])
        )
        student = cur.fetchone()
        cur.close()

        if student:
            session["student_name"] = student[1]
            return redirect("/student_dashboard")

        flash("Invalid Student Credentials")

    return render_template("student_login.html")

@app.route("/student_dashboard")
def student_dashboard():
    if "student_name" not in session:
        return redirect("/student_login")
    return render_template("student_dashboard.html", name=session["student_name"])

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
        start = raw.find("{")
        end = raw.rfind("}") + 1
        analysis = json.loads(raw[start:end])

        technical = analysis["technical"]
        clarity = analysis["clarity"]
        communication = analysis["communication"]
        confidence = analysis["confidence"]
        feedback = analysis["feedback"]

        total = technical + clarity + communication + confidence

    # ✅ SAVE INTELLIVIVA RESULT FOR ADMIN
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

    cur = db.cursor(dictionary=True, buffered=True)  # ✅ FIX

    cur.execute("""
        SELECT id, section, question,
               option_a, option_b, option_c, option_d
        FROM apti_questions
        WHERE session_id=%s
    """, (session["apti_session_id"],))

    questions = cur.fetchall()
    cur.close()

    return render_template("apti_exam.html", questions=questions)

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

    return f"""
    <h2>✅ Test Submitted Successfully</h2>
    <p>Total Score: {score} / {total}</p>
    <p>Quant: {quant_score}</p>
    <p>Reasoning: {reasoning_score}</p>
    <p>Verbal: {verbal_score}</p>
    <a href="/student_dashboard">Back to Dashboard</a>
    """



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
    app.run(debug=True)
