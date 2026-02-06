from groq import Groq
import os

GROQ_API_KEY = os.getenv("GROQ_API_KEY"))

# 1️⃣ Generate Interview Question
def generate_question(domain="OOPS", level="Medium"):
    prompt = f"""
    Ask one {level} difficulty interview question
    for a BCA student on topic: {domain}
    """

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content


# 2️⃣ Evaluate Answer using AI
def evaluate_answer(question, answer):
    prompt = f"""
    Evaluate the student's answer.

    Question: {question}
    Answer: {answer}

    Give output in this format:
    Relevance Score (0-10):
    Concept Clarity:
    Confidence Level:
    Overall Feedback:
    """

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content
