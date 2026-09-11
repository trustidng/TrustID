"""Idempotently prepare Phase 11 administrator and organization demo accounts.

This preserves the existing synthetic citizen and licence authorities.
"""
from pathlib import Path
import sys

import mysql.connector
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.security import hash_password, new_organisation_reference  # noqa: E402

DEMO_PASSWORD = "NeuGombe@2026"

ADMINISTRATORS = [
    ("admin", "NEU Neural Defender", "admin@trustid.com", "SUPER_ADMIN"),
    ("vaisah.zirra", "Vaisah Peter Zirra", "vaisahzirra7@gmail.com", "ADMIN"),
    ("abubakar.ibrahim", "Abubakar Sadiq Ibrahim", "abubakarsadiqibrahim4321@gmail.com", "ADMIN"),
]

ORGANISATIONS = [
    ("Arewa Family Mart", "hello@arewafamilymart.test", "+2348037001101", "RETAIL", "RC-RET-1001", "Confirm age and identity status for restricted purchases."),
    ("Coastal Choice Stores", "support@coastalchoice.test", "+2348067001102", "RETAIL", "RC-RET-1002", "Verify customer eligibility while collecting minimal information."),
    ("Unity Home Supplies", "contact@unityhomesupplies.test", "+2348137001103", "RETAIL", "RC-RET-1003", "Confirm age requirements for selected products and services."),
    ("Savanna Market Hub", "service@savannamarket.test", "+2348167001104", "RETAIL", "RC-RET-1004", "Confirm valid identity records for trusted customer transactions."),
    ("NorthBridge Microfinance", "operations@northbridgefinance.test", "+2347037001201", "FINANCIAL", "RC-FIN-2001", "Support customer onboarding and regulated identity verification."),
    ("CedarTrust Finance", "compliance@cedartrust.test", "+2347067001202", "FINANCIAL", "RC-FIN-2002", "Verify customer information for financial-service applications."),
    ("Horizon Cooperative Bank", "identity@horizoncooperative.test", "+2348107001203", "FINANCIAL", "RC-FIN-2003", "Confirm applicant identity and approved address information."),
    ("Gombe Community Credit", "help@gombecredit.test", "+2348147001204", "FINANCIAL", "RC-FIN-2004", "Complete privacy-conscious member onboarding and eligibility checks."),
    ("National Skills Support Programme", "desk@skillssupport.test", "+2349037001301", "PROGRAMME_OPERATOR", "RC-PRO-3001", "Confirm applicant eligibility for training and support programmes."),
    ("GreenFuture Grant Initiative", "applications@greenfuture.test", "+2349067001302", "PROGRAMME_OPERATOR", "RC-PRO-3002", "Verify beneficiary eligibility and approved identity information."),
    ("Community Health Access Scheme", "enrolment@healthaccess.test", "+2347057001303", "PROGRAMME_OPERATOR", "RC-PRO-3003", "Confirm enrolment requirements for community support services."),
    ("Youth Enterprise Network", "verify@youthenterprise.test", "+2349157001304", "PROGRAMME_OPERATOR", "RC-PRO-3004", "Verify programme applicants without collecting full identity records."),
    ("Federal Citizen Services Office", "services@citizenoffice.gov.test", "+2349017001401", "GOVERNMENT", "MDA-GOV-4001", "Support secure citizen eligibility and service-access verification."),
    ("Gombe Social Support Agency", "intake@gombesupport.gov.test", "+2349027001402", "GOVERNMENT", "MDA-GOV-4002", "Confirm applicant information for public support programmes."),
    ("Regional Housing Services Board", "applications@housingboard.gov.test", "+2348037001403", "GOVERNMENT", "MDA-GOV-4003", "Verify approved applicant details for housing services."),
    ("Public Scholarship Bureau", "awards@scholarshipbureau.gov.test", "+2348067001404", "GOVERNMENT", "MDA-GOV-4004", "Confirm scholarship applicant eligibility and identity information."),
    ("SahelLink Logistics", "verification@sahellink.test", "+2348137001501", "TRANSPORT_LOGISTICS", "RC-LOG-5001", "Verify driving licence status and class for driver onboarding."),
    ("MetroHaul Transport", "fleet@metrohaul.test", "+2348167001502", "TRANSPORT_LOGISTICS", "RC-LOG-5002", "Confirm driver licence eligibility for fleet assignments."),
    ("SwiftRoute Delivery", "drivers@swiftroute.test", "+2347037001503", "TRANSPORT_LOGISTICS", "RC-LOG-5003", "Verify licence status for delivery-partner registration."),
    ("Unity Transit Services", "compliance@unitytransit.test", "+2347067001504", "TRANSPORT_LOGISTICS", "RC-LOG-5004", "Confirm driver identity and licence requirements for transport services."),
]


def main() -> None:
    conn = mysql.connector.connect(host=settings.db_host, port=settings.db_port, user=settings.db_user,
                                   password=settings.db_password, database=settings.db_name, autocommit=False)
    try:
        cur = conn.cursor(dictionary=True)
        password_hash = hash_password(DEMO_PASSWORD)
        for username, full_name, email, role in ADMINISTRATORS:
            cur.execute("SELECT id FROM admin_users WHERE username=%s", (username,))
            existing = cur.fetchone()
            if existing:
                cur.execute("""UPDATE admin_users SET full_name=%s,email=%s,role=%s,active=TRUE,
                    password_hash=%s,must_change_password=FALSE,failed_login_attempts=0,locked_until=NULL
                    WHERE id=%s""", (full_name, email, role, password_hash, existing["id"]))
            else:
                cur.execute("""INSERT INTO admin_users
                    (username,full_name,email,role,active,password_hash,must_change_password)
                    VALUES (%s,%s,%s,%s,TRUE,%s,FALSE)""", (username, full_name, email, role, password_hash))

        # Preserve the historic record for audit continuity, but do not leave the
        # superseded administrator login active alongside the approved accounts.
        cur.execute("""UPDATE admin_users SET active=FALSE,failed_login_attempts=0,locked_until=NULL
            WHERE username='vaisahzirra7'""")
        cur.execute("""DELETE s FROM auth_sessions s JOIN admin_users a ON a.id=s.actor_id
            WHERE s.actor_type='ADMIN' AND a.username='vaisahzirra7'""")

        for name, email, phone, category_code, registration, intended_use in ORGANISATIONS:
            cur.execute("SELECT id FROM organisation_categories WHERE code=%s AND active=TRUE", (category_code,))
            category = cur.fetchone()
            if not category:
                raise RuntimeError(f"Missing active organization category: {category_code}")
            cur.execute("SELECT id FROM organisations WHERE email=%s", (email,))
            existing = cur.fetchone()
            if existing:
                cur.execute("""UPDATE organisations SET business_name=%s,phone=%s,category_id=%s,
                    status='APPROVED',registration_reference=%s,intended_use=%s,password_hash=%s,
                    status_reason=NULL,failed_login_attempts=0,locked_until=NULL WHERE id=%s""",
                    (name, phone, category["id"], registration, intended_use, password_hash, existing["id"]))
            else:
                cur.execute("""INSERT INTO organisations
                    (public_reference,business_name,email,phone,category_id,status,registration_reference,
                     intended_use,password_hash)
                    VALUES (%s,%s,%s,%s,%s,'APPROVED',%s,%s,%s)""",
                    (new_organisation_reference(), name, email, phone, category["id"], registration,
                     intended_use, password_hash))

        cur.execute("""UPDATE citizens SET pin_hash=%s,failed_pin_attempts=0,locked_until=NULL
            WHERE account_activated=TRUE""", (hash_password("13579"),))
        conn.commit()
        print(f"Prepared {len(ADMINISTRATORS)} administrators, {len(ORGANISATIONS)} organizations, "
              "and standardized all activated synthetic citizen PINs.")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
