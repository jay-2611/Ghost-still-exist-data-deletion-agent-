import os
import base64
import json

def call_gemini(parts):
    """Test double: never make a network request or read credentials in tests."""
    return json.dumps({"ok": True, "part_count": len(parts)})

def test_intent_classification():
    print("=== 1. Testing Intent Classification (Text) ===")
    prompt = """Analyze each of the following user requests and determine if it authorizes account/personal data deletion.
Answer in JSON with format: [{"id": 1, "is_deletion": true/false, "action": "..."}, ...]

Requests:
1. "Please close my account and permanently delete all my personal data."
2. "I would like a copy of all my data exported to JSON format."
3. "Por favor, elimine permanentemente todos mis datos personales de sus servidores."
4. "Please unsubscribe me from promotional newsletters."
"""
    result = call_gemini([{"text": prompt}])
    print("Gemini Response:\n", result)

def test_image_extraction():
    print("\n=== 2. Testing Image Extraction (Multimodal PNG) ===")
    img_path = os.path.join("dataset", "evidence", "images", "account_admin_console_20260926.png")
    if not os.path.exists(img_path):
        print(f"Image not found at {img_path}")
        return

    with open(img_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = "Extract all key information visible in this admin console screenshot: system/portal name, user_id, emails, timestamps, statuses, and any account identifiers."
    parts = [
        {"text": prompt},
        {
            "inline_data": {
                "mime_type": "image/png",
                "data": img_b64
            }
        }
    ]
    result = call_gemini(parts)
    print("Gemini Image Extraction:\n", result)

def test_pdf_extraction():
    print("\n=== 3. Testing PDF Document Extraction (Multimodal PDF) ===")
    pdf_path = os.path.join("dataset", "evidence", "documents", "legal_retention_register_20260529.pdf")
    if not os.path.exists(pdf_path):
        print(f"PDF not found at {pdf_path}")
        return

    with open(pdf_path, "rb") as f:
        pdf_b64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = "Summarize this legal retention register document: list user IDs, retention reasons, dates, legal hold statuses, or references mentioned."
    parts = [
        {"text": prompt},
        {
            "inline_data": {
                "mime_type": "application/pdf",
                "data": pdf_b64
            }
        }
    ]
    result = call_gemini(parts)
    print("Gemini PDF Extraction:\n", result)

if __name__ == "__main__":
    test_intent_classification()
    test_image_extraction()
    test_pdf_extraction()
