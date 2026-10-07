"""Rule-based classification from the job title (used until/unless AI analysis runs) and duplicate detection."""
from __future__ import annotations

import re
import unicodedata
from typing import Optional, Tuple

_GENDER_TAGS = re.compile(
    r"\((?:[mwfdxi*]\s*[/|,]\s*)+[mwfdxi*]\)|\((?:all|alle)\s+genders?\)|\(gn\)|\(w/m/d\)|\*innen|\(m/f/diverse\)",
    re.I,
)
_LEGAL_SUFFIX = re.compile(r"\b(gmbh|ag|se|kg|og|e\.?u\.?|co|ltd|inc|llc|gesmbh|holding|group|austria|österreich)\b\.?", re.I)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def normalize_title(title: str) -> str:
    t = _GENDER_TAGS.sub(" ", title or "")
    t = _fold(t)
    t = re.sub(r"[^a-z0-9+#]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def normalize_company(company: Optional[str]) -> str:
    c = _fold(company or "")
    c = _LEGAL_SUFFIX.sub(" ", c)
    c = re.sub(r"[^a-z0-9]+", " ", c)
    return re.sub(r"\s+", " ", c).strip()


def fingerprint(title: str, company: Optional[str]) -> str:
    return f"{normalize_title(title)}|{normalize_company(company)}"


# ---------- title rules ----------

def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I) is not None


def classify_job_type(title: str, employment_raw: Optional[str] = None) -> str:
    t = f"{title} {employment_raw or ''}"
    if _has(r"werkstudent|working student|studentische|student(?:ische)? (?:mitarbeit|job|assist)|studierende|student job", t):
        return "working_student"
    if _has(r"praktik|\bintern\b|internship|\bpraktikant|trainee program|\binternship\b|\bINTERN\b", t):
        return "internship"
    if _has(r"\blehr(?:e|ling|stelle)\b|apprentice", t):
        return "apprenticeship"
    if _has(r"freelanc|freiberuf|contractor|\bcontract\b|werkvertrag", t):
        return "freelance"
    if _has(r"teilzeit|part[- ]time|geringf", t):
        return "part_time"
    if _has(r"vollzeit|full[- ]time|permanent", t):
        return "full_time"
    return "unspecified"


def classify_seniority(title: str, job_type: str = "unspecified", seniority_raw: Optional[str] = None) -> str:
    if job_type in ("working_student", "internship", "apprenticeship"):
        return "entry"
    t = title or ""
    if _has(r"\b(head of|principal|staff|lead|leiter|leitung|teamlead|team lead|architect|architekt|chief|director|cto)\b", t):
        return "lead"
    if _has(r"\b(senior|sr\.?|expert|experte|experienced|erfahren)\b", t):
        return "senior"
    if _has(r"\b(junior|jr\.?|entry|graduate|absolvent|berufseinsteiger|einsteiger|young professional|trainee)\b", t):
        return "junior"
    if _has(r"\b(medior|mid[- ]level|intermediate|professional)\b", t):
        return "mid"
    raw = (seniority_raw or "").lower()
    if raw.startswith("internship"):
        return "entry"
    if raw.startswith("entry"):
        return "junior"
    if raw.startswith("associate"):
        return "mid"
    if raw.startswith("mid-senior"):
        return "senior"
    if raw.startswith(("director", "executive")):
        return "lead"
    return "unspecified"


_CATEGORY_RULES: Tuple[Tuple[str, str], ...] = (
    ("security", r"security|sicherheit|secops|pentest|penetration|soc analyst|cyber|iam engineer"),
    ("devops_cloud", r"devops|dev ops|\bsre\b|site reliability|platform engineer|plattform|cloud|kubernetes|infrastructure engineer|infrastruktur|\bops engineer|devsecops|mlops|release engineer|build engineer"),
    ("qa_testing", r"\bqa\b|quality assurance|test(?:er|ing|automation|automatisierung|engineer|manager|analyst)?\b|software test|qualit[aä]tssicherung"),
    ("data_ai", r"\bdata\b|daten|machine learning|\bml\b|\bai\b|\bki\b|artificial intelligence|deep learning|\bbi\b|business intelligence|analytics|llm|computer vision|\bnlp\b"),
    ("mobile", r"\bmobile\b|\bios\b|android|flutter|react native|swift|kotlin"),
    ("embedded", r"embedded|firmware|\bfpga\b|hardwarenah|\bplc\b|\bsps\b|automotive software|echtzeit"),
    ("fullstack", r"full[- ]?stack"),
    ("frontend", r"front[- ]?end|\bui\b developer|react|angular|vue|web developer|webentwickl"),
    ("backend", r"back[- ]?end|\bjava\b|\.net|c#|python developer|golang|\bgo developer|node\.?js|php|\bapi\b"),
    ("it_ops", r"system ?administrat|sysadmin|it[- ]support|helpdesk|service desk|it[- ]techniker|netzwerk|network engineer|\bit[- ]administrator|it[- ]operations|client[- ]management|workplace"),
    ("software_general", r"software|developer|entwickler|programmier|engineer|informatik|coder|\bdev\b"),
)


_NON_SOFTWARE = re.compile(
    r"mechani|maschinenbau|konstrukt|elektrotechn|electrical|elektriker|civil|bauingen|hochbau|tiefbau|verfahrens|"
    r"process engineer|chemi|sales|vertrieb|verkauf|\bhr\b|human resources|personal|recruit|marketing|buchhalt|"
    r"accountant|controlling|finance|finanz|lager|logistik|pflege|koch|kellner|montage|monteur|schlosser|"
    r"produktion|production|fertigung|einkauf|purchas|legal|jurist|steuer|tax",
    re.I,
)
_SOFTWARE_HINT = re.compile(r"software|\bit\b|devops|data|daten|cloud|developer|entwickler|programm|informatik|web|app\b", re.I)


def classify_category(title: str) -> str:
    t = _fold(title or "")
    if _NON_SOFTWARE.search(t) and not _SOFTWARE_HINT.search(t):
        return "other"
    for category, pattern in _CATEGORY_RULES:
        if re.search(pattern, t, re.I):
            return category
    return "other"


def classify(title: str, employment_raw: Optional[str] = None, seniority_raw: Optional[str] = None) -> dict:
    job_type = classify_job_type(title, employment_raw)
    return {
        "job_type": job_type,
        "seniority": classify_seniority(title, job_type, seniority_raw),
        "category": classify_category(title),
    }
