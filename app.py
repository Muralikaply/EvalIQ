import os
from flask import Flask, request, jsonify, render_template
from groq import Groq
import base64, uuid, json, sqlite3
from pathlib import Path
from datetime import datetime
import fitz  # PyMuPDF

# API key must be set as an environment variable on Render (Dashboard -> Environment)
# NEVER hardcode API keys in source code.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY environment variable is not set")

groq_client = Groq(api_key=GROQ_API_KEY)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "evaliq-secret-2024")
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024

UPLOAD = Path("uploads")
DB     = Path("data/evaliq.db")
ALLOWED = {'pdf', 'png', 'jpg', 'jpeg'}


def ensure_dirs():
    """Create required directories. Must run at import time (not just
    under __main__) because gunicorn imports this module without
    executing the __main__ block."""
    UPLOAD.mkdir(exist_ok=True)
    (UPLOAD / "keys").mkdir(exist_ok=True)
    (UPLOAD / "answers").mkdir(exist_ok=True)
    DB.parent.mkdir(exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS assignments (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            subject TEXT NOT NULL,
            max_marks INTEGER DEFAULT 100,
            key_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            deadline TEXT
        );
        CREATE TABLE IF NOT EXISTS submissions (
            id TEXT PRIMARY KEY,
            assignment_id TEXT NOT NULL,
            student_roll TEXT NOT NULL,
            student_name TEXT NOT NULL,
            answer_path TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            total_score INTEGER,
            percentage REAL,
            grade TEXT,
            summary TEXT,
            feedback_json TEXT,
            FOREIGN KEY (assignment_id) REFERENCES assignments(id)
        );
    """)
    conn.commit()
    conn.close()


# Run setup at import time so it works both with `python app.py`
# locally and with `gunicorn app:app` on Render.
ensure_dirs()
init_db()


def allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED


def pdf_to_base64(path):
    """Convert first page of PDF to base64 PNG."""
    doc = fitz.open(path)
    pix = doc[0].get_pixmap(dpi=150)
    data = base64.standard_b64encode(pix.tobytes("png")).decode()
    doc.close()
    return data


def file_to_base64(path):
    """Convert image or PDF to base64 string."""
    ext = Path(path).suffix.lower()
    if ext == '.pdf':
        return pdf_to_base64(path), "image/png"
    with open(path, 'rb') as f:
        data = f.read()
    mt = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png'}.get(ext.lstrip('.'), 'image/png')
    return base64.standard_b64encode(data).decode(), mt


def ai_evaluate(key_path, ans_path, subject, max_marks):
    k_b64, k_mt = file_to_base64(key_path)
    a_b64, a_mt = file_to_base64(ans_path)

    prompt = f"""You are an expert academic evaluator.
Subject: {subject} | Maximum Marks: {max_marks}

The FIRST image is the ANSWER KEY (teacher's correct answers).
The SECOND image is the STUDENT'S answer sheet.

Compare the student's answers against the answer key carefully.
Award marks fairly for each question.

Respond ONLY with valid JSON — no markdown, no extra text:
{{
  "total_score": <number>,
  "max_marks": {max_marks},
  "percentage": <number>,
  "grade": "<A+/A/B/C/D/F>",
  "summary": "<2-3 sentence overall assessment>",
  "questions": [
    {{
      "question_no": "Q1",
      "marks_awarded": <number>,
      "marks_possible": <number>,
      "status": "<correct|partial|incorrect>",
      "feedback": "<specific constructive feedback>"
    }}
  ],
  "strengths": ["<strength 1>", "<strength 2>"],
  "improvements": ["<area to improve 1>", "<area to improve 2>"]
}}"""

    response = groq_client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text",  "text": "ANSWER KEY (teacher):"},
                    {"type": "image_url", "image_url": {"url": f"data:{k_mt};base64,{k_b64}"}},
                    {"type": "text",  "text": "STUDENT ANSWER SHEET:"},
                    {"type": "image_url", "image_url": {"url": f"data:{a_mt};base64,{a_b64}"}},
                    {"type": "text",  "text": prompt}
                ]
            }
        ],
        max_tokens=2000,
        temperature=0.1
    )

    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


@app.route('/')
def index():
    return render_template('login.html')

@app.route('/teacher')
def teacher():
    return render_template('teacher.html')

@app.route('/student')
def student():
    return render_template('student.html')


@app.route('/api/teacher/create-assignment', methods=['POST'])
def create_assignment():
    if 'key_file' not in request.files:
        return jsonify({"error": "Answer key file required"}), 400
    f = request.files['key_file']
    if not allowed(f.filename):
        return jsonify({"error": "Invalid file type"}), 400

    aid     = str(uuid.uuid4())[:8]
    ext     = Path(f.filename).suffix
    key_path = UPLOAD / "keys" / f"{aid}_key{ext}"
    f.save(key_path)

    title     = request.form.get('title', 'Untitled Assignment')
    subject   = request.form.get('subject', 'General')
    max_marks = int(request.form.get('max_marks', 100))
    deadline  = request.form.get('deadline', '')

    db = get_db()
    db.execute("INSERT INTO assignments VALUES (?,?,?,?,?,?,?)",
               (aid, title, subject, max_marks, str(key_path), now(), deadline))
    db.commit()
    db.close()
    return jsonify({"success": True, "assignment_id": aid})

@app.route('/api/teacher/assignments')
def get_assignments():
    db   = get_db()
    rows = db.execute("SELECT * FROM assignments ORDER BY created_at DESC").fetchall()
    result = []
    for r in rows:
        subs  = db.execute("SELECT COUNT(*) as c FROM submissions WHERE assignment_id=?", (r['id'],)).fetchone()['c']
        evald = db.execute("SELECT COUNT(*) as c FROM submissions WHERE assignment_id=? AND status='evaluated'", (r['id'],)).fetchone()['c']
        result.append({
            "id": r['id'], "title": r['title'], "subject": r['subject'],
            "max_marks": r['max_marks'], "created_at": r['created_at'],
            "deadline": r['deadline'], "total_submissions": subs,
            "evaluated": evald, "pending": subs - evald
        })
    db.close()
    return jsonify(result)

@app.route('/api/teacher/submissions/<assignment_id>')
def get_submissions(assignment_id):
    db   = get_db()
    rows = db.execute("SELECT * FROM submissions WHERE assignment_id=? ORDER BY submitted_at DESC", (assignment_id,)).fetchall()
    result = []
    for r in rows:
        fb = json.loads(r['feedback_json']) if r['feedback_json'] else {}
        result.append({
            "id": r['id'], "student_roll": r['student_roll'],
            "student_name": r['student_name'], "submitted_at": r['submitted_at'],
            "status": r['status'], "total_score": r['total_score'],
            "percentage": r['percentage'], "grade": r['grade'],
            "summary": r['summary'], "feedback": fb
        })
    db.close()
    return jsonify(result)

# ─── STUDENT APIs ─────────────────────────────────────────────────
@app.route('/api/student/login', methods=['POST'])
def student_login():
    data = request.json
    roll = data.get('roll', '').strip().upper()
    name = data.get('name', '').strip()
    if not roll or not name:
        return jsonify({"error": "Roll number and name are required"}), 400
    return jsonify({"success": True, "roll": roll, "name": name})

@app.route('/api/student/assignments')
def student_assignments():
    db   = get_db()
    rows = db.execute("SELECT * FROM assignments ORDER BY created_at DESC").fetchall()
    db.close()
    return jsonify([{
        "id": r['id'], "title": r['title'], "subject": r['subject'],
        "max_marks": r['max_marks'], "created_at": r['created_at'], "deadline": r['deadline']
    } for r in rows])

@app.route('/api/student/my-submissions')
def my_submissions():
    roll = request.args.get('roll', '').upper()
    if not roll:
        return jsonify({"error": "Roll number required"}), 400
    db   = get_db()
    rows = db.execute(
        """SELECT s.*, a.title, a.subject, a.max_marks
           FROM submissions s JOIN assignments a ON s.assignment_id=a.id
           WHERE s.student_roll=? ORDER BY s.submitted_at DESC""", (roll,)
    ).fetchall()
    result = []
    for r in rows:
        fb = json.loads(r['feedback_json']) if r['feedback_json'] else {}
        result.append({
            "id": r['id'], "assignment_id": r['assignment_id'],
            "title": r['title'], "subject": r['subject'],
            "max_marks": r['max_marks'], "submitted_at": r['submitted_at'],
            "status": r['status'], "total_score": r['total_score'],
            "percentage": r['percentage'], "grade": r['grade'],
            "summary": r['summary'], "feedback": fb
        })
    db.close()
    return jsonify(result)

@app.route('/api/student/submit', methods=['POST'])
def submit_answer():
    roll = request.form.get('roll', '').strip().upper()
    name = request.form.get('name', '').strip()
    aid  = request.form.get('assignment_id', '')

    if not roll or not name or not aid:
        return jsonify({"error": "Missing required fields"}), 400

    db         = get_db()
    assignment = db.execute("SELECT * FROM assignments WHERE id=?", (aid,)).fetchone()
    if not assignment:
        db.close()
        return jsonify({"error": "Assignment not found"}), 404

    existing = db.execute(
        "SELECT id FROM submissions WHERE assignment_id=? AND student_roll=?", (aid, roll)
    ).fetchone()
    if existing:
        db.close()
        return jsonify({"error": "You have already submitted this assignment"}), 409

    if 'answer_file' not in request.files:
        db.close()
        return jsonify({"error": "Answer file required"}), 400

    f = request.files['answer_file']
    if not allowed(f.filename):
        db.close()
        return jsonify({"error": "Invalid file type"}), 400

    sid      = str(uuid.uuid4())[:8]
    ext      = Path(f.filename).suffix
    ans_path = UPLOAD / "answers" / f"{sid}_ans{ext}"
    f.save(ans_path)

    db.execute("INSERT INTO submissions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
               (sid, aid, roll, name, str(ans_path), now(),
                'evaluating', None, None, None, None, None))
    db.commit()

    try:
        result = ai_evaluate(assignment['key_path'], str(ans_path),
                             assignment['subject'], assignment['max_marks'])
        db.execute(
            """UPDATE submissions SET status='evaluated', total_score=?,
               percentage=?, grade=?, summary=?, feedback_json=? WHERE id=?""",
            (result['total_score'], result['percentage'], result['grade'],
             result['summary'], json.dumps(result), sid)
        )
        db.commit()
        db.close()
        return jsonify({"success": True, "result": result, "submission_id": sid})
    except Exception as e:
        db.execute("UPDATE submissions SET status='error' WHERE id=?", (sid,))
        db.commit()
        db.close()
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    # Local dev only. On Render, gunicorn runs the app instead of this block.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
