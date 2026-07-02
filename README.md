# EvalIQ — AI Exam Evaluation System

A complete Flask web app with Teacher & Student dashboards powered by Claude AI.

## Quick Start

### 1. Install
```bash
pip install -r requirements.txt
```

### 2. Set API Key
```bash
export ANTHROPIC_API_KEY=your_key_here   # Mac/Linux
set ANTHROPIC_API_KEY=your_key_here      # Windows
```

### 3. Run
```bash
python app.py
```
Open → **http://localhost:5000**

---

## How to Use

### 👩‍🏫 As a Teacher
1. Go to `http://localhost:5000` → click **Teacher**
2. Password: **`teacher123`** (change in app.py if needed)
3. **Create Assignment** → enter title, subject, max marks, upload answer key
4. Students submit their answers online
5. Go to **Assignments** → click any assignment → see all submissions
6. Click **Details** on any student to see their full breakdown, marks per question, grade, feedback

### 🎓 As a Student
1. Go to `http://localhost:5000` → click **Student**
2. Enter your **Roll Number** (e.g. CS2024001) + Full Name
3. **Submit Answer** → pick an assignment → upload your answer sheet
4. Wait ~30-60 seconds — AI evaluates automatically
5. Go to **My Results** → see score, grade, feedback per question

---

## Project Structure
```
evaliq/
├── app.py                  # Flask backend + SQLite + Claude AI
├── requirements.txt
├── data/
│   └── evaliq.db           # Auto-created SQLite database
├── uploads/
│   ├── keys/               # Teacher answer keys (temp)
│   └── answers/            # Student answer sheets (temp)
└── templates/
    ├── login.html           # Landing page (Teacher / Student choice)
    ├── teacher.html         # Teacher dashboard
    └── student.html         # Student dashboard
```

## Features
| Feature | Teacher | Student |
|---|---|---|
| Login | Password-based | Roll Number + Name |
| Assignments | Create, manage | View available |
| Answer Key | Upload PDF/image | — |
| Submission | — | Upload answer, see instant result |
| Results | All students, per assignment | Own results only |
| AI Feedback | View any student's detail | View own detail |
| Stats | Total, submitted, evaluated, pending | Avg score, submitted count |

## Notes
- SQLite DB auto-created on first run in `data/` folder
- Files deleted after evaluation (privacy)  
- Duplicate submission prevention by roll number per assignment
- Change teacher password in `app.py` → `TEACHER_PASS` in login.html
