import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from supabase import create_client
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import base64
import os
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

class GenerateRequest(BaseModel):
    name: str = "there"

class SendEmailRequest(BaseModel):
    to: EmailStr
    subject: str
    body: str
    user_id: str

@app.get("/")
async def root():
    return {"message": "KnockKnock backend is running"}

@app.post("/generate")
async def generate_email(request: GenerateRequest):
    personalized_email = f"Hi {request.name}, I’d love to connect regarding internship opportunities."
    return {"emails": [personalized_email]}

@app.post("/send-email")
async def send_email(request: SendEmailRequest):
    try:
        tokens_resp = supabase.table("google_tokens").select("*").eq("user_id", request.user_id).single().execute()
        tokens = tokens_resp.data
        if not tokens or "refresh_token" not in tokens:
            logging.error(f"Missing refresh token for user {request.user_id}")
            raise HTTPException(status_code=403, detail="Missing refresh token for user")

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
        logging.info(f"Email sent to {request.to} for user {request.user_id}")
        return {"status": "sent"}
    except Exception as e:
        logging.error(f"Error sending email: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
