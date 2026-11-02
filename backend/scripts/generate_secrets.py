import secrets
import string

def generate_secure_string(length: int = 64) -> str:
    """Generate a cryptographically secure random string with high entropy."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*(-_=+)"
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def generate_hex_string(bytes_count: int = 32) -> str:
    """Generate a clean high-entropy hexadecimal secret."""
    return secrets.token_hex(bytes_count)

def main():
    print("==================================================")
    print("[SECURITY] Akriti PathLab -- Production Secrets Generator")
    print("==================================================")
    print("\nCopy and paste the following keys into your Render Dashboard / .env:\n")
    
    print(f"JWT_SECRET_KEY=\"{generate_secure_string(64)}\"")
    print(f"PASSWORD_PEPPER=\"{generate_hex_string(32)}\"")
    print(f"AADHAAR_PEPPER=\"{generate_hex_string(32)}\"")
    print(f"WHATSAPP_SERVICE_TOKEN=\"{generate_hex_string(24)}\"")
    
    print("\n==================================================")
    print("[WARNING] Never share these keys or commit them to public Git.")
    print("==================================================")

if __name__ == "__main__":
    main()
