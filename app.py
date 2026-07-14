from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, session, redirect, url_for
import anthropic
import random
import json
import os
import threading

app = Flask(__name__)
app.secret_key = "any-random-string-here"
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

TOPICS = ["accounting", "valuation", "DCF", "LBO", "M&A", "enterprise value"]

# In-memory cache for pre-generated next questions, keyed by session id
next_question_cache = {}

BASE_STYLES = """
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#1e3a5f">
<title>Technicals Quiz</title>
<style>
    * { box-sizing: border-box; }
    body { margin: 0; padding: 0; background: #1e3a5f; color: #333; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; min-height: 100vh; }
    .container { max-width: 700px; margin: 0 auto; padding: 24px 20px; }
    .card { background: white; border-radius: 16px; padding: 28px 24px; box-shadow: 0 4px 20px rgba(0,0,0,0.15); margin-bottom: 20px; }
    h1 { color: white; text-align: center; margin: 20px 0 30px; font-size: 32px; }
    h2 { color: #1e3a5f; margin: 0 0 20px; font-size: 22px; line-height: 1.4; }
    h3 { color: #1e3a5f; margin: 20px 0 10px; font-size: 18px; }
    p { line-height: 1.6; margin: 0 0 12px; }
    .status-bar { display: flex; justify-content: space-between; color: white; font-size: 14px; margin-bottom: 16px; padding: 0 4px; }
    .topic-tag { display: inline-block; background: #4a90e2; color: white; padding: 6px 14px; border-radius: 20px; font-size: 13px; font-weight: 600; margin-bottom: 16px; text-transform: uppercase; letter-spacing: 0.5px; }
    .option-label { display: block; background: #f4f6f9; padding: 16px; margin: 10px 0; border-radius: 10px; cursor: pointer; transition: background 0.15s; font-size: 16px; line-height: 1.5; }
    .option-label:hover, .option-label:active { background: #e8eef5; }
    .option-label input { margin-right: 12px; }
    button, .btn { background: #4a90e2; color: white; border: none; padding: 16px 32px; font-size: 17px; font-weight: 600; border-radius: 12px; cursor: pointer; width: 100%; margin-top: 12px; transition: background 0.15s; text-decoration: none; display: inline-block; text-align: center; }
    button:hover, .btn:hover { background: #3a7dd0; }
    .result-correct { color: #22c55e; font-size: 24px; font-weight: 700; margin-bottom: 16px; }
    .result-wrong { color: #ef4444; font-size: 24px; font-weight: 700; margin-bottom: 16px; }
    .difficulty-choice { display: block; background: #f4f6f9; padding: 14px 16px; margin: 8px 0; border-radius: 10px; cursor: pointer; font-size: 16px; }
    .difficulty-choice input { margin-right: 10px; }
    .score-big { font-size: 48px; font-weight: 700; color: #4a90e2; text-align: center; margin: 20px 0; }
    .percent { font-size: 20px; text-align: center; color: #666; margin-bottom: 20px; }
    .loading { text-align: center; padding: 40px; color: #666; }
</style>
"""

def page(content):
    return f"<!DOCTYPE html><html><head>{BASE_STYLES}</head><body><div class='container'>{content}</div></body></html>"

def generate_question(difficulty, chosen_topic, asked_questions):
    difficulty_notes = {
        "easy": "This should be a basic conceptual question that tests foundational understanding.",
        "medium": "This should be a standard interview-level question.",
        "hard": "This should be a challenging question that tests deeper understanding, edge cases, or nuanced concepts."
    }
    
    avoid_text = ""
    if asked_questions:
        avoid_text = f"\n\nDO NOT ask any of these previously asked questions or minor rewordings of them:\n" + "\n".join([f"- {q}" for q in asked_questions[-15:]])
    
    prompt = f"""Generate one CONCEPTUAL investment banking technical multiple choice question on the topic of {chosen_topic}.

Difficulty: {difficulty}. {difficulty_notes[difficulty]}

This should test understanding of concepts, definitions, relationships, and reasoning. NOT math calculations.{avoid_text}

Respond with ONLY valid JSON, no markdown, no code blocks:

{{
  "question": "the question text",
  "options": {{"A": "text", "B": "text", "C": "text", "D": "text"}},
  "correct": "A",
  "explanation": "why the correct answer is right"
}}"""
    
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    
    raw = message.content[0].text.strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    if raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    
    return json.loads(raw.strip())

def pick_topic(recent):
    available = [t for t in TOPICS if t not in recent[-3:]] or TOPICS
    return random.choice(available)

def prefetch_next(session_id, difficulty, recent_topics, asked_questions):
    """Runs in background thread to pre-generate the next question."""
    try:
        chosen_topic = pick_topic(recent_topics)
        data = generate_question(difficulty, chosen_topic, asked_questions)
        next_question_cache[session_id] = {"data": data, "topic": chosen_topic}
    except Exception as e:
        next_question_cache[session_id] = {"error": str(e)}

@app.route("/")
def home():
    return page('''
        <h1>Technicals Quiz</h1>
        <div class="card">
            <h3>Select difficulty</h3>
            <form action="/start" method="post">
                <label class="difficulty-choice"><input type="radio" name="difficulty" value="easy"> Easy</label>
                <label class="difficulty-choice"><input type="radio" name="difficulty" value="medium" checked> Medium</label>
                <label class="difficulty-choice"><input type="radio" name="difficulty" value="hard"> Hard</label>
                <button type="submit">Start Quiz</button>
            </form>
        </div>
    ''')

@app.route("/start", methods=["POST"])
def start():
    session["difficulty"] = request.form["difficulty"]
    session["question_num"] = 0
    session["score"] = 0
    session["recent_topics"] = []
    session["asked_questions"] = []
    session["session_id"] = str(random.randint(100000, 999999))
    # Clear any old cached questions
    next_question_cache.pop(session["session_id"], None)
    return redirect(url_for("question"))

@app.route("/question")
def question():
    if session.get("question_num", 0) >= 20:
        return redirect(url_for("results"))
    
    session_id = session.get("session_id")
    recent = session.get("recent_topics", [])
    difficulty = session.get("difficulty", "medium")
    asked = session.get("asked_questions", [])
    
    # Check if we have a pre-generated question ready
    cached = next_question_cache.pop(session_id, None)
    
    if cached and "data" in cached:
        data = cached["data"]
        chosen_topic = cached["topic"]
    else:
        # No cache (first question or prefetch failed), generate now
        chosen_topic = pick_topic(recent)
        data = generate_question(difficulty, chosen_topic, asked)
    
    recent.append(chosen_topic)
    session["recent_topics"] = recent
    asked.append(data["question"])
    session["asked_questions"] = asked
    
    session["current_question"] = data["question"]
    session["current_options"] = data["options"]
    session["current_correct"] = data["correct"]
    session["current_explanation"] = data["explanation"]
    session["current_topic"] = chosen_topic
    
    options_html = "".join([f'<label class="option-label"><input type="radio" name="user_answer" value="{k}" required> <strong>{k})</strong> {v}</label>' for k, v in data["options"].items()])
    
    return page(f'''
        <div class="status-bar">
            <span>Question {session["question_num"] + 1} of 20</span>
            <span>Score: {session["score"]}</span>
        </div>
        <div class="card">
            <span class="topic-tag">{chosen_topic}</span>
            <h2>{data["question"]}</h2>
            <form action="/answer" method="post">
                {options_html}
                <button type="submit">Submit</button>
            </form>
        </div>
    ''')

@app.route("/answer", methods=["POST"])
def answer():
    user_answer = request.form["user_answer"]
    session["question_num"] = session.get("question_num", 0) + 1
    
    correct = session["current_correct"]
    is_correct = user_answer.upper() == correct.upper()
    if is_correct:
        session["score"] = session.get("score", 0) + 1
    
    result_class = "result-correct" if is_correct else "result-wrong"
    result_text = "Correct" if is_correct else f"Wrong. Correct answer: {correct}"
    
    options = session["current_options"]
    options_display = "".join([f'<p><strong>{k})</strong> {v}</p>' for k, v in options.items()])
    
    # Kick off background pre-generation of next question (if not on last one)
    if session["question_num"] < 20:
        thread = threading.Thread(
            target=prefetch_next,
            args=(session["session_id"], session["difficulty"], session["recent_topics"], session["asked_questions"])
        )
        thread.daemon = True
        thread.start()
    
    return page(f'''
        <div class="status-bar">
            <span>Question {session["question_num"]} of 20</span>
            <span>Score: {session["score"]}</span>
        </div>
        <div class="card">
            <div class="{result_class}">{result_text}</div>
            <span class="topic-tag">{session["current_topic"]}</span>
            <h2>{session["current_question"]}</h2>
            {options_display}
            <p><strong>Your answer:</strong> {user_answer}</p>
            <h3>Explanation</h3>
            <p>{session["current_explanation"]}</p>
            <a href="/question" class="btn">Next Question</a>
        </div>
    ''')

@app.route("/results")
def results():
    score = session.get("score", 0)
    percent = round(score/20*100)
    # Clean up cache
    next_question_cache.pop(session.get("session_id"), None)
    return page(f'''
        <h1>Quiz Complete</h1>
        <div class="card">
            <div class="score-big">{score} / 20</div>
            <div class="percent">{percent}%</div>
            <a href="/" class="btn">New Quiz</a>
        </div>
    ''')

if __name__ == "__main__":
    app.run(debug=True)