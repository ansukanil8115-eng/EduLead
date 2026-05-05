import os
import sqlite3
from datetime import datetime

from flask import Flask, jsonify, render_template, request, session

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")

DB_PATH = "leads.db"

COURSES = {
    "ai_ml": {
        "name": "AI & ML",
        "duration": "6 months",
        "fees": "INR 65,000",
        "description": "Covers machine learning, deep learning, and real-world AI projects.",
        "keywords": ["ai", "ml", "machine learning", "artificial intelligence", "ai & ml"],
    },
    "data_science": {
        "name": "Data Science",
        "duration": "8 months",
        "fees": "INR 75,000",
        "description": "Includes Python, statistics, data visualization, and model building.",
        "keywords": ["data science", "data scientist", "analytics", "data"],
    },
    "web_development": {
        "name": "Web Development",
        "duration": "5 months",
        "fees": "INR 50,000",
        "description": "Teaches frontend, backend, APIs, and deployment with hands-on projects.",
        "keywords": ["web", "web development", "frontend", "backend", "full stack"],
    },
}


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            course TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


def default_conversation_state():
    return {"stage": "idle", "lead": {}}


def detect_course_from_text(message: str):
    lower_msg = message.lower()
    for course in COURSES.values():
        if any(keyword in lower_msg for keyword in course["keywords"]):
            return course
    return None


def detect_intent(message: str, state: dict):
    lower_msg = message.lower().strip()

    stage = state.get("stage", "idle")
    if stage == "await_name":
        return "provide_name"
    if stage == "await_phone":
        return "provide_phone"
    if stage == "await_course":
        return "provide_course"
    if stage == "await_brochure":
        if any(word in lower_msg for word in ["yes", "yeah", "sure", "ok"]):
            return "brochure_yes"
        if any(word in lower_msg for word in ["no", "not now", "later"]):
            return "brochure_no"
        return "brochure_clarify"

    if any(word in lower_msg for word in ["hello", "hi", "hey"]):
        return "greeting"
    if "what courses" in lower_msg or "courses do you offer" in lower_msg:
        return "course_list"
    if any(word in lower_msg for word in ["fees", "fee", "duration", "details", "about"]):
        if detect_course_from_text(message):
            return "course_detail"

    if detect_course_from_text(message):
        return "course_detail"

    return "unknown"


def ai_response(message: str):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or OpenAI is None:
        return None

    try:
        client = OpenAI(api_key=api_key)
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an educational enquiry assistant. "
                        "Answer only about courses, fees, and duration in 1-2 short lines."
                    ),
                },
                {"role": "user", "content": message},
            ],
            temperature=0.2,
        )
        return completion.choices[0].message.content
    except Exception:
        return None


def save_lead(name: str, phone: str, course: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO leads (name, phone, course, timestamp) VALUES (?, ?, ?, ?)",
        (name, phone, course, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def generate_response(intent: str, message: str, state: dict):
    course = detect_course_from_text(message)

    if intent == "greeting":
        return "Hello! I can help with course details for AI & ML, Data Science, and Web Development."

    if intent == "course_list":
        state["stage"] = "await_name"
        return (
            "We offer: AI & ML, Data Science, and Web Development.\n"
            "Can I have your name?"
        )

    if intent == "course_detail":
        if course:
            state["stage"] = "await_name"
            return (
                f"{course['name']} - Duration: {course['duration']}, Fees: {course['fees']}. "
                f"{course['description']}\nCan I have your name?"
            )

    if intent == "provide_name":
        name = message.strip()
        if len(name) < 2:
            return "Please share a valid name."
        state["lead"]["name"] = name
        state["stage"] = "await_phone"
        return "Please enter your phone number."

    if intent == "provide_phone":
        cleaned = "".join(ch for ch in message if ch.isdigit())
        if len(cleaned) < 10:
            return "Please enter a valid phone number (at least 10 digits)."
        state["lead"]["phone"] = cleaned
        state["stage"] = "await_course"
        return "Which course are you interested in? (AI & ML / Data Science / Web Development)"

    if intent == "provide_course":
        if not course:
            return "Please choose one of these courses: AI & ML, Data Science, Web Development."
        state["lead"]["course"] = course["name"]
        save_lead(
            state["lead"]["name"],
            state["lead"]["phone"],
            state["lead"]["course"],
        )
        state["stage"] = "await_brochure"
        return "Thank you. Our team will contact you soon. Would you like a brochure?"

    if intent == "brochure_yes":
        state["stage"] = "completed"
        return "Great! Here is the brochure link: https://example.com/brochure.pdf"

    if intent == "brochure_no":
        state["stage"] = "completed"
        return "No problem. Let me know if you need any more course details."

    if intent == "brochure_clarify":
        return "Please reply with Yes or No. Would you like a brochure?"

    # Optional AI layer first, then rule-based fallback.
    ai_text = ai_response(message)
    if ai_text:
        state["stage"] = "await_name"
        return f"{ai_text}\nCan I have your name?"

    return (
        "I can help with AI & ML, Data Science, or Web Development queries. "
        "Ask about course fees, duration, or details."
    )


@app.route("/")
def index():
    if "conversation_state" not in session:
        session["conversation_state"] = default_conversation_state()
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message", "").strip()

    if not message:
        return jsonify({"reply": "Please type a message."})

    state = session.get("conversation_state", default_conversation_state())
    intent = detect_intent(message, state)
    reply = generate_response(intent, message, state)

    session["conversation_state"] = state
    return jsonify({"reply": reply})


@app.route("/reset", methods=["POST"])
def reset_chat():
    session["conversation_state"] = default_conversation_state()
    return jsonify({"reply": "Hello! Ask me about our courses."})


if __name__ == "__main__":
    app.run(debug=True)
