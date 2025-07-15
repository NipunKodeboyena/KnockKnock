import logging
import base64
import os
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from supabase import create_client
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from dotenv import load_dotenv
import requests

# Load environment variables
load_dotenv()

# Logging
logging.basicConfig(level=logging.INFO)

# App setup
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Env vars
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Clients
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# Models
class GenerateRequest(BaseModel):
    user_id: str
    prompt: str
    job_title: str
    company: str

class SendEmailRequest(BaseModel):
    to: EmailStr
    subject: str
    body: str
    user_id: str

# Health check
@app.get("/")
async def root():
    return {"message": "KnockKnock backend is running"}

# Helper: Refresh credits monthly
def refresh_user_credits(user):
    plan = user["plan"]
    last_refresh = datetime.strptime(user["last_refresh"], "%Y-%m-%d").date()
    today = datetime.utcnow().date()

    if today > last_refresh + timedelta(days=30):
        new_credits = 100 if plan == "free" else 250
        supabase.table("users").update({
            "credits": new_credits,
            "last_refresh": today.isoformat()
        }).eq("id", user["id"]).execute()
        return new_credits
    return user["credits"]

# /generate - with credits + LLM
@app.post("/generate")
async def generate_email(request: GenerateRequest):
    # Get user
    user_resp = supabase.table("users").select("*").eq("id", request.user_id).single().execute()
    user = user_resp.data
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Refresh credits if needed
    credits = refresh_user_credits(user)
    if credits <= 0:
        raise HTTPException(status_code=403, detail="You’ve run out of credits. Upgrade to Pro or wait for monthly reset.")

    # Prompt LLM (Gemini)
    try:
        gemini_resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}",
            json={
                "contents": [{
                    "parts": [{
                        "text": f"Write a concise, friendly cold outreach email for someone applying to a job as {request.job_title} at {request.company}. Add context: {request.prompt}"
                    }]
                }]
            }
        )
        gemini_data = gemini_resp.json()
        email_text = gemini_data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logging.error(f"Gemini API error: {e}")
        raise HTTPException(status_code=500, detail="LLM generation failed")

    # Decrement credit
    supabase.table("users").update({"credits": credits - 1}).eq("id", user["id"]).execute()

    # Log to email_logs (optional)
    supabase.table("email_logs").insert({
        "user_id": user["id"],
        "email": email_text,
        "subject": f"Cold outreach for {request.job_title}",
        "body": email_text,
        "sent_at": datetime.utcnow().isoformat()
    }).execute()

    return {
        "email": email_text,
        "remaining_credits": credits - 1
    }

# /send-email - Gmail
@app.post("/send-email")
async def send_email(request: SendEmailRequest):
    try:
        tokens_resp = supabase.table("google_tokens").select("*").eq("user_id", request.user_id).single().execute()
        tokens = tokens_resp.data
        if not tokens or "refresh_token" not in tokens:
            raise HTTPException(status_code=403, detail="Missing refresh token")

        creds = Credentials(
            None,
            refresh_token=tokens["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET
        )
        creds.refresh(Request())

        service = build("gmail", "v1", credentials=creds)
        raw_message = base64.urlsafe_b64encode(
            f"To:{request.to}\nSubject:{request.subject}\n\n{request.body}".encode("utf-8")
        ).decode()
        message = {"raw": raw_message}
        service.users().messages().send(userId="me", body=message).execute()

        logging.info(f"Email sent to {request.to}")
        return {"status": "sent"}

    except Exception as e:
        logging.error(f"Send email error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
