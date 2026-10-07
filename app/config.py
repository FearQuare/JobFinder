"""Paths and constants shared across the app."""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("JOBFINDER_DATA_DIR", PROJECT_ROOT / "data")).expanduser()
DB_PATH = DATA_DIR / "jobfinder.db"
LINKEDIN_PROFILE_DIR = DATA_DIR / "linkedin-browser-profile"
SECRETS_FALLBACK_PATH = DATA_DIR / "secrets.json"

# Host names the web app answers to. Anything else is refused, which stops DNS-rebinding pages from reading
# the app through a domain that resolves to 127.0.0.1. Add more with JOBFINDER_ALLOWED_HOSTS="a,b".
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"} | {
    h.strip().lower() for h in os.environ.get("JOBFINDER_ALLOWED_HOSTS", "").split(",") if h.strip()
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

DEFAULT_AI_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_OPENAI_MODEL = "gpt-6-luna"

# Role categories used by both the rule-based classifier and the AI extractor.
CATEGORIES = {
    "devops_cloud": "DevOps / Cloud / SRE",
    "backend": "Backend",
    "frontend": "Frontend",
    "fullstack": "Full-stack",
    "software_general": "Software Engineering (general)",
    "mobile": "Mobile",
    "qa_testing": "QA / Testing",
    "data_ai": "Data / ML / AI",
    "security": "Security",
    "embedded": "Embedded / Firmware",
    "it_ops": "IT Operations / Sysadmin / Support",
    "other": "Not a software role",
}

SENIORITIES = {
    "entry": "Entry (student / intern)",
    "junior": "Junior",
    "mid": "Mid-level",
    "senior": "Senior",
    "lead": "Lead / Principal",
    "unspecified": "Unspecified",
}

JOB_TYPES = {
    "full_time": "Full-time",
    "part_time": "Part-time",
    "working_student": "Working student",
    "internship": "Internship",
    "apprenticeship": "Apprenticeship",
    "freelance": "Freelance / Contract",
    "unspecified": "Unspecified",
}

SOURCES = {
    "karriere": "karriere.at",
    "linkedin": "LinkedIn",
    "adzuna": "Adzuna",
}

# Default search profiles created on first start. Users can edit them in the UI.
DEFAULT_SEARCHES = [
    ("DevOps / Cloud / SRE", ["DevOps", "Site Reliability Engineer", "Platform Engineer", "Cloud Engineer"]),
    ("Software Engineering", ["Software Engineer", "Software Developer", "Softwareentwickler"]),
    ("Backend / Frontend / Full-stack", ["Backend Developer", "Frontend Developer", "Full Stack Developer"]),
    ("QA / Test Automation", ["QA Engineer", "Test Automation", "Software Tester"]),
    ("Data / ML", ["Data Engineer", "Data Scientist", "Machine Learning Engineer"]),
    ("Working student & internships (IT)", ["Werkstudent IT", "Werkstudent Software", "Praktikum Software", "Working Student Developer"]),
]
