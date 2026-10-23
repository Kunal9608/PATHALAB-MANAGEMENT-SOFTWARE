"""
Seed script — creates admin account + 65 tests from SRS Appendix A.
Run via: python -m backend.seed.seed
"""
import sys
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from backend.app.core.db import SessionLocal, init_db, enable_pgvector
from backend.app.core.security import hash_password
from backend.app.models.user import User, RoleEnum
from backend.app.models.test import Test
from backend.app.config import settings

TESTS_SEED = [
    ("CBC 5 Part", 230, "Haematology"),
    ("TC DC OF WBC", 60, "Haematology"),
    ("HB%", 65, "Haematology"),
    ("Blood Sugar(F)", 50, "Biochemistry"),
    ("Blood Sugar(R)", 50, "Biochemistry"),
    ("Blood Sugar Fasting/PP", 100, "Biochemistry"),
    ("Blood Urea", 200, "Biochemistry"),
    ("Urine Culture", 350, "Microbiology"),
    ("HIV 1&2 Test", 200, "Serology"),
    ("TB Platinum Test", 200, "Microbiology"),
    ("Para Check of P.F", 200, "Serology"),
    ("Lipid Profile", 400, "Biochemistry"),
    ("Para Check for (PV & PF)", 250, "Serology"),
    ("Para Screen for P.F", 150, "Serology"),
    ("Serum Electrolytes (Na,K,Cl)", 400, "Biochemistry"),
    ("Trust Test", 60, "Serology"),
    ("VDRL", 60, "Serology"),
    ("Vitamin D", 750, "Biochemistry"),
    ("Vitamin B12", 750, "Biochemistry"),
    ("Total Protein A/G Ratio", 200, "Biochemistry"),
    ("Dengue (IgE/IgM)", 500, "Serology"),
    ("Testosterone Total", 500, "Hormones"),
    ("R/E of Urine", 100, "Routine"),
    ("Stool R/E", 150, "Routine"),
    ("Micral Test Albumin Urine", 250, "Biochemistry"),
    ("Aldehyde", 150, "Biochemistry"),
    ("Serum Calcium", 180, "Biochemistry"),
    ("T3,T4,TSH", 450, "Hormones"),
    ("Thyroid Profile (FT3,FT4,TSH)", 650, "Hormones"),
    ("PSA", 450, "Hormones"),
    ("HbA1c", 250, "Biochemistry"),
    ("Preg Colour", 50, "Serology"),
    ("Parahit Total", 230, "Serology"),
    ("Triglyceride", 200, "Biochemistry"),
    ("Cholesterol", 200, "Biochemistry"),
    ("Montox Test 5TU/10TU", 150, "Microbiology"),
    ("IgE", 450, "Immunology"),
    ("HBsAg", 200, "Serology"),
    ("HCV", 220, "Serology"),
    ("Blood Group and Rh Typing", 100, "Haematology"),
    ("R.A. Test", 250, "Serology"),
    ("Hypertension Profile", 850, "Profiles"),
    ("Arthritis Profile", 750, "Profiles"),
    ("Serum Bilirubin", 200, "Biochemistry"),
    ("SGPT", 100, "Biochemistry"),
    ("SGOT", 100, "Biochemistry"),
    ("LFT", 500, "Profiles"),
    ("KFT", 500, "Profiles"),
    ("Serum Creatinine", 200, "Biochemistry"),
    ("Serum Uric Acid", 200, "Biochemistry"),
    ("Diabetic Profile", 850, "Profiles"),
    ("Kidney Profile", 850, "Profiles"),
    ("ASO Titer", 250, "Serology"),
    ("CRP (Quantitative Test)", 300, "Serology"),
    ("Widal", 180, "Serology"),
    ("PBS for MP", 100, "Haematology"),
    ("RK 39", 650, "Serology"),
    ("PT/INR", 230, "Haematology"),
    ("USG Whole Abdomen", 650, "Radiology"),
    ("USG Upper Abdomen", 550, "Radiology"),
    ("USG Lower Abdomen", 550, "Radiology"),
    ("USG Uterus and Adnexa", 550, "Radiology"),
    ("USG Fetal Profile", 550, "Radiology"),
    ("ECG", 250, "Cardiology"),
    ("Anemia Profile (HB%, CBC, Iron, TIBC, Ferritin)", 1000, "Profiles"),
]


def seed():
    print("\nRunning seed script...")
    db = SessionLocal()
    try:
        # Prevent slow DDL execution on every startup in production
        if os.getenv("FORCE_INIT_DB", "false").lower() == "true":
            print("  [INFO] Running database initialization (DDL)...")
            enable_pgvector(db)
            init_db()

        # ── Admin account ──────────────────────────────────────────────────
        from backend.app.repositories.user_repo import normalize_email
        admin_email = normalize_email(settings.ADMIN_SEED_EMAIL)
        existing_admin = db.query(User).filter(User.email == admin_email).first()
        
        if not existing_admin:
            import secrets
            import string
            # Generate a random temporary password
            chars = string.ascii_letters + string.digits
            temp_pwd = "".join(secrets.choice(chars) for _ in range(12))
            
            admin = User(
                role=RoleEnum.admin,
                name="Admin",
                email=admin_email,
                password_hash=hash_password(temp_pwd),
                is_active=True,
                must_reset_password=True,  # Force password reset on first login
                face_registered=False,
            )
            db.add(admin)
            db.flush()
            print(f"  [OK] Admin account created: {admin_email}")
            if settings.is_production:
                print("  [SECURITY] Temporary admin password provisioned. Check deployment bootstrap channel; must reset on first login.")
            else:
                # In development, write to local private file to avoid terminal capture
                try:
                    with open(".admin_bootstrap_token", "w") as f:
                        f.write(f"{admin_email}:{temp_pwd}\n")
                    print("  [INFO] Temporary bootstrap credentials saved to local .admin_bootstrap_token (non-production only).")
                except Exception:
                    print("  [INFO] Temporary admin password provisioned.")
        else:
            # Do NOT reset or overwrite password on restart if admin already exists
            existing_admin.email = admin_email
            existing_admin.is_active = True
            db.flush()
            print(f"  [OK] Admin account verified: {admin_email}")

        # ── 65 Tests ────────────────────────────────────────────────────────
        existing_test_names = {r[0] for r in db.query(Test.name).all()}
        inserted = 0
        for name, price, category in TESTS_SEED:
            if name not in existing_test_names:
                test = Test(name=name, price=price, category=category)
                db.add(test)
                inserted += 1

        db.commit()

        # Backfill any missing test codes
        from backend.app.repositories.test_repo import backfill_test_codes
        backfill_test_codes(db)

        # Backfill any missing staff codes
        from backend.app.services.staff_service import backfill_staff_codes
        backfill_staff_codes(db)

        # Seed standard test parameters
        from backend.seed.seed_parameters import seed_test_parameters
        seeded_params_count = seed_test_parameters(db)
        print(f"  [OK] Seeded parameters for {seeded_params_count} tests")

        print(f"  [OK] {inserted} tests inserted ({len(TESTS_SEED) - inserted} already existed)")
        print("\nSeed completed successfully!")

    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        print(f"  [ERROR] Seed failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
