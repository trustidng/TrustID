"""
TrustID — Phase 1 synthetic data generator.

Generates fake NIMC-style identity records and FRSC-style licence records
for demo/testing. No real personal data is used anywhere in this script.

Idempotent: truncates and reseeds every table it touches, so it's safe to
re-run before a judge demo to get back to a known, clean state.

Usage:
    1. Run schema.sql against your MySQL database first.
    2. Copy .env.example to .env and fill in your DB credentials.
    3. pip install -r requirements.txt
    4. python seed_data.py
"""

import os
import random
import string
import bcrypt
from datetime import date, timedelta
from faker import Faker
import mysql.connector
from dotenv import load_dotenv
from prepare_phase11_demo_data import ADMINISTRATORS, DEMO_PASSWORD, ORGANISATIONS

load_dotenv()

fake = Faker()
random.seed(42)  # deterministic demo data — same seed every run

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "trustid"),
}

NIGERIAN_STATES = [
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue",
    "Borno", "Cross River", "Delta", "Ebonyi", "Edo", "Ekiti", "Enugu",
    "FCT - Abuja", "Gombe", "Imo", "Jigawa", "Kaduna", "Kano", "Katsina",
    "Kebbi", "Kogi", "Kwara", "Lagos", "Nasarawa", "Niger", "Ogun", "Ondo",
    "Osun", "Oyo", "Plateau", "Rivers", "Sokoto", "Taraba", "Yobe", "Zamfara",
]

# Valid-ish Nigerian mobile network prefixes for plausible synthetic numbers
NETWORK_PREFIXES = ["803", "806", "813", "816", "703", "706", "810", "814",
                     "903", "906", "705", "915", "901", "902"]

LICENCE_CLASSES = ["A", "B", "C", "D", "E"]
ADDRESS_LOCATIONS = [
    "Unity Road", "Independence Avenue", "Community Close", "Market Road",
    "College Estate", "New Layout", "Peace Crescent", "Station Road",
    "Government Reservation Area", "Garden Close",
]
IDENTITY_PROFILES = [
    ("Zainab", "Musa", "Abubakar", "FEMALE"), ("Musa", "Sani", "Abdullahi", "MALE"),
    ("Aisha", "Ibrahim", "Bello", "FEMALE"), ("Ibrahim", "Sadiq", "Suleiman", "MALE"),
    ("Aishatu", "Anisa", "Lawal", "FEMALE"), ("Sani", "Musa", "Danladi", "MALE"),
    ("Yasmin", "Fatima", "Usman", "FEMALE"), ("Bashir", None, "Adamu", "MALE"),
    ("Chiamaka", "Adaeze", "Okafor", "FEMALE"), ("Chinedu", "Emeka", "Nwosu", "MALE"),
    ("Adaeze", "Ngozi", "Eze", "FEMALE"), ("Obinna", "Chukwuemeka", "Onyeka", "MALE"),
    ("Ngozi", None, "Umeh", "FEMALE"), ("Ifeanyi", "Chibuzo", "Obi", "MALE"),
    ("Amarachi", "Chioma", "Nnamani", "FEMALE"), ("Kelechi", None, "Ibekwe", "MALE"),
    ("Temilade", "Abiola", "Adebayo", "FEMALE"), ("Adewale", "Babatunde", "Ogunleye", "MALE"),
    ("Yetunde", None, "Balogun", "FEMALE"), ("Oluwaseun", "Adekunle", "Adeyemi", "MALE"),
    ("Ayomide", "Tolulope", "Fashola", "FEMALE"), ("Babatunde", "Olumide", "Oladipo", "MALE"),
    ("Bisola", "Temitope", "Akinyemi", "FEMALE"), ("Femi", None, "Ajayi", "MALE"),
    ("Iniobong", "Mfon", "Okon", "FEMALE"), ("Aniefiok", "Udo", "Essien", "MALE"),
    ("Mfon", None, "Etim", "FEMALE"), ("Imaobong", "Eno", "Ekanem", "FEMALE"),
    ("Terna", "Terseer", "Iorfa", "MALE"), ("Dooshima", "Mngohol", "Ortom", "FEMALE"),
    ("Tari", "Preye", "Briggs", "MALE"), ("Osaze", None, "Omoregie", "MALE"),
]
MALE_PORTRAITS = (1, 3, 6, 8, 9, 11, 14, 16)
FEMALE_PORTRAITS = (2, 4, 5, 7, 10, 12, 13, 15)
STATE_LGAS = {
    "Abia": "Umuahia North", "Adamawa": "Yola North", "Akwa Ibom": "Uyo",
    "Anambra": "Awka South", "Bauchi": "Bauchi", "Bayelsa": "Yenagoa",
    "Benue": "Makurdi", "Borno": "Maiduguri", "Cross River": "Calabar Municipal",
    "Delta": "Oshimili South", "Ebonyi": "Abakaliki", "Edo": "Oredo",
    "Ekiti": "Ado Ekiti", "Enugu": "Enugu North", "FCT - Abuja": "Abuja Municipal",
    "Gombe": "Gombe", "Imo": "Owerri Municipal", "Jigawa": "Dutse",
    "Kaduna": "Kaduna North", "Kano": "Kano Municipal", "Katsina": "Katsina",
    "Kebbi": "Birnin Kebbi", "Kogi": "Lokoja", "Kwara": "Ilorin West",
    "Lagos": "Ikeja", "Nasarawa": "Lafia", "Niger": "Chanchaga",
    "Ogun": "Abeokuta South", "Ondo": "Akure South", "Osun": "Osogbo",
    "Oyo": "Ibadan North", "Plateau": "Jos North", "Rivers": "Port Harcourt",
    "Sokoto": "Sokoto North", "Taraba": "Jalingo", "Yobe": "Damaturu",
    "Zamfara": "Gusau",
}


def synthetic_phone():
    prefix = random.choice(NETWORK_PREFIXES)
    line = "".join(random.choices(string.digits, k=7))
    return f"+234{prefix}{line}"


def synthetic_nin():
    return "".join(random.choices(string.digits, k=11))


def synthetic_address(state):
    """Generate a clearly fictional but locally plausible demo address."""
    return f"{random.randint(1, 199)} {random.choice(ADDRESS_LOCATIONS)}, {state}"


def synthetic_identity(index=None):
    first_name, middle_name, surname, gender = (
        IDENTITY_PROFILES[index % len(IDENTITY_PROFILES)]
        if index is not None else random.choice(IDENTITY_PROFILES)
    )
    full_name = " ".join(part for part in (first_name, middle_name, surname) if part)
    return full_name, surname, first_name, middle_name, gender


def name_parts(full_name):
    parts = full_name.split()
    return parts[-1], parts[0], " ".join(parts[1:-1]) or None


def photograph_reference(index, gender):
    portraits = MALE_PORTRAITS if gender == "MALE" else FEMALE_PORTRAITS
    return f"PHOTO-{portraits[index % len(portraits)]:04d}"


def random_dob(min_age, max_age, as_of=None):
    as_of = as_of or date.today()
    days_min = min_age * 365
    days_max = max_age * 365
    offset = random.randint(days_min, days_max)
    return as_of - timedelta(days=offset)


def exact_age_dob(age_years, as_of=None):
    """DOB that makes the citizen exactly `age_years` old today, for boundary tests."""
    as_of = as_of or date.today()
    return date(as_of.year - age_years, as_of.month, as_of.day)


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def reset_tables(cur):
    # Respect FK order
    tables = [
        "ussd_sessions", "sms_deliveries", "otp_challenges", "phone_sessions", "auth_sessions",
        "request_history", "audit_log", "controlled_disclosures", "consent_request_contexts", "consent_requests", "receipts",
        "identity_photo_rate_limits", "authenticity_rate_limits",
        "verifications", "licences", "citizens", "organisations",
        "category_claim_permissions", "organisation_categories", "claim_definitions", "admin_users",
    ]
    cur.execute("SET FOREIGN_KEY_CHECKS = 0")
    for t in tables:
        cur.execute(f"TRUNCATE TABLE {t}")
    cur.execute("SET FOREIGN_KEY_CHECKS = 1")


def seed_admin(cur):
    for username, full_name, email, role in ADMINISTRATORS:
        cur.execute("""INSERT INTO admin_users
            (username,full_name,email,role,active,password_hash,must_change_password)
            VALUES (%s,%s,%s,%s,TRUE,%s,FALSE)""",
            (username, full_name, email, role, hash_password(DEMO_PASSWORD)))
    print(f"Seeded {len(ADMINISTRATORS)} administrator accounts")


def seed_policy_catalog(cur):
    claims = [
        ("AGE_COMPARE", "Verify age requirement", "VERIFY", "INSTANT"),
        ("IDENTITY_STATUS", "Verify identity record", "VERIFY", "INSTANT"),
        ("LICENCE_STATUS", "Verify driving licence status", "VERIFY", "INSTANT"),
        ("LICENCE_CLASS", "Verify driving licence class", "VERIFY", "INSTANT"),
        ("FULL_LEGAL_NAME", "Request legal name", "REQUEST", "CONSENT"),
        ("STATE_OF_ORIGIN", "Request state of origin", "REQUEST", "CONSENT"),
        ("RESIDENTIAL_ADDRESS", "Request residential address", "REQUEST", "STRONG_CONSENT"),
        ("NAME_MATCH", "Verify name match", "VERIFY", "INSTANT"),
        ("REGISTERED_RESIDENCE", "Verify registered residence", "VERIFY", "STRONG_CONSENT"),
    ]
    cur.executemany("""INSERT INTO claim_definitions
        (claim_code,display_name,action_type,privacy_mode) VALUES (%s,%s,%s,%s)""", claims)
    categories = [
        ("RETAIL", "Retail", "Retailers and small vendors"),
        ("PROGRAMME_OPERATOR", "Programme operator", "Eligibility and support programme operators"),
        ("GOVERNMENT", "Government", "Government service organizations"),
        ("FINANCIAL", "Financial", "Banks, financial institutions and financial-service providers"),
        ("TRANSPORT_LOGISTICS", "Transport and logistics", "Transport, delivery and logistics organizations"),
    ]
    cur.executemany("INSERT INTO organisation_categories (code,name,description) VALUES (%s,%s,%s)", categories)
    permissions = {
        "RETAIL": ("AGE_COMPARE", "IDENTITY_STATUS"),
        "PROGRAMME_OPERATOR": ("AGE_COMPARE", "IDENTITY_STATUS", "FULL_LEGAL_NAME", "STATE_OF_ORIGIN", "NAME_MATCH", "REGISTERED_RESIDENCE"),
        "GOVERNMENT": ("AGE_COMPARE", "IDENTITY_STATUS", "FULL_LEGAL_NAME", "STATE_OF_ORIGIN", "RESIDENTIAL_ADDRESS", "NAME_MATCH", "REGISTERED_RESIDENCE"),
        "FINANCIAL": ("AGE_COMPARE", "IDENTITY_STATUS", "FULL_LEGAL_NAME", "STATE_OF_ORIGIN", "RESIDENTIAL_ADDRESS", "NAME_MATCH", "REGISTERED_RESIDENCE"),
        "TRANSPORT_LOGISTICS": ("LICENCE_STATUS", "LICENCE_CLASS", "IDENTITY_STATUS", "NAME_MATCH"),
    }
    for code, claim_codes in permissions.items():
        cur.execute("SELECT id FROM organisation_categories WHERE code=%s", (code,))
        category_id = cur.fetchone()[0]
        cur.executemany("INSERT INTO category_claim_permissions (category_id,claim_code) VALUES (%s,%s)",
                        [(category_id, claim) for claim in claim_codes])
    print("Seeded policy claim catalogue and 5 organisation categories")


def seed_organisations(cur):
    for name, email, phone, category, registration, intended_use in ORGANISATIONS:
        cur.execute("SELECT id FROM organisation_categories WHERE code=%s", (category,))
        category_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO organisations
               (public_reference,business_name,email,phone,category_id,status,registration_reference,
                intended_use,password_hash)
               VALUES (%s,%s,%s,%s,%s,'APPROVED',%s,%s,%s)""",
            ("ORG-DEMO-" + registration.split("-")[-1], name, email, phone, category_id,
             registration, intended_use, hash_password(DEMO_PASSWORD)),
        )
    print(f"Seeded {len(ORGANISATIONS)} approved demo organizations across all categories")


def seed_citizens(cur, n=300):
    citizen_ids = []

    # --- Explicit boundary-case citizens for Phase 0 acceptance tests #3/#4 ---
    boundary_citizens = [(0, exact_age_dob(18)), (1, exact_age_dob(30))]
    for index, (profile_index, dob) in enumerate(boundary_citizens):
        state = random.choice(NIGERIAN_STATES)
        residence_state = random.choice(NIGERIAN_STATES)
        name, surname, first_name, middle_name, gender = synthetic_identity(profile_index)
        cur.execute(
            """INSERT INTO citizens
               (synthetic_nin,full_name,surname,first_name,middle_name,date_of_birth,gender,registered_phone,
                identity_status,record_status,state_of_origin,state_of_residence,lga_of_residence,
                residential_address,identity_photograph_reference,
                pin_hash, account_activated)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'VERIFIED','ACTIVE',%s,%s,%s,%s,%s,%s,TRUE)""",
            (synthetic_nin(),name,surname,first_name,middle_name,dob,gender,synthetic_phone(),
             state,residence_state,STATE_LGAS[residence_state],synthetic_address(residence_state),
             photograph_reference(index, gender),hash_pin("13579")),
        )
        citizen_ids.append(cur.lastrowid)

    # --- Bulk synthetic citizens ---
    for index in range(n):
        dob = random_dob(5, 85)  # includes minors deliberately, for negative test cases
        identity_status = random.choices(
            ["VERIFIED", "ACTIVE", "REVOKED"], weights=[80, 15, 5]
        )[0]
        record_status = random.choices(["ACTIVE", "INACTIVE"], weights=[95, 5])[0]
        activated = random.random() < 0.6  # not everyone has activated a TrustID account yet
        state = random.choice(NIGERIAN_STATES)
        residence_state = random.choice(NIGERIAN_STATES)
        full_name, surname, first_name, middle_name, gender = synthetic_identity(index + len(boundary_citizens))
        cur.execute(
            """INSERT INTO citizens
               (synthetic_nin,full_name,surname,first_name,middle_name,date_of_birth,gender,registered_phone,
                identity_status,record_status,state_of_origin,state_of_residence,lga_of_residence,
                residential_address,identity_photograph_reference,
                pin_hash, account_activated)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (synthetic_nin(),full_name,surname,first_name,middle_name,dob,gender,synthetic_phone(),
             identity_status,record_status,state,residence_state,STATE_LGAS[residence_state],synthetic_address(residence_state),
             photograph_reference(index + len(boundary_citizens), gender),
             hash_pin("13579") if activated else None, activated),
        )
        citizen_ids.append(cur.lastrowid)

    print(f"Seeded {len(citizen_ids)} citizens ({len(boundary_citizens)} boundary-case + {n} random)")
    return citizen_ids


def seed_licences(cur, citizen_ids, coverage=0.5):
    count = 0
    for cid in citizen_ids:
        if random.random() > coverage:
            continue
        cur.execute("""SELECT full_name,surname,first_name,middle_name,date_of_birth,gender,identity_photograph_reference
            FROM citizens WHERE citizen_id=%s""", (cid,))
        full_name, surname, first_name, middle_name, date_of_birth, gender, photo_reference = cur.fetchone()
        issue = fake.date_between(start_date="-10y", end_date="-1y")
        expiry_years = random.choice([-1, 1, 2, 3])  # some intentionally expired
        expiry = issue + timedelta(days=365 * random.randint(3, 5) + expiry_years * 30)
        status = "VALID"
        if expiry < date.today():
            status = "EXPIRED"
        elif random.random() < 0.05:
            status = "SUSPENDED"
        licence_number = "LIC-" + "".join(random.choices(string.digits, k=9))
        cur.execute(
            """INSERT INTO licences
               (licence_number,holder_full_name,holder_surname,holder_first_name,holder_middle_name,
                holder_date_of_birth,holder_gender,holder_photograph_reference,
                licence_class,issue_date,expiry_date,licence_status,record_status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ACTIVE')""",
            (licence_number,full_name,surname,first_name,middle_name,date_of_birth,gender,photo_reference,
             random.choice(LICENCE_CLASSES), issue, expiry, status),
        )
        count += 1

    independent_count = max(30, int(count * 0.35))
    for index in range(independent_count):
        issue = fake.date_between(start_date="-8y", end_date="-180d")
        expiry = issue + timedelta(days=365 * random.randint(3, 5))
        status = "EXPIRED" if expiry < date.today() else ("SUSPENDED" if random.random() < 0.05 else "VALID")
        independent_name, independent_surname, independent_first, independent_middle, gender = synthetic_identity(index + 7)
        cur.execute(
            """INSERT INTO licences
               (licence_number,holder_full_name,holder_surname,holder_first_name,holder_middle_name,
                holder_date_of_birth,holder_gender,holder_photograph_reference,
                licence_class,issue_date,expiry_date,licence_status,record_status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            ("LIC-" + "".join(random.choices(string.digits, k=9)),independent_name,
             independent_surname,independent_first,independent_middle,random_dob(18, 75),
             gender,photograph_reference(index + 7, gender), random.choice(LICENCE_CLASSES), issue, expiry, status,
             "INACTIVE" if random.random() < 0.03 else "ACTIVE"),
        )
    print(f"Seeded {count + independent_count} standalone licence records "
          f"({count} matching selected synthetic identity details; {independent_count} independent)")


def main():
    conn = mysql.connector.connect(**DB_CONFIG)
    cur = conn.cursor()
    try:
        reset_tables(cur)
        seed_policy_catalog(cur)
        seed_admin(cur)
        seed_organisations(cur)
        citizen_ids = seed_citizens(cur)
        seed_licences(cur, citizen_ids)
        conn.commit()
        print("\nSeed complete. Database is in a clean, demo-ready state.")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
