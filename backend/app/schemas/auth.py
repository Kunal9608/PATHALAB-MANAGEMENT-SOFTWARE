"""Auth schemas — request/response DTOs."""
from pydantic import BaseModel, EmailStr
from typing import Optional


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    recaptcha_token: Optional[str] = None


class OtpRequestSchema(BaseModel):
    email: EmailStr
    purpose: str = "login"  # login | password_reset
    recaptcha_token: Optional[str] = None


class OtpVerifyRequest(BaseModel):
    email: EmailStr
    otp: Optional[str] = None
    otp_code: Optional[str] = None
    purpose: str = "login"


class PasswordResetRequest(BaseModel):
    reset_token: str
    new_password: str
    confirm_password: Optional[str] = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    requires_password_reset: bool = False


class LoginResponse(BaseModel):
    success: bool
    requires_password_reset: bool = False
    reset_token: Optional[str] = None
    user: Optional[dict] = None
    message: str = "Login successful"


class MessageResponse(BaseModel):
    message: str
    success: bool = True
