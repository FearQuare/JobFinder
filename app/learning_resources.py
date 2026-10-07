"""Curated, link-checked learning resources and roadmap.sh roadmaps.

The AI planner is shown the relevant entries and asked to use these URLs. Any URL it
invents that is not in this catalog (or on roadmap.sh / an allowed official domain)
is replaced with a web-search link, so the plan never shows a made-up link.

roadmap.sh content is not copied into the app (its license allows personal use and
linking, not republishing); the app links to the roadmap pages instead.
"""
from __future__ import annotations

from typing import Dict, List, Optional
from urllib.parse import quote_plus, urlparse

ROADMAP_BASE = "https://roadmap.sh/"

# slug -> title (from roadmap.sh/roadmaps, Sep 2026)
ROADMAPS: Dict[str, str] = {
    "devops": "DevOps", "devops-beginner": "DevOps Beginner", "devsecops": "DevSecOps", "backend": "Backend",
    "backend-beginner": "Backend Beginner", "frontend": "Frontend", "frontend-beginner": "Frontend Beginner",
    "full-stack": "Full Stack", "qa": "QA", "data-engineer": "Data Engineer", "data-analyst": "Data Analyst",
    "ai-data-scientist": "AI and Data Scientist", "machine-learning": "Machine Learning", "ai-engineer": "AI Engineer",
    "mlops": "MLOps", "cyber-security": "Cyber Security", "network-engineer": "Network Engineer", "android": "Android",
    "ios": "iOS", "flutter": "Flutter", "react-native": "React Native", "software-architect": "Software Architect",
    "computer-science": "Computer Science", "system-design": "System Design", "api-design": "API Design",
    "software-design-architecture": "Software Design & Architecture", "docker": "Docker", "kubernetes": "Kubernetes",
    "linux": "Linux", "terraform": "Terraform", "aws": "AWS", "shell-bash": "Shell / Bash", "git-github": "Git and GitHub",
    "python": "Python", "sql": "SQL", "postgresql-dba": "PostgreSQL", "mongodb": "MongoDB", "redis": "Redis",
    "javascript": "JavaScript", "typescript": "TypeScript", "nodejs": "Node.js", "react": "React", "vue": "Vue",
    "angular": "Angular", "nextjs": "Next.js", "java": "Java", "spring-boot": "Spring Boot", "aspnet-core": "ASP.NET Core",
    "golang": "Go", "rust": "Rust", "cpp": "C++", "c": "C Programming", "kotlin": "Kotlin", "php": "PHP", "scala": "Scala",
    "elasticsearch": "Elasticsearch", "cloudflare": "Cloudflare", "power-bi": "Power BI", "django": "Django",
    "datastructures-and-algorithms": "Data Structures & Algorithms", "prompt-engineering": "Prompt Engineering",
    "code-review-best-practices": "Code Review",
}

# Role category -> role roadmaps (beginner variant first for entry/junior targets)
ROLE_ROADMAPS: Dict[str, List[str]] = {
    "devops_cloud": ["devops-beginner", "devops"],
    "backend": ["backend-beginner", "backend"],
    "frontend": ["frontend-beginner", "frontend"],
    "fullstack": ["full-stack"],
    "software_general": ["backend-beginner", "computer-science"],
    "mobile": ["android", "ios", "flutter"],
    "qa_testing": ["qa"],
    "data_ai": ["data-engineer", "ai-data-scientist"],
    "security": ["cyber-security", "devsecops"],
    "embedded": ["cpp", "c"],
    "it_ops": ["linux", "network-engineer"],
}

# canonical skill (lowercase) -> roadmap slug
SKILL_ROADMAPS: Dict[str, str] = {
    "docker": "docker", "kubernetes": "kubernetes", "linux": "linux", "terraform": "terraform", "aws": "aws",
    "bash": "shell-bash", "shell scripting": "shell-bash", "git": "git-github", "github": "git-github",
    "python": "python", "sql": "sql", "postgresql": "postgresql-dba", "mongodb": "mongodb", "redis": "redis",
    "javascript": "javascript", "typescript": "typescript", "node.js": "nodejs", "react": "react", "vue": "vue",
    "angular": "angular", "next.js": "nextjs", "java": "java", "spring": "spring-boot", "spring boot": "spring-boot",
    "asp.net": "aspnet-core", ".net": "aspnet-core", "c#": "aspnet-core", "go": "golang", "rust": "rust", "c++": "cpp",
    "c": "c", "kotlin": "kotlin", "php": "php", "scala": "scala", "elasticsearch": "elasticsearch",
    "system design": "system-design", "rest apis": "api-design", "api design": "api-design", "rest": "api-design",
    "microservices": "software-architect", "software architecture": "software-architect",
    "data structures": "datastructures-and-algorithms", "algorithms": "datastructures-and-algorithms",
    "machine learning": "machine-learning", "mlops": "mlops", "power bi": "power-bi", "django": "django",
    "flutter": "flutter", "react native": "react-native", "android": "android", "ios": "ios",
    "devsecops": "devsecops", "security": "cyber-security", "networking": "network-engineer",
    "prompt engineering": "prompt-engineering", "code review": "code-review-best-practices",
}

# canonical skill / topic (lowercase) -> resources. URLs checked Sep 2026 (learngerman.dw.com blocks automated
# checks; it is DW's long-standing free German course site).
RESOURCES: Dict[str, List[dict]] = {
    "docker": [{"title": "Docker: Get started (official)", "url": "https://docs.docker.com/get-started/", "type": "docs", "free": True}],
    "kubernetes": [{"title": "Kubernetes tutorials (official)", "url": "https://kubernetes.io/docs/tutorials/", "type": "docs", "free": True},
                   {"title": "Certified Kubernetes Administrator (CKA)", "url": "https://training.linuxfoundation.org/certification/certified-kubernetes-administrator-cka/", "type": "certification", "free": False}],
    "helm": [{"title": "Helm quickstart (official)", "url": "https://helm.sh/docs/intro/quickstart/", "type": "docs", "free": True}],
    "terraform": [{"title": "HashiCorp Terraform tutorials", "url": "https://developer.hashicorp.com/terraform/tutorials", "type": "course", "free": True}],
    "ansible": [{"title": "Ansible getting started (official)", "url": "https://docs.ansible.com/ansible/latest/getting_started/index.html", "type": "docs", "free": True}],
    "aws": [{"title": "AWS Skill Builder (600+ free courses)", "url": "https://skillbuilder.aws/", "type": "course", "free": True},
            {"title": "AWS Certified Cloud Practitioner", "url": "https://aws.amazon.com/certification/certified-cloud-practitioner/", "type": "certification", "free": False}],
    "azure": [{"title": "Microsoft Learn: Azure training", "url": "https://learn.microsoft.com/en-us/training/azure/", "type": "course", "free": True},
              {"title": "Azure Fundamentals (AZ-900)", "url": "https://learn.microsoft.com/en-us/credentials/certifications/azure-fundamentals/", "type": "certification", "free": False}],
    "google cloud": [{"title": "Google Cloud training", "url": "https://cloud.google.com/learn/training", "type": "course", "free": True}],
    "linux": [{"title": "Linux Journey (free, interactive)", "url": "https://labex.io/linuxjourney", "type": "course", "free": True}],
    "bash": [{"title": "LinuxCommand.org: learning the shell", "url": "https://linuxcommand.org/", "type": "course", "free": True}],
    "git": [{"title": "Pro Git book (free)", "url": "https://git-scm.com/book/en/v2", "type": "book", "free": True}],
    "github actions": [{"title": "GitHub Actions documentation", "url": "https://docs.github.com/en/actions", "type": "docs", "free": True}],
    "gitlab ci": [{"title": "GitLab CI/CD documentation", "url": "https://docs.gitlab.com/ci/", "type": "docs", "free": True}],
    "jenkins": [{"title": "Jenkins tutorials (official)", "url": "https://www.jenkins.io/doc/tutorials/", "type": "docs", "free": True}],
    "ci/cd": [{"title": "GitHub Actions documentation", "url": "https://docs.github.com/en/actions", "type": "docs", "free": True}],
    "prometheus": [{"title": "Prometheus introduction (official)", "url": "https://prometheus.io/docs/introduction/overview/", "type": "docs", "free": True}],
    "grafana": [{"title": "Grafana tutorials", "url": "https://grafana.com/tutorials/", "type": "docs", "free": True}],
    "monitoring": [{"title": "Prometheus introduction (official)", "url": "https://prometheus.io/docs/introduction/overview/", "type": "docs", "free": True}],
    "python": [{"title": "The Python Tutorial (official)", "url": "https://docs.python.org/3/tutorial/", "type": "docs", "free": True}],
    "sql": [{"title": "PostgreSQL tutorial (official)", "url": "https://www.postgresql.org/docs/current/tutorial.html", "type": "docs", "free": True}],
    "postgresql": [{"title": "PostgreSQL tutorial (official)", "url": "https://www.postgresql.org/docs/current/tutorial.html", "type": "docs", "free": True}],
    "c#": [{"title": "Microsoft Learn: C#", "url": "https://learn.microsoft.com/en-us/dotnet/csharp/", "type": "docs", "free": True}],
    ".net": [{"title": "Microsoft Learn: .NET", "url": "https://learn.microsoft.com/en-us/dotnet/", "type": "docs", "free": True}],
    "java": [{"title": "dev.java: Learn Java (official)", "url": "https://dev.java/learn/", "type": "docs", "free": True}],
    "javascript": [{"title": "MDN: Learn web development", "url": "https://developer.mozilla.org/en-US/docs/Learn", "type": "course", "free": True}],
    "typescript": [{"title": "TypeScript handbook (official)", "url": "https://www.typescriptlang.org/docs/handbook/intro.html", "type": "docs", "free": True}],
    "react": [{"title": "react.dev: Learn React", "url": "https://react.dev/learn", "type": "docs", "free": True}],
    "go": [{"title": "A Tour of Go (official)", "url": "https://go.dev/tour/", "type": "course", "free": True}],
    "selenium": [{"title": "Selenium documentation", "url": "https://www.selenium.dev/documentation/", "type": "docs", "free": True}],
    "playwright": [{"title": "Playwright docs: getting started", "url": "https://playwright.dev/docs/intro", "type": "docs", "free": True}],
    "scrum": [{"title": "The Scrum Guide", "url": "https://scrumguides.org/scrum-guide.html", "type": "docs", "free": True}],
    "agile": [{"title": "The Scrum Guide", "url": "https://scrumguides.org/scrum-guide.html", "type": "docs", "free": True}],
    "german": [
        {"title": "DW Learn German (free A1–C1 courses)", "url": "https://learngerman.dw.com/", "type": "course", "free": True},
        {"title": "University of Vienna Language Centre – German courses", "url": "https://sprachenzentrum.univie.ac.at/en/", "type": "course", "free": False},
        {"title": "ÖSD – Austrian German language certificates", "url": "https://www.osd.at/en/", "type": "certification", "free": False},
    ],
    "english": [{"title": "British Council LearnEnglish", "url": "https://learnenglish.britishcouncil.org/", "type": "course", "free": True}],
}

# Official documentation domains the AI may link to even when not in RESOURCES.
TRUSTED_DOMAINS = {
    "roadmap.sh", "docs.docker.com", "kubernetes.io", "helm.sh", "developer.hashicorp.com", "docs.ansible.com",
    "aws.amazon.com", "docs.aws.amazon.com", "skillbuilder.aws", "learn.microsoft.com", "cloud.google.com",
    "docs.github.com", "docs.gitlab.com", "www.jenkins.io", "prometheus.io", "grafana.com", "docs.python.org",
    "www.postgresql.org", "dev.java", "developer.mozilla.org", "www.typescriptlang.org", "react.dev", "go.dev",
    "www.selenium.dev", "playwright.dev", "scrumguides.org", "git-scm.com", "www.osd.at", "learngerman.dw.com",
    "sprachenzentrum.univie.ac.at", "learnenglish.britishcouncil.org", "training.linuxfoundation.org",
    "labex.io", "linuxcommand.org", "www.rust-lang.org", "doc.rust-lang.org", "angular.dev", "vuejs.org",
    "nodejs.org", "spring.io", "kotlinlang.org", "www.cncf.io", "opentelemetry.io", "docs.docker.com",
}

KNOWN_URLS = {r["url"] for lst in RESOURCES.values() for r in lst}


def roadmap_url(slug: str) -> str:
    return ROADMAP_BASE + slug


def roadmap_for_skill(skill: str) -> Optional[dict]:
    slug = SKILL_ROADMAPS.get((skill or "").strip().lower())
    return {"title": f"roadmap.sh: {ROADMAPS[slug]}", "url": roadmap_url(slug)} if slug else None


def role_roadmaps(categories: List[str], seniorities: List[str]) -> List[dict]:
    beginner = not seniorities or any(s in ("entry", "junior", "unspecified") for s in seniorities)
    out, seen = [], set()
    for cat in categories:
        for slug in ROLE_ROADMAPS.get(cat, []):
            if slug.endswith("-beginner") and not beginner:
                continue
            if slug not in seen:
                seen.add(slug)
                out.append({"title": ROADMAPS[slug], "url": roadmap_url(slug), "slug": slug})
    return out


def resources_for(skill: str) -> List[dict]:
    return list(RESOURCES.get((skill or "").strip().lower(), []))


def catalog_for_prompt(skills: List[str]) -> Dict[str, List[dict]]:
    """Subset of the catalog relevant to these skills, for the AI prompt."""
    out: Dict[str, List[dict]] = {}
    for s in skills:
        key = (s or "").strip().lower()
        items = list(RESOURCES.get(key, []))
        rm = roadmap_for_skill(s)
        if rm:
            items.append({**rm, "type": "roadmap", "free": True})
        if items:
            out[s] = items
    return out


def search_url(query: str) -> str:
    return "https://duckduckgo.com/?q=" + quote_plus(query)


def safe_resource(res: dict, topic: str) -> dict:
    """Keep catalog/trusted URLs; replace anything else with a search link for the resource title."""
    url = (res.get("url") or "").strip()
    title = (res.get("title") or topic).strip()
    host = urlparse(url).netloc.lower() if url.startswith(("http://", "https://")) else ""
    if url in KNOWN_URLS or host in TRUSTED_DOMAINS:
        if host == "roadmap.sh":
            slug = urlparse(url).path.strip("/").split("/")[0]
            if slug not in ROADMAPS:
                return {**res, "title": title, "url": search_url(f"roadmap.sh {topic}"), "verified": False}
        return {**res, "title": title, "url": url, "verified": True}
    return {**res, "title": title, "url": search_url(title), "verified": False}


# ---------------------------------------------------------------- roadmaps beyond roadmap.sh
# Role curricula, learning paths and portfolio challenges from several providers (all links checked Sep 2026).
# kind: roadmap | learning_path | curriculum | book | project | practice
LEARNING_PATHS: Dict[str, dict] = {
    "ms-devops-career": {"title": "Microsoft Learn: DevOps Engineer career path", "provider": "Microsoft",
                         "url": "https://learn.microsoft.com/en-us/training/career-paths/devops-engineer", "kind": "learning_path", "free": True,
                         "note": "Structured Azure DevOps learning paths leading to AZ-400."},
    "aws-ramp-up": {"title": "AWS Ramp-Up Guides (DevOps, Developer, SysOps…)", "provider": "AWS",
                    "url": "https://aws.amazon.com/training/ramp-up-guides/", "kind": "learning_path", "free": True,
                    "note": "Role-based study sequences for AWS, from fundamentals to certification."},
    "milanm-devops": {"title": "DevOps Roadmap (milanm, ~20k★)", "provider": "GitHub community",
                      "url": "https://github.com/milanm/DevOps-Roadmap", "kind": "roadmap", "free": True,
                      "note": "Step-by-step DevOps roadmap with curated free resources per step."},
    "90daysofdevops": {"title": "90DaysOfDevOps (~30k★)", "provider": "GitHub community",
                       "url": "https://github.com/MichaelCade/90DaysOfDevOps", "kind": "curriculum", "free": True,
                       "note": "Daily hands-on DevOps learning journey: Linux, Git, containers, Kubernetes, IaC, CI/CD."},
    "cloud-resume-challenge": {"title": "The Cloud Resume Challenge", "provider": "Forrest Brazeal",
                               "url": "https://cloudresumechallenge.dev/", "kind": "project", "free": True,
                               "note": "16-step portfolio project (cloud, IaC, CI/CD, DNS) that employers recognise."},
    "k8s-hard-way": {"title": "Kubernetes The Hard Way (~50k★)", "provider": "Kelsey Hightower",
                     "url": "https://github.com/kelseyhightower/kubernetes-the-hard-way", "kind": "practice", "free": True,
                     "note": "Build a cluster by hand to deeply understand Kubernetes (great CKA prep)."},
    "devops-exercises": {"title": "DevOps Exercises & interview questions (~84k★)", "provider": "GitHub community",
                         "url": "https://github.com/bregman-arie/devops-exercises", "kind": "practice", "free": True,
                         "note": "Thousands of questions across Linux, Docker, Kubernetes, cloud — for interview prep."},
    "google-sre-books": {"title": "Google SRE books (free online)", "provider": "Google",
                         "url": "https://sre.google/books/", "kind": "book", "free": True,
                         "note": "The reference books on Site Reliability Engineering."},
    "ossu-cs": {"title": "OSSU Computer Science (~200k★)", "provider": "Open Source Society University",
                "url": "https://github.com/ossu/computer-science", "kind": "curriculum", "free": True,
                "note": "A full CS degree curriculum from free online courses — fills theory gaps."},
    "system-design-primer": {"title": "System Design Primer (~360k★)", "provider": "GitHub community",
                             "url": "https://github.com/donnemartin/system-design-primer", "kind": "book", "free": True,
                             "note": "Scalability, databases, caching — standard prep for system-design interviews."},
    "fullstack-open": {"title": "Full Stack Open (University of Helsinki)", "provider": "University of Helsinki",
                       "url": "https://fullstackopen.com/en/", "kind": "curriculum", "free": True,
                       "note": "University-grade React/Node/TypeScript/CI course with exercises."},
    "odin-project": {"title": "The Odin Project", "provider": "The Odin Project",
                     "url": "https://www.theodinproject.com/", "kind": "curriculum", "free": True,
                     "note": "Project-based full-stack web development curriculum."},
    "freecodecamp": {"title": "freeCodeCamp curriculum & certifications", "provider": "freeCodeCamp",
                     "url": "https://www.freecodecamp.org/learn", "kind": "curriculum", "free": True,
                     "note": "Free self-paced curriculum with free certificates."},
    "tau": {"title": "Test Automation University learning paths", "provider": "Applitools",
            "url": "https://testautomationu.applitools.com/", "kind": "learning_path", "free": True,
            "note": "Free courses on Selenium, Playwright, API testing, CI for testers."},
    "de-zoomcamp": {"title": "Data Engineering Zoomcamp (DataTalksClub)", "provider": "DataTalksClub",
                    "url": "https://github.com/DataTalksClub/data-engineering-zoomcamp", "kind": "curriculum", "free": True,
                    "note": "Free 9-week course: Docker, Terraform, orchestration, warehousing, streaming."},
    "owasp-top10": {"title": "OWASP Top 10", "provider": "OWASP",
                    "url": "https://owasp.org/www-project-top-ten/", "kind": "book", "free": True,
                    "note": "The reference list of critical web-application security risks."},
    "linux-journey": {"title": "Linux Journey", "provider": "LabEx",
                      "url": "https://labex.io/linuxjourney", "kind": "curriculum", "free": True,
                      "note": "Free, interactive Linux fundamentals to networking."},
}

ROLE_PATHS: Dict[str, List[str]] = {
    "devops_cloud": ["milanm-devops", "90daysofdevops", "ms-devops-career", "aws-ramp-up", "cloud-resume-challenge",
                     "k8s-hard-way", "devops-exercises", "google-sre-books"],
    "backend": ["system-design-primer", "ossu-cs", "fullstack-open", "aws-ramp-up"],
    "frontend": ["odin-project", "fullstack-open", "freecodecamp"],
    "fullstack": ["fullstack-open", "odin-project", "system-design-primer", "freecodecamp"],
    "software_general": ["ossu-cs", "system-design-primer", "freecodecamp"],
    "mobile": ["ossu-cs"],
    "qa_testing": ["tau"],
    "data_ai": ["de-zoomcamp", "ossu-cs"],
    "security": ["owasp-top10", "linux-journey"],
    "embedded": ["ossu-cs", "linux-journey"],
    "it_ops": ["linux-journey", "google-sre-books", "devops-exercises"],
}


def roadmap_catalog(categories: List[str], seniorities: List[str]) -> List[dict]:
    """roadmap.sh role roadmaps + other providers' paths for these roles, each with a stable id."""
    out: List[dict] = []
    seen = set()
    for r in role_roadmaps(categories, seniorities):
        rid = "roadmapsh-" + r["slug"]
        seen.add(rid)
        out.append({"id": rid, "title": f"roadmap.sh: {r['title']}", "url": r["url"], "provider": "roadmap.sh",
                    "kind": "roadmap", "free": True, "note": "Community-maintained visual roadmap."})
    for cat in categories:
        for pid in ROLE_PATHS.get(cat, []):
            if pid not in seen:
                seen.add(pid)
                out.append({"id": pid, **LEARNING_PATHS[pid]})
    return out


# ---------------------------------------------------------------- certifications
# Checked Sep 2026. Retired and left out on purpose: AZ-204 (Azure Developer), AI-102 (Azure AI Engineer).
# level: foundational < associate < professional < expert. cost: exam fee as shown by the issuer (USD) or None.
CERTIFICATIONS: Dict[str, dict] = {
    "aws-ccp": {"name": "AWS Certified Cloud Practitioner", "issuer": "AWS", "level": "foundational", "cost": 100,
                "url": "https://aws.amazon.com/certification/certified-cloud-practitioner/",
                "categories": ["devops_cloud", "backend", "data_ai"], "skills": ["aws"], "aliases": ["cloud practitioner", "clf-c02"]},
    "aws-saa": {"name": "AWS Certified Solutions Architect – Associate", "issuer": "AWS", "level": "associate", "cost": 150,
                "url": "https://aws.amazon.com/certification/certified-solutions-architect-associate/",
                "categories": ["devops_cloud", "backend"], "skills": ["aws"], "aliases": ["solutions architect associate", "saa-c03", "aws saa"]},
    "aws-dva": {"name": "AWS Certified Developer – Associate", "issuer": "AWS", "level": "associate", "cost": 150,
                "url": "https://aws.amazon.com/certification/certified-developer-associate/",
                "categories": ["backend", "fullstack", "devops_cloud"], "skills": ["aws"], "aliases": ["aws developer associate", "dva-c02"]},
    "aws-dop": {"name": "AWS Certified DevOps Engineer – Professional", "issuer": "AWS", "level": "professional", "cost": 300,
                "url": "https://aws.amazon.com/certification/certified-devops-engineer-professional/",
                "categories": ["devops_cloud"], "skills": ["aws", "ci/cd"], "aliases": ["aws devops engineer", "dop-c02"]},
    "az-900": {"name": "Microsoft Azure Fundamentals (AZ-900)", "issuer": "Microsoft", "level": "foundational", "cost": None,
               "url": "https://learn.microsoft.com/en-us/credentials/certifications/azure-fundamentals/",
               "categories": ["devops_cloud", "backend", "data_ai"], "skills": ["azure"], "aliases": ["az-900", "azure fundamentals"]},
    "az-104": {"name": "Microsoft Azure Administrator Associate (AZ-104)", "issuer": "Microsoft", "level": "associate", "cost": None,
               "url": "https://learn.microsoft.com/en-us/credentials/certifications/azure-administrator/",
               "categories": ["devops_cloud", "it_ops"], "skills": ["azure"], "aliases": ["az-104", "azure administrator"]},
    "az-400": {"name": "Microsoft DevOps Engineer Expert (AZ-400)", "issuer": "Microsoft", "level": "expert", "cost": None,
               "url": "https://learn.microsoft.com/en-us/credentials/certifications/devops-engineer/",
               "categories": ["devops_cloud"], "skills": ["azure", "ci/cd", "azure devops"], "aliases": ["az-400", "devops engineer expert"],
               "prereq": "Azure Administrator (AZ-104) or Azure Developer Associate"},
    "gcp-ace": {"name": "Google Cloud Associate Cloud Engineer", "issuer": "Google Cloud", "level": "associate", "cost": 125,
                "url": "https://cloud.google.com/learn/certification/cloud-engineer",
                "categories": ["devops_cloud"], "skills": ["google cloud"], "aliases": ["associate cloud engineer", "gcp ace"]},
    "kcna": {"name": "Kubernetes and Cloud Native Associate (KCNA)", "issuer": "Linux Foundation / CNCF", "level": "foundational", "cost": 250,
             "url": "https://training.linuxfoundation.org/certification/kubernetes-cloud-native-associate/",
             "categories": ["devops_cloud"], "skills": ["kubernetes"], "aliases": ["kcna"]},
    "cka": {"name": "Certified Kubernetes Administrator (CKA)", "issuer": "Linux Foundation / CNCF", "level": "professional", "cost": None,
            "url": "https://training.linuxfoundation.org/certification/certified-kubernetes-administrator-cka/",
            "categories": ["devops_cloud", "it_ops"], "skills": ["kubernetes"], "aliases": ["cka", "certified kubernetes administrator"],
            "note": "Hands-on, performance-based exam."},
    "ckad": {"name": "Certified Kubernetes Application Developer (CKAD)", "issuer": "Linux Foundation / CNCF", "level": "professional", "cost": 445,
             "url": "https://training.linuxfoundation.org/certification/certified-kubernetes-application-developer-ckad/",
             "categories": ["devops_cloud", "backend"], "skills": ["kubernetes"], "aliases": ["ckad"], "note": "Hands-on, performance-based exam."},
    "terraform-associate": {"name": "HashiCorp Terraform Associate (004)", "issuer": "HashiCorp", "level": "associate", "cost": 70.5,
                            "url": "https://developer.hashicorp.com/certifications/infrastructure-automation",
                            "categories": ["devops_cloud"], "skills": ["terraform", "infrastructure as code"], "aliases": ["terraform associate"]},
    "lfcs": {"name": "Linux Foundation Certified System Administrator (LFCS)", "issuer": "Linux Foundation", "level": "associate", "cost": 445,
             "url": "https://training.linuxfoundation.org/certification/linux-foundation-certified-sysadmin-lfcs/",
             "categories": ["devops_cloud", "it_ops"], "skills": ["linux"], "aliases": ["lfcs"]},
    "rhcsa": {"name": "Red Hat Certified System Administrator (RHCSA, EX200)", "issuer": "Red Hat", "level": "associate", "cost": None,
              "url": "https://www.redhat.com/en/services/certification/rhcsa",
              "categories": ["devops_cloud", "it_ops"], "skills": ["linux"], "aliases": ["rhcsa", "red hat certified"]},
    "gh-900": {"name": "GitHub Foundations (GH-900)", "issuer": "GitHub / Microsoft", "level": "foundational", "cost": None,
               "url": "https://learn.microsoft.com/en-us/credentials/certifications/github-foundations/",
               "categories": ["devops_cloud", "software_general", "backend", "frontend", "fullstack"], "skills": ["git", "github"], "aliases": ["gh-900"]},
    "gh-200": {"name": "GitHub Actions (GH-200)", "issuer": "GitHub / Microsoft", "level": "associate", "cost": None,
               "url": "https://learn.microsoft.com/en-us/credentials/certifications/github-actions/",
               "categories": ["devops_cloud"], "skills": ["github actions", "ci/cd"], "aliases": ["gh-200", "github actions certification"]},
    "istqb-ctfl": {"name": "ISTQB Certified Tester Foundation Level (CTFL v4.0)", "issuer": "ISTQB", "level": "foundational", "cost": None,
                   "url": "https://www.istqb.org/certifications/certified-tester-foundation-level-ctfl-v4-0/",
                   "categories": ["qa_testing"], "skills": ["testing", "test automation"], "aliases": ["istqb", "ctfl", "istqb foundation"]},
    "istqb-tae": {"name": "ISTQB Advanced Test Automation Engineering (CTAL-TAE)", "issuer": "ISTQB", "level": "professional", "cost": None,
                  "url": "https://www.istqb.org/certifications/certified-tester-advanced-level-test-automation-engineering-ctal-tae/",
                  "categories": ["qa_testing"], "skills": ["test automation"], "aliases": ["ctal-tae", "istqb test automation"],
                  "prereq": "ISTQB CTFL + practical experience"},
    "comptia-secplus": {"name": "CompTIA Security+", "issuer": "CompTIA", "level": "associate", "cost": None,
                        "url": "https://www.comptia.org/en-us/certifications/security/",
                        "categories": ["security", "it_ops"], "skills": ["security"], "aliases": ["security+", "comptia security"]},
    "isc2-cc": {"name": "ISC2 Certified in Cybersecurity (CC)", "issuer": "ISC2", "level": "foundational", "cost": None,
                "url": "https://www.isc2.org/certifications/cc",
                "categories": ["security"], "skills": ["security"], "aliases": ["isc2 cc", "certified in cybersecurity"]},
    "dp-700": {"name": "Microsoft Fabric Data Engineer Associate (DP-700)", "issuer": "Microsoft", "level": "associate", "cost": None,
               "url": "https://learn.microsoft.com/en-us/credentials/certifications/fabric-data-engineer-associate/",
               "categories": ["data_ai"], "skills": ["azure", "sql", "spark"], "aliases": ["dp-700", "fabric data engineer"]},
    "databricks-dea": {"name": "Databricks Certified Data Engineer Associate", "issuer": "Databricks", "level": "associate", "cost": 200,
                       "url": "https://www.databricks.com/learn/certification/data-engineer-associate",
                       "categories": ["data_ai"], "skills": ["databricks", "spark"], "aliases": ["databricks data engineer"]},
    "psm-1": {"name": "Professional Scrum Master I (PSM I)", "issuer": "Scrum.org", "level": "foundational", "cost": None,
              "url": "https://www.scrum.org/assessments/professional-scrum-master-i-certification",
              "categories": ["software_general", "qa_testing", "backend", "frontend", "fullstack"], "skills": ["scrum", "agile"],
              "aliases": ["psm", "psm i", "scrum master"]},
    "goethe": {"name": "Goethe-Zertifikat (A1–C2)", "issuer": "Goethe-Institut", "level": "foundational", "cost": None,
               "url": "https://www.goethe.de/en/spr/prf.html", "categories": [], "skills": ["german"], "language": "German",
               "aliases": ["goethe-zertifikat", "goethe"]},
    "osd": {"name": "ÖSD Austrian German Diploma (A1–C2)", "issuer": "ÖSD", "level": "foundational", "cost": None,
            "url": "https://www.osd.at/en/", "categories": [], "skills": ["german"], "language": "German", "aliases": ["ösd", "osd"]},
}

LEVEL_ORDER = {"foundational": 1, "associate": 2, "professional": 3, "expert": 4}


def certification_candidates(categories: List[str], skills: List[str], language_gaps: List[str]) -> List[dict]:
    """Certifications relevant to the target roles, the skill gaps, or a language the person needs."""
    skill_set = {s.lower() for s in skills}
    langs = {l.lower() for l in language_gaps}
    out = []
    for cid, c in CERTIFICATIONS.items():
        if c.get("language"):
            relevant = c["language"].lower() in langs
        else:
            relevant = bool(set(c["categories"]) & set(categories)) or bool(set(c["skills"]) & skill_set)
        if relevant:
            out.append({"id": cid, **c})
    out.sort(key=lambda c: (LEVEL_ORDER.get(c["level"], 9), c["issuer"], c["name"]))
    return out


def cert_mentions(cert: dict, mentioned: Dict[str, int]) -> int:
    """How many postings mention this certification (mentioned: lowercase cert text -> count)."""
    keys = [cert["name"].lower()] + [a.lower() for a in cert.get("aliases", [])]
    return sum(n for text, n in mentioned.items() if any(k in text for k in keys))


KNOWN_URLS.update(p["url"] for p in LEARNING_PATHS.values())
KNOWN_URLS.update(c["url"] for c in CERTIFICATIONS.values())
