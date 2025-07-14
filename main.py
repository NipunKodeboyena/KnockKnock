from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import base64
import os
from dotenv import load_dotenv

load_dotenv()

# FastAPI app
app = FastAPI()

# Enable CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # You can restrict this to your frontend domain later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# Google credentials
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")


# Pydantic models
class GenerateRequest(BaseModel):
    name: str = "there"
    # add more fields later for scraping input


class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str
    user_id: str


@app.post("/generate")
def generate_email(request: GenerateRequest):
    # TODO: Replace this with actual scraping + Gemini generation logic
    personalized_email = f"Hi {request.name}, I’d love to connect regarding internship opportunities."
    return {"emails": [personalized_email]}


@app.post("/send-email")
def send_email(request: SendEmailRequest):
    try:
        # Fetch Gmail refresh token from Supabase
        tokens = supabase.table("google_tokens").select("*").eq("user_id", request.user_id).single().execute().data
        if not tokens or "refresh_token" not in tokens:
            raise HTTPException(status_code=403, detail="Missing refresh token for user")

        creds = Credentials(
            None,
            refresh_token=tokens["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET
        )
        creds.refresh(Request())

        # Compose and send email
        service = build("gmail", "v1", credentials=creds)
        raw_message = base64.urlsafe_b64encode(
            f"To:{request.to}\nSubject:{request.subject}\n\n{request.body}".encode("utf-8")
        ).decode()

        message = {"raw": raw_message}
        service.users().messages().send(userId="me", body=message).execute()

        return {"status": "sent"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
