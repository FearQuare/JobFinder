"""AI skill extraction with the Anthropic API.

Each job description is sent once to the model, which returns structured data
(category, seniority, skills with required/nice-to-have, language requirements, …).
Results are stored, so re-running only analyses new jobs.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

from . import config

MAX_DESCRIPTION_CHARS = 12000

SKILL_TYPES = ["programming_language", "framework_library", "tool_platform", "cloud", "database", "practice_method", "domain_knowledge", "soft_skill", "certification"]
EDUCATION = ["not_mentioned", "currently_studying", "vocational_or_htl", "bachelor", "master", "phd", "degree_or_equivalent_experience"]
REMOTE = ["not_mentioned", "onsite", "hybrid", "remote"]

ANALYSIS_TOOL = {
    "name": "record_job_analysis",
    "description": "Record the structured analysis of one job posting.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": list(config.CATEGORIES), "description": "Main role family. Use 'other' for roles that are not software/IT engineering (e.g. sales, HR, mechanical engineering)."},
            "seniority": {"type": "string", "enum": list(config.SENIORITIES), "description": "entry = student/intern/apprentice; junior = 0-2 years; mid = 2-5 years; senior = 5+ years or 'Senior' title; lead = lead/principal/architect/head. 'unspecified' only if there is no signal at all."},
            "job_type": {"type": "string", "enum": list(config.JOB_TYPES)},
            "years_experience_min": {"type": ["integer", "null"], "description": "Minimum years of professional experience asked for, or null if not stated."},
            "education": {"type": "string", "enum": EDUCATION},
            "remote_policy": {"type": "string", "enum": REMOTE},
            "skills": {
                "type": "array",
                "description": "Technical and soft skills the candidate should have. Do NOT include spoken languages here.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Short canonical English name, e.g. 'Kubernetes', 'CI/CD', 'Terraform', 'Python', 'Azure', 'Communication'."},
                        "type": {"type": "string", "enum": SKILL_TYPES},
                        "required": {"type": "boolean", "description": "false if described as nice-to-have / von Vorteil / wünschenswert / ideally / a plus."},
                    },
                    "required": ["name", "type", "required"],
                },
            },
            "languages": {
                "type": "array",
                "description": "Spoken/written human languages required (e.g. German, English).",
                "items": {
                    "type": "object",
                    "properties": {
                        "language": {"type": "string", "description": "English name, e.g. 'German'."},
                        "level": {"type": "string", "description": "CEFR level (A1-C2) if stated or clearly implied ('fließend' ≈ C1, 'sehr gut' ≈ C1, 'gut' ≈ B2, 'Grundkenntnisse' ≈ A2), 'native', or 'unspecified'."},
                        "required": {"type": "boolean"},
                    },
                    "required": ["language", "level", "required"],
                },
            },
            "summary": {"type": "string", "description": "One English sentence describing the role."},
        },
        "required": ["category", "seniority", "job_type", "years_experience_min", "education", "remote_policy", "skills", "languages", "summary"],
    },
}

SYSTEM_PROMPT = """You analyse job postings from Austria (usually German or English) for a job-market research tool.
Extract what the employer expects from candidates. Rules:
- Use short canonical English skill names so they can be counted across postings: "Kubernetes" (not K8s), "Azure", "AWS", "Google Cloud", "Terraform", "Ansible", "Docker", "CI/CD", "GitHub Actions", "GitLab CI", "Jenkins", "Linux", "Python", "Java", "C#", ".NET", "JavaScript", "TypeScript", "React", "Angular", "SQL", "PostgreSQL", "Git", "Agile", "Scrum", "Infrastructure as Code", "Monitoring", "Prometheus", "Grafana", "Communication", "Teamwork", "Problem solving".
- One concept per skill. Split lists like "AWS/Azure/GCP" into separate skills. Keep skills to what is asked of the candidate (a company's tech stack mentioned as context counts as nice-to-have).
- Put human languages (German, English, …) only in "languages", never in "skills".
- Soft skills only if explicitly asked for; name them in 1-3 words.
- Be faithful to the text; do not invent requirements."""

ALIASES = {
    "k8s": "Kubernetes", "kubernetes (k8s)": "Kubernetes", "openshift": "OpenShift",
    "microsoft azure": "Azure", "ms azure": "Azure", "azure cloud": "Azure",
    "amazon web services": "AWS", "amazon web services (aws)": "AWS", "aws cloud": "AWS",
    "gcp": "Google Cloud", "google cloud platform": "Google Cloud", "google cloud platform (gcp)": "Google Cloud",
    "golang": "Go", "js": "JavaScript", "javascript (es6+)": "JavaScript", "ts": "TypeScript",
    "postgres": "PostgreSQL", "postgresql database": "PostgreSQL", "ms sql": "SQL Server", "mssql": "SQL Server", "microsoft sql server": "SQL Server",
    "ci/cd pipelines": "CI/CD", "ci / cd": "CI/CD", "continuous integration": "CI/CD", "ci/cd pipeline": "CI/CD",
    "github action": "GitHub Actions", "gitlab ci/cd": "GitLab CI", "gitlab-ci": "GitLab CI",
    "iac": "Infrastructure as Code", "infrastructure-as-code": "Infrastructure as Code",
    "agile methodologies": "Agile", "agile methods": "Agile", "agile development": "Agile",
    "c sharp": "C#", "dotnet": ".NET", ".net core": ".NET", "asp.net core": "ASP.NET", "node": "Node.js", "nodejs": "Node.js",
    "reactjs": "React", "react.js": "React", "vue.js": "Vue", "vuejs": "Vue", "angularjs": "Angular",
    "team player": "Teamwork", "team work": "Teamwork", "communication skills": "Communication",
    "problem-solving": "Problem solving", "problem solving skills": "Problem solving",
    "linux administration": "Linux", "bash scripting": "Bash", "shell scripting": "Shell scripting",
}


def canonical_skill(name: str) -> str:
    n = re.sub(r"\s+", " ", (name or "").strip()).rstrip(" .,;")
    return ALIASES.get(n.lower(), n)


def normalise_result(raw: Dict[str, Any]) -> Dict[str, Any]:
    def pick(value, allowed, default):
        return value if value in allowed else default

    skills: List[dict] = []
    seen = set()
    for s in raw.get("skills") or []:
        if not isinstance(s, dict) or not s.get("name"):
            continue
        name = canonical_skill(str(s["name"]))
        if not name or name.lower() in seen or len(name) > 60:
            continue
        seen.add(name.lower())
        skills.append({"name": name, "type": pick(s.get("type"), SKILL_TYPES, "tool_platform"), "required": bool(s.get("required", True))})
    languages = []
    seen_lang = set()
    for l in raw.get("languages") or []:
        if not isinstance(l, dict) or not l.get("language"):
            continue
        lang = str(l["language"]).strip().title()
        if lang.lower() in seen_lang:
            continue
        seen_lang.add(lang.lower())
        languages.append({"language": lang, "level": str(l.get("level") or "unspecified").strip(), "required": bool(l.get("required", True))})
    yrs = raw.get("years_experience_min")
    try:
        yrs = int(yrs) if yrs is not None else None
    except (TypeError, ValueError):
        yrs = None
    return {
        "category": pick(raw.get("category"), config.CATEGORIES, "other"),
        "seniority": pick(raw.get("seniority"), config.SENIORITIES, "unspecified"),
        "job_type": pick(raw.get("job_type"), config.JOB_TYPES, "unspecified"),
        "years_experience_min": yrs,
        "education": pick(raw.get("education"), EDUCATION, "not_mentioned"),
        "remote_policy": pick(raw.get("remote_policy"), REMOTE, "not_mentioned"),
        "skills": skills,
        "languages": languages,
        "summary": str(raw.get("summary") or "")[:400],
    }


def build_job_prompt(job: Dict[str, Any]) -> str:
    desc = (job.get("description") or "").strip()
    if len(desc) > MAX_DESCRIPTION_CHARS:
        desc = desc[:MAX_DESCRIPTION_CHARS] + "\n[…truncated]"
    parts = [
        f"Title: {job.get('title') or ''}",
        f"Company: {job.get('company') or 'unknown'}",
        f"Location: {job.get('location') or 'unknown'}",
        f"Employment info: {job.get('employment_raw') or 'unknown'}",
        "",
        "Description:",
        desc or "(no description available — infer only from the title)",
    ]
    return "\n".join(parts)


class AIError(Exception):
    pass


class AIAuthError(AIError):
    """Unrecoverable for this run (bad key, no credits, unknown model): stop analysing."""


# ---------------------------------------------------------------- providers

PROVIDERS = {"anthropic": "Anthropic (Claude)", "openai": "OpenAI"}
KEY_NAMES = {"anthropic": "anthropic_api_key", "openai": "openai_api_key"}
DEFAULT_MODELS = {"anthropic": config.DEFAULT_AI_MODEL, "openai": config.DEFAULT_OPENAI_MODEL}
MODEL_SETTING = {"anthropic": "ai_model", "openai": "openai_model"}


def current_provider(settings: Dict[str, str]) -> str:
    p = settings.get("ai_provider") or "anthropic"
    return p if p in PROVIDERS else "anthropic"


def model_for(settings: Dict[str, str], provider: Optional[str] = None) -> str:
    provider = provider or current_provider(settings)
    return (settings.get(MODEL_SETTING[provider]) or "").strip() or DEFAULT_MODELS[provider]


def api_key_for(settings: Dict[str, str], provider: Optional[str] = None) -> Optional[str]:
    from . import secrets_store

    return secrets_store.get_secret(KEY_NAMES[provider or current_provider(settings)])


def has_key(settings: Dict[str, str]) -> bool:
    return bool(api_key_for(settings))


# Models offered for profile analysis and roadmap creation (quality matters more than cost there).
# Prices per million input / output tokens from the providers' docs (Sep 2026).
PLANNING_PRESETS: List[Dict[str, Any]] = [
    {"provider": "anthropic", "model": "claude-fable-5-1", "label": "Claude Fable 5.1", "note": "Most capable Claude model; slowest", "price": (10, 50)},
    {"provider": "anthropic", "model": "claude-opus-5-5", "label": "Claude Opus 5.5", "note": "Recommended: excellent reasoning, moderate cost", "price": (4, 20), "recommended": True},
    {"provider": "anthropic", "model": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "note": "Balanced speed and intelligence", "price": (2, 10)},
    {"provider": "anthropic", "model": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5", "note": "Fastest and cheapest; least thorough", "price": (1, 5)},
    {"provider": "openai", "model": "gpt-6-astra", "label": "GPT-6 Astra", "note": "OpenAI's most capable model", "price": (10, 50), "recommended": True},
    {"provider": "openai", "model": "gpt-6.1-sol", "label": "GPT-6.1 Sol", "note": "Near-Astra quality at lower cost", "price": (2, 10)},
    {"provider": "openai", "model": "gpt-6-luna", "label": "GPT-6 Luna", "note": "Fastest and cheapest; least thorough", "price": (0.1, 0.5)},
]
EFFORTS = {"low": "Low (fast)", "medium": "Medium", "high": "High (most thorough)"}
PLAN_TOKENS_ESTIMATE = (20000, 15000)  # rough input / output (incl. thinking) tokens for one plan


def estimate_cost(price) -> str:
    cost = price[0] * PLAN_TOKENS_ESTIMATE[0] / 1e6 + price[1] * PLAN_TOKENS_ESTIMATE[1] / 1e6
    return f"≈ ${cost:.2f}" if cost >= 0.1 else "< $0.10"


def planning_options(settings: Dict[str, str]) -> List[Dict[str, Any]]:
    """Presets (plus a saved custom model), flagged by whether their provider has a key."""
    opts = []
    for p in PLANNING_PRESETS:
        opts.append({**p, "id": f"{p['provider']}:{p['model']}", "available": bool(api_key_for(settings, p["provider"])),
                     "cost": estimate_cost(p["price"])})
    custom = (settings.get("planning_model") or "").strip()
    if custom and ":" in custom and custom not in {o["id"] for o in opts}:
        prov, model = custom.split(":", 1)
        if prov in PROVIDERS:
            opts.append({"provider": prov, "model": model, "label": model, "note": "Custom model", "id": custom,
                         "available": bool(api_key_for(settings, prov)), "cost": "", "price": None})
    return opts


def planning_choice(settings: Dict[str, str]) -> Optional[Dict[str, str]]:
    """The model to use for profile analysis / roadmaps: the saved choice if its key exists, else the best available."""
    saved = (settings.get("planning_model") or "").strip()
    if ":" in saved:
        prov, model = saved.split(":", 1)
        if prov in PROVIDERS and api_key_for(settings, prov):
            return {"provider": prov, "model": model}
    order = [current_provider(settings)] + [p for p in PROVIDERS if p != current_provider(settings)]
    for prov in order:
        if api_key_for(settings, prov):
            best = next(p for p in PLANNING_PRESETS if p["provider"] == prov and p.get("recommended"))
            return {"provider": prov, "model": best["model"]}
    return None


def make_analyzer(settings: Dict[str, str], concurrency: Optional[int] = None, purpose: str = "jobs") -> "BaseAnalyzer":
    """purpose="jobs": fast bulk extraction model. purpose="planning": the (smarter) profile/roadmap model."""
    if purpose == "planning":
        choice = planning_choice(settings)
        if not choice:
            raise AIAuthError("Add an Anthropic or OpenAI API key in Settings first.")
        provider, model = choice["provider"], choice["model"]
        effort = settings.get("planning_effort") if settings.get("planning_effort") in EFFORTS else "high"
    else:
        provider, model, effort = current_provider(settings), None, None
    key = api_key_for(settings, provider)
    if not key:
        raise AIAuthError(f"No {PROVIDERS[provider]} API key saved. Add it in Settings.")
    if concurrency is None:
        try:
            concurrency = int(settings.get("ai_concurrency") or 4)
        except ValueError:
            concurrency = 4
    model = model or model_for(settings, provider)
    if provider == "openai":
        return OpenAIAnalyzer(key, model, concurrency, reasoning_effort=effort or "low")
    return AnthropicAnalyzer(key, model, concurrency, effort=effort)


def summary_prompt(title: str, stats: Dict[str, Any]) -> str:
    return (
        f"Here is aggregated data from {stats['job_count']} currently open job postings in Austria for: {title}.\n\n"
        f"{json.dumps(stats, ensure_ascii=False, indent=1)}\n\n"
        "Write a concise report (150-250 words, Markdown) for a job seeker: what companies require for these roles "
        "(the must-haves, with rough percentages), common nice-to-haves, language requirements (especially German level), "
        "typical experience expected, and 2-3 practical suggestions for what to learn first to become competitive. "
        "Base every claim on the data. Use short headings or bullets. No preamble."
    )


class BaseAnalyzer:
    """Provider-neutral interface: structured JSON output for a schema, or free text."""

    provider = "base"

    def __init__(self, api_key: str, model: str, concurrency: int = 4):
        self.model = model
        self._concurrency = max(1, concurrency)
        self._sem: Optional[asyncio.Semaphore] = None

    @property
    def sem(self) -> asyncio.Semaphore:
        # Created on first use so it binds to the running event loop (required on Python 3.9).
        if self._sem is None:
            self._sem = asyncio.Semaphore(self._concurrency)
        return self._sem

    async def structured(self, name: str, description: str, schema: Dict[str, Any], system: str, prompt: str,
                         max_tokens: int = 2000) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    async def complete(self, prompt: str, max_tokens: int = 1200) -> str:  # pragma: no cover
        raise NotImplementedError

    async def analyse_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        async with self.sem:
            raw = await self.structured(ANALYSIS_TOOL["name"], ANALYSIS_TOOL["description"], ANALYSIS_TOOL["input_schema"],
                                        SYSTEM_PROMPT, build_job_prompt(job), max_tokens=2000)
        return normalise_result(raw)

    async def summarise_group(self, title: str, stats: Dict[str, Any]) -> str:
        return await self.complete(summary_prompt(title, stats), max_tokens=1200)

    async def aclose(self) -> None:
        pass


class AnthropicAnalyzer(BaseAnalyzer):
    provider = "anthropic"

    def __init__(self, api_key: str, model: str, concurrency: int = 4, http_client=None, max_retries: int = 4,
                 effort: Optional[str] = None):
        super().__init__(api_key, model, concurrency)
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise AIError("The 'anthropic' package is not installed. Run ./run.sh again.") from exc
        self._sdk = anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=max_retries, http_client=http_client)
        self.effort = effort  # adaptive-thinking effort for models that support it (Opus/Sonnet 5.5, Fable 5.1)

    async def _create(self, max_tokens: int, output_config: Dict[str, Any], **kwargs):
        """Send the request; drop the effort setting once if the model doesn't support it (e.g. Haiku 4.5)."""
        cfg = dict(output_config)
        if self.effort:
            cfg["effort"] = self.effort
        if cfg:
            kwargs["output_config"] = cfg
        if max_tokens > 16000:
            # Long, thinking-heavy requests: explicit timeout instead of the SDK's 10-minute non-streaming guard.
            kwargs["timeout"] = 900
        try:
            return await self.client.messages.create(model=self.model, max_tokens=max_tokens, **kwargs)
        except self._sdk.BadRequestError as exc:
            if self.effort and "effort" in str(exc).lower():
                self.effort = None
                kwargs.pop("output_config", None)
                kwargs.pop("timeout", None)
                return await self._create(max_tokens, output_config, **kwargs)
            raise

    def _translate(self, exc: Exception) -> AIError:
        a = self._sdk
        if isinstance(exc, a.AuthenticationError):
            return AIAuthError("The Anthropic API key was rejected. Check it in Settings.")
        if isinstance(exc, a.PermissionDeniedError):
            return AIAuthError(f"The Anthropic API refused the request: {exc}")
        if isinstance(exc, a.NotFoundError):
            return AIAuthError(f"Anthropic model '{self.model}' was not found. Change the model in Settings.")
        if isinstance(exc, a.BadRequestError) and "credit balance" in str(exc).lower():
            return AIAuthError("Your Anthropic account is out of credits.")
        return AIError(str(exc)[:300])

    async def structured(self, name, description, schema, system, prompt, max_tokens=2000):
        # Structured outputs (output_config.format) work on every current Claude model. Forced tool use does not:
        # Opus 5.5, Sonnet 5.5 and Fable 5.1 reject tool_choice "tool"/"any".
        fmt = {"type": "json_schema", "schema": strict_json_schema(schema)}
        try:
            resp = await self._create(max_tokens, {"format": fmt}, system=f"{system}\n\nTask: {description}",
                                      messages=[{"role": "user", "content": prompt}])
        except self._sdk.APIError as exc:
            raise self._translate(exc) from exc
        stop = getattr(resp, "stop_reason", None)
        if stop == "max_tokens":
            raise AIError("The model ran out of output space before finishing.")
        if stop == "refusal":
            raise AIError("The model declined to answer this request.")
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text").strip()
        try:
            return json.loads(text)
        except ValueError as exc:
            raise AIError("The model did not return valid JSON.") from exc

    async def complete(self, prompt, max_tokens=1200):
        try:
            resp = await self._create(max_tokens, {}, messages=[{"role": "user", "content": prompt}])
        except self._sdk.APIError as exc:
            raise self._translate(exc) from exc
        return "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text").strip()

    async def aclose(self) -> None:
        await self.client.close()


def strict_json_schema(schema: Any) -> Any:
    """OpenAI strict structured outputs need additionalProperties=false and every property listed as required."""
    if isinstance(schema, dict):
        out = {k: strict_json_schema(v) for k, v in schema.items()}
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"])
        return out
    if isinstance(schema, list):
        return [strict_json_schema(v) for v in schema]
    return schema


def openai_format(name: str, description: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "json_schema", "name": name, "description": description,
            "schema": strict_json_schema(schema), "strict": True}


OPENAI_FORMAT = openai_format(ANALYSIS_TOOL["name"], ANALYSIS_TOOL["description"], ANALYSIS_TOOL["input_schema"])


class OpenAIAnalyzer(BaseAnalyzer):
    """Uses the Responses API with a strict JSON schema (works for reasoning and non-reasoning models)."""

    provider = "openai"
    REASONING_EFFORT = "low"   # extraction doesn't need deep reasoning; keeps cost and latency down

    def __init__(self, api_key: str, model: str, concurrency: int = 4, http_client=None, max_retries: int = 4,
                 reasoning_effort: str = "low"):
        super().__init__(api_key, model, concurrency)
        self.REASONING_EFFORT = reasoning_effort
        try:
            import openai
        except ImportError as exc:  # pragma: no cover
            raise AIError("The 'openai' package is not installed. Run ./run.sh again.") from exc
        self._sdk = openai
        self.client = openai.AsyncOpenAI(api_key=api_key, max_retries=max_retries, http_client=http_client)
        self._use_reasoning = True

    def _translate(self, exc: Exception) -> AIError:
        o = self._sdk
        msg = str(exc)
        if isinstance(exc, o.AuthenticationError):
            return AIAuthError("The OpenAI API key was rejected. Check it in Settings.")
        if isinstance(exc, o.PermissionDeniedError):
            return AIAuthError(f"The OpenAI API refused the request: {msg[:200]}")
        if isinstance(exc, o.NotFoundError):
            return AIAuthError(f"OpenAI model '{self.model}' was not found or isn't available to your account. Change it in Settings.")
        if isinstance(exc, o.RateLimitError) and ("insufficient_quota" in msg or getattr(exc, "code", None) == "insufficient_quota"):
            return AIAuthError("Your OpenAI account has no remaining credits/quota (check billing at platform.openai.com).")
        return AIError(msg[:300])

    async def _create(self, **kwargs):
        if self._use_reasoning:
            try:
                return await self.client.responses.create(reasoning={"effort": self.REASONING_EFFORT}, **kwargs)
            except self._sdk.BadRequestError as exc:
                if "reasoning" not in str(exc).lower():
                    raise
                self._use_reasoning = False  # non-reasoning model (e.g. gpt-4.1-mini): retry without the parameter
        return await self.client.responses.create(**kwargs)

    async def structured(self, name, description, schema, system, prompt, max_tokens=2000):
        try:
            resp = await self._create(
                model=self.model,
                instructions=system,
                input=prompt,
                text={"format": openai_format(name, description, schema)},
                max_output_tokens=max_tokens + (4000 if self.REASONING_EFFORT == "low" else 20000),  # reasoning counts
                store=False,
                **({"timeout": 900} if max_tokens > 8000 else {}),
            )
        except self._sdk.APIError as exc:
            raise self._translate(exc) from exc
        if getattr(resp, "status", "completed") == "incomplete":
            raise AIError("OpenAI stopped before finishing the answer (output limit).")
        text = getattr(resp, "output_text", "") or ""
        try:
            return json.loads(text)
        except ValueError as exc:
            raise AIError("OpenAI did not return valid JSON.") from exc

    async def complete(self, prompt, max_tokens=1200):
        try:
            resp = await self._create(model=self.model, input=prompt, max_output_tokens=max_tokens + 3000, store=False)
        except self._sdk.APIError as exc:
            raise self._translate(exc) from exc
        return (getattr(resp, "output_text", "") or "").strip()

    async def aclose(self) -> None:
        await self.client.close()
