import pytest

from app import classify
from app.ai import canonical_skill, normalise_result


def test_fingerprint_merges_gender_tags_and_legal_suffixes():
    a = classify.fingerprint("DevOps Engineer (m/w/d)", "KNAPP")
    b = classify.fingerprint("DevOps Engineer (all genders)", "KNAPP AG")
    c = classify.fingerprint("DevOps Engineer (w/m/x)", "Knapp GmbH")
    assert a == b == c
    assert classify.fingerprint("Senior DevOps Engineer", "KNAPP") != a


@pytest.mark.parametrize("title,category", [
    ("Senior DevOps Engineer (m/w/d) - Kubernetes", "devops_cloud"),
    ("Azure Platform Engineer (all genders)", "devops_cloud"),
    ("Site Reliability Engineer", "devops_cloud"),
    ("Test Automation Engineer", "qa_testing"),
    ("QA Engineer (w/m/d)", "qa_testing"),
    ("Data Engineer", "data_ai"),
    ("Frontend Developer React", "frontend"),
    ("Full Stack Developer", "fullstack"),
    ("Java Backend Developer", "backend"),
    ("Softwareentwickler C++", "software_general"),
    ("iOS Developer", "mobile"),
    ("IT Security Analyst", "security"),
    ("Werkstudent HR – Learning and Development", "other"),
    ("Mechanical Engineer", "other"),
])
def test_category(title, category):
    assert classify.classify_category(title) == category


@pytest.mark.parametrize("title,employment,job_type,seniority", [
    ("Werkstudent Software Development (w/m/d)", None, "working_student", "entry"),
    ("Praktikum IT / DevOps", None, "internship", "entry"),
    ("Junior Software Developer", "Vollzeit", "full_time", "junior"),
    ("Senior DevOps Engineer", "Full-time", "full_time", "senior"),
    ("Lead Backend Engineer", None, "unspecified", "lead"),
    ("Software Engineer", "Teilzeit", "part_time", "unspecified"),
])
def test_type_and_seniority(title, employment, job_type, seniority):
    c = classify.classify(title, employment)
    assert c["job_type"] == job_type
    assert c["seniority"] == seniority


def test_seniority_from_linkedin_level():
    assert classify.classify_seniority("DevOps Engineer", "full_time", "Entry level") == "junior"
    assert classify.classify_seniority("DevOps Engineer", "full_time", "Mid-Senior level") == "senior"


def test_ai_normalisation():
    raw = {
        "category": "devops_cloud", "seniority": "junior", "job_type": "bogus", "years_experience_min": "2",
        "education": "bachelor", "remote_policy": "hybrid",
        "skills": [
            {"name": "K8s", "type": "tool_platform", "required": True},
            {"name": "kubernetes", "type": "tool_platform", "required": False},
            {"name": "Microsoft Azure", "type": "cloud", "required": True},
            {"name": "", "type": "cloud"},
        ],
        "languages": [{"language": "german", "level": "C1", "required": True}],
        "summary": "x",
    }
    out = normalise_result(raw)
    assert out["job_type"] == "unspecified"
    assert out["years_experience_min"] == 2
    assert [s["name"] for s in out["skills"]] == ["Kubernetes", "Azure"]
    assert out["languages"][0]["language"] == "German"
    assert canonical_skill("CI/CD pipelines") == "CI/CD"


def test_dotnet_keeps_its_dot():
    assert canonical_skill(".NET") == ".NET"
    assert canonical_skill("Docker.") == "Docker"
