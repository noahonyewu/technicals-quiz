from dotenv import load_dotenv
load_dotenv()
from flask import Flask, request, session, redirect, url_for
import anthropic
import random
import json
import os

app = Flask(__name__)
app.secret_key = "any-random-string-here"
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

TOPICS = ["accounting", "valuation", "DCF", "LBO", "M&A", "enterprise value"]

@app.route("/")
def home():
    return '''
    <div style="max-width: 800px; margin: 0 auto; padding: 20px; font-family: sans-serif;">
        <h1>Technicals Quiz</h1>
        <p>20 questions. Pick your mode:</p>
        <form action="/start" method="post">
            <label><input type="radio" name="mode" value="mc" checked> Multiple choice only</label><br>
            <label><input type="radio" name="mode" value="long"> Long answer only</label><br>
            <label><input type="radio" name="mode" value="mixed"> Mix of both</label><br><br>
            <button type="submit">Start Quiz</button>
        </form>
    </div>
    '''

@app.route("/start", methods=["POST"])
def start():
    session["mode"] = request.form["mode"]
    session["question_num"] = 0
    session["score"] = 0
    session["recent_topics"] = []
    return redirect(url_for("question"))

@app.route("/question")
def question():
    if session.get("question_num", 0) >= 20:
        return redirect(url_for("results"))
    
    recent = session.get("recent_topics", [])
    available = [t for t in TOPICS if t not in recent[-3:]] or TOPICS
    chosen_topic = random.choice(available)
    recent.append(chosen_topic)
    session["recent_topics"] = recent
    
    mode = session.get("mode", "mixed")
    if mode == "mc":
        q_type = "mc"
    elif mode == "long":
        q_type = "long"
    else:
        q_type = random.choice(["mc", "long"])
    
    session["current_type"] = q_type
    
    if q_type == "mc":
        prompt = f"""Generate one CONCEPTUAL investment banking technical multiple choice question on the topic of {chosen_topic}.

This should test understanding of concepts, definitions, relationships, and reasoning. NOT math calculations.

Respond with ONLY valid JSON in this exact format, no markdown, no code blocks, no explanation before or after:

{{
  "question": "the question text",
  "options": {{
    "A": "option A text",
    "B": "option B text",
    "C": "option C text",
    "D": "option D text"
  }},
  "correct": "A",
  "explanation": "why the correct answer is right"
}}"""
        
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        
        raw = message.content[0].text.strip()
        # Strip common markdown wrappers
        if raw.startswith("```json"):
            raw = raw[7:]
        if raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        
        data = json.loads(raw)
        
        session["current_question"] = data["question"]
        session["current_options"] = data["options"]
        session["current_correct"] = data["correct"]
        session["current_explanation"] = data["explanation"]
        
        options_html = "".join([f'<label><input type="radio" name="user_answer" value="{k}" required> {k}) {v}</label><br>' for k, v in data["options"].items()])
        
        return f'''
        <div style="max-width: 800px; margin: 0 auto; padding: 20px; font-family: sans-serif;">
            <p>Question {session["question_num"] + 1} of 20 | Score: {session["score"]}</p>
            <h2>{data["question"]}</h2>
            <form action="/answer" method="post">
                {options_html}<br>
                <button type="submit">Submit</button>
            </form>
        </div>
        '''
    else:
        prompt = f"""Generate one investment banking technical interview question on the topic of {chosen_topic}.

Format your response exactly like this, with no markdown, no asterisks, no pound signs, and no bullet points:

QUESTION: [the question]
ANSWER: [the correct answer, using clear step-by-step math. Use the word 'minus' instead of the minus symbol.]"""
        
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        text = message.content[0].text
        
        question_part = text.split("ANSWER:")[0].replace("QUESTION:", "").strip()
        answer_part = text.split("ANSWER:")[1].strip()
        
        session["current_question"] = question_part
        session["current_answer"] = answer_part
        
        return f'''
        <div style="max-width: 800px; margin: 0 auto; padding: 20px; font-family: sans-serif;">
            <p>Question {session["question_num"] + 1} of 20 | Score: {session["score"]}</p>
            <h2>{question_part}</h2>
            <form action="/answer" method="post">
                <textarea name="user_answer" rows="6" cols="60" placeholder="Type your answer" required></textarea><br><br>
                <button type="submit">Submit</button>
            </form>
        </div>
        '''

@app.route("/answer", methods=["POST"])
def answer():
    user_answer = request.form["user_answer"]
    q_type = session.get("current_type")
    session["question_num"] = session.get("question_num", 0) + 1
    
    if q_type == "mc":
        correct = session["current_correct"]
        is_correct = user_answer.upper() == correct.upper()
        if is_correct:
            session["score"] = session.get("score", 0) + 1
        
        result_text = "Correct!" if is_correct else f"Wrong. Correct answer: {correct}"
        
        options = session["current_options"]
        options_display = "".join([f'<p>{k}) {v}</p>' for k, v in options.items()])
        
        return f'''
        <div style="max-width: 800px; margin: 0 auto; padding: 20px; font-family: sans-serif;">
            <h2>{result_text}</h2>
            <p><strong>Question:</strong> {session["current_question"]}</p>
            {options_display}
            <p><strong>Your answer:</strong> {user_answer}</p>
            <h3>Explanation</h3>
            <div style="white-space: pre-wrap;">{session["current_explanation"]}</div>
            <br>
            <a href="/question"><button>Next Question</button></a>
        </div>
        '''
    else:
        grading = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": f"""Question: {session["current_question"]}

Correct answer: {session["current_answer"]}

My answer: {user_answer}

Grade my answer. First, say whether I got the core answer and reasoning correct. Do not penalize informal phrasing. Only flag actual conceptual errors. At the end, give the full polished interview version.

Also, on the very first line, output just the word CORRECT or WRONG based on whether I got the mechanics right.

Do not use any markdown formatting."""
            }]
        )
        feedback = grading.content[0].text
        
        first_line = feedback.split("\n")[0].strip().upper()
        is_correct = "CORRECT" in first_line and "WRONG" not in first_line
        if is_correct:
            session["score"] = session.get("score", 0) + 1
        
        return f'''
        <div style="max-width: 800px; margin: 0 auto; padding: 20px; font-family: sans-serif;">
            <h2>{"Correct!" if is_correct else "Wrong."}</h2>
            <p><strong>Question:</strong> {session["current_question"]}</p>
            <p><strong>Your answer:</strong> {user_answer}</p>
            <h3>Feedback</h3>
            <div style="white-space: pre-wrap;">{feedback}</div>
            <br>
            <a href="/question"><button>Next Question</button></a>
        </div>
        '''

@app.route("/results")
def results():
    score = session.get("score", 0)
    return f'''
    <div style="max-width: 800px; margin: 0 auto; padding: 20px; font-family: sans-serif;">
        <h1>Quiz Complete</h1>
        <h2>Final Score: {score} / 20</h2>
        <p>{round(score/20*100)}%</p>
        <br>
        <a href="/"><button>New Quiz</button></a>
    </div>
    '''

if __name__ == "__main__":
    app.run(debug=True)