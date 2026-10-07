"""Both AI providers, exercised through their real SDKs against a mocked HTTP layer."""
import asyncio
import json

import httpx
import pytest

from app import ai, db, secrets_store

JOB = {"title": "Junior DevOps Engineer (m/w/d)", "company": "ACME", "location": "Wien", "employment_raw": "Vollzeit",
       "description": "Du hast Erfahrung mit Docker und Kubernetes. Terraform von Vorteil. Sehr gute Deutschkenntnisse."}

RESULT = {
    "category": "devops_cloud", "seniority": "junior", "job_type": "full_time", "years_experience_min": None,
    "education": "not_mentioned", "remote_policy": "not_mentioned",
    "skills": [{"name": "Docker", "type": "tool_platform", "required": True},
               {"name": "K8s", "type": "tool_platform", "required": True},
               {"name": "Terraform", "type": "tool_platform", "required": False}],
    "languages": [{"language": "German", "level": "C1", "required": True}],
    "summary": "Junior DevOps role.",
}


def anthropic_http(handler):
    """The Anthropic SDK may be built on httpx or its successor httpx2; mock whichever it uses."""
    try:
        import httpx2 as hx
    except ImportError:
        hx = httpx

    def adapt(request):
        r = handler(request)
        return hx.Response(r.status_code, content=r.content, headers={"content-type": "application/json"})

    import anthropic
    try:
        return anthropic.DefaultAsyncHttpxClient(transport=hx.MockTransport(adapt))
    except TypeError:
        return hx.AsyncClient(transport=hx.MockTransport(adapt))


def run(coro):
    return asyncio.run(coro)


def openai_response(text, status="completed"):
    return {
        "id": "resp_1", "object": "response", "created_at": 1790000000, "status": status, "model": "gpt-6-luna",
        "output": [
            {"type": "reasoning", "id": "rs_1", "summary": []},
            {"type": "message", "id": "msg_1", "status": "completed", "role": "assistant",
             "content": [{"type": "output_text", "text": text, "annotations": []}]},
        ],
        "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
        "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20,
                  "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
    }


def make_openai(handler, model="gpt-6-luna"):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ai.OpenAIAnalyzer("sk-test", model, http_client=client, max_retries=0)


def test_openai_strict_schema_is_valid():
    schema = ai.OPENAI_FORMAT["schema"]

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                assert node["additionalProperties"] is False
                assert sorted(node["required"]) == sorted(node["properties"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    assert ai.OPENAI_FORMAT["strict"] is True


def test_openai_request_and_parsing():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=openai_response(json.dumps(RESULT)))

    analyzer = make_openai(handler)
    out = run(analyzer.analyse_job(JOB))
    assert seen["url"].endswith("/v1/responses")
    assert seen["auth"] == "Bearer sk-test"
    body = seen["body"]
    assert body["model"] == "gpt-6-luna"
    assert body["reasoning"] == {"effort": "low"}
    assert body["text"]["format"]["type"] == "json_schema" and body["text"]["format"]["strict"] is True
    assert body["store"] is False
    assert "Junior DevOps Engineer" in body["input"] and "canonical English" in body["instructions"]
    assert out["category"] == "devops_cloud" and out["seniority"] == "junior"
    assert [s["name"] for s in out["skills"]] == ["Docker", "Kubernetes", "Terraform"]
    assert out["skills"][2]["required"] is False


def test_openai_retries_without_reasoning_for_non_reasoning_models():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append("reasoning" in body)
        if "reasoning" in body:
            return httpx.Response(400, json={"error": {"message": "Unsupported parameter: 'reasoning.effort' is not supported with this model.",
                                                        "type": "invalid_request_error", "param": "reasoning.effort", "code": "unsupported_parameter"}})
        return httpx.Response(200, json=openai_response(json.dumps(RESULT)))

    analyzer = make_openai(handler, model="gpt-4.1-mini")
    run(analyzer.analyse_job(JOB))
    run(analyzer.analyse_job(JOB))
    assert calls == [True, False, False]  # learns once, then stops sending it


@pytest.mark.parametrize("status,payload,expected", [
    (401, {"error": {"message": "Incorrect API key provided", "type": "invalid_request_error", "code": "invalid_api_key"}}, "key was rejected"),
    (429, {"error": {"message": "You exceeded your current quota", "type": "insufficient_quota", "code": "insufficient_quota"}}, "no remaining credits"),
    (404, {"error": {"message": "The model `gpt-x` does not exist", "type": "invalid_request_error", "code": "model_not_found"}}, "was not found"),
])
def test_openai_fatal_errors(status, payload, expected):
    analyzer = make_openai(lambda r: httpx.Response(status, json=payload))
    with pytest.raises(ai.AIAuthError, match=expected):
        run(analyzer.analyse_job(JOB))


def test_openai_bad_json_is_a_job_error_not_fatal():
    analyzer = make_openai(lambda r: httpx.Response(200, json=openai_response("not json")))
    with pytest.raises(ai.AIError) as info:
        run(analyzer.analyse_job(JOB))
    assert not isinstance(info.value, ai.AIAuthError)


def test_openai_summary():
    def handler(request):
        body = json.loads(request.content)
        assert "text" not in body
        return httpx.Response(200, json=openai_response("## Summary\n- Docker in 80%"))

    text = run(make_openai(handler).summarise_group("Junior DevOps roles", {"job_count": 5, "skills": []}))
    assert text.startswith("## Summary")


def anthropic_message(text, stop="end_turn", thinking=True):
    content = ([{"type": "thinking", "thinking": "Let me look at the skills…", "signature": "sig"}] if thinking else [])
    content.append({"type": "text", "text": text})
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": content,
            "stop_reason": stop, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 10}}


def test_anthropic_request_and_parsing():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=anthropic_message(json.dumps(RESULT)))

    analyzer = ai.AnthropicAnalyzer("sk-ant-test", "claude-opus-5-5", http_client=anthropic_http(handler), max_retries=0)
    out = run(analyzer.analyse_job(JOB))
    body = seen["body"]
    assert seen["url"].endswith("/v1/messages") and seen["key"] == "sk-ant-test"
    # structured outputs, not forced tool use (Opus/Sonnet 5.5 and Fable 5.1 reject tool_choice "tool")
    assert "tools" not in body and "tool_choice" not in body
    fmt = body["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False
    assert "effort" not in body["output_config"]
    assert out["skills"][1]["name"] == "Kubernetes"   # thinking block ignored, text parsed


def test_anthropic_effort_is_sent_and_dropped_if_unsupported():
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "effort" in body.get("output_config", {}):
            return httpx.Response(400, json={"type": "error", "error": {"type": "invalid_request_error",
                                                                          "message": "output_config.effort: not supported by this model"}})
        return httpx.Response(200, json=anthropic_message(json.dumps(RESULT), thinking=False))

    analyzer = ai.AnthropicAnalyzer("k", "claude-haiku-4-5-20251001", http_client=anthropic_http(handler), max_retries=0, effort="high")
    run(analyzer.structured("x", "d", ai.ANALYSIS_TOOL["input_schema"], "sys", "prompt", max_tokens=32000))
    assert "effort" in bodies[0]["output_config"] and "effort" not in bodies[1]["output_config"]
    assert "format" in bodies[1]["output_config"] and analyzer.effort is None


def test_anthropic_effort_accepted_and_refusal_handled():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=anthropic_message("", stop="refusal"))

    analyzer = ai.AnthropicAnalyzer("k", "claude-fable-5-1", http_client=anthropic_http(handler), max_retries=0, effort="high")
    with pytest.raises(ai.AIError, match="declined"):
        run(analyzer.structured("x", "d", ai.ANALYSIS_TOOL["input_schema"], "sys", "prompt"))
    assert seen["body"]["output_config"]["effort"] == "high" and seen["body"]["model"] == "claude-fable-5-1"


def test_planning_model_choice(tmp_data):
    with db.session() as conn:
        settings = db.get_settings(conn)
    assert ai.planning_choice(settings) is None
    secrets_store.set_secret("openai_api_key", "sk-o")
    assert ai.planning_choice(settings) == {"provider": "openai", "model": "gpt-6-astra"}
    secrets_store.set_secret("anthropic_api_key", "sk-a")
    assert ai.planning_choice(settings) == {"provider": "anthropic", "model": "claude-opus-5-5"}
    settings["planning_model"] = "anthropic:claude-fable-5-1"
    settings["planning_effort"] = "medium"
    a = ai.make_analyzer(settings, purpose="planning")
    assert isinstance(a, ai.AnthropicAnalyzer) and a.model == "claude-fable-5-1" and a.effort == "medium"
    settings["planning_model"] = "openai:gpt-6.1-sol"
    a = ai.make_analyzer(settings, purpose="planning")
    assert isinstance(a, ai.OpenAIAnalyzer) and a.model == "gpt-6.1-sol" and a.REASONING_EFFORT == "medium"
    # job extraction is unaffected by the planning choice
    j = ai.make_analyzer(settings)
    assert isinstance(j, ai.AnthropicAnalyzer) and j.model == "claude-haiku-4-5-20251001" and j.effort is None
    # a saved choice whose key was removed falls back to the best available model
    secrets_store.delete_secret("openai_api_key")
    assert ai.planning_choice(settings) == {"provider": "anthropic", "model": "claude-opus-5-5"}
    opts = {o["id"]: o for o in ai.planning_options(settings)}
    assert opts["anthropic:claude-opus-5-5"]["available"] and not opts["openai:gpt-6-astra"]["available"]
    assert opts["anthropic:claude-opus-5-5"]["cost"] == "≈ $0.38"
    settings["planning_model"] = "anthropic:claude-opus-6-preview"
    assert "anthropic:claude-opus-6-preview" in {o["id"] for o in ai.planning_options(settings)}


def test_anthropic_bad_key_is_fatal():
    client = anthropic_http(
        lambda r: httpx.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}))
    analyzer = ai.AnthropicAnalyzer("bad", "claude-haiku-4-5-20251001", http_client=client, max_retries=0)
    with pytest.raises(ai.AIAuthError, match="Anthropic API key was rejected"):
        run(analyzer.analyse_job(JOB))


def test_provider_selection(tmp_data):
    with db.session() as conn:
        settings = db.get_settings(conn)
    assert ai.current_provider(settings) == "anthropic"
    assert not ai.has_key(settings)
    with pytest.raises(ai.AIAuthError):
        ai.make_analyzer(settings)

    secrets_store.set_secret("openai_api_key", "sk-openai")
    settings["ai_provider"] = "openai"
    assert ai.has_key(settings)
    analyzer = ai.make_analyzer(settings)
    assert isinstance(analyzer, ai.OpenAIAnalyzer) and analyzer.model == "gpt-6-luna"
    settings["openai_model"] = "gpt-6.1-sol"
    assert ai.make_analyzer(settings).model == "gpt-6.1-sol"
    settings["ai_provider"] = "nonsense"
    assert ai.current_provider(settings) == "anthropic"


def test_settings_page_switches_provider_when_only_openai_key_saved(tmp_data):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        r = client.post("/settings/keys", data={"openai_api_key": "sk-proj-abcdefghijklmnop"}, follow_redirects=True)
        assert r.status_code == 200
        assert "sk-p…mnop" in r.text
        with db.session() as conn:
            assert db.get_settings(conn)["ai_provider"] == "openai"
        # a second key doesn't override the choice; the user picks explicitly
        client.post("/settings/keys", data={"anthropic_api_key": "sk-ant-abcdefghijkl"})
        with db.session() as conn:
            assert db.get_settings(conn)["ai_provider"] == "openai"
        client.post("/settings/options", data={"ai_provider": "anthropic", "openai_model": "gpt-6.1-sol"})
        with db.session() as conn:
            s = db.get_settings(conn)
        assert s["ai_provider"] == "anthropic" and s["openai_model"] == "gpt-6.1-sol"
        client.post("/settings/keys", data={"clear": "anthropic_api_key"})
        r = client.get("/insights")
        assert "Add your Anthropic (Claude) API key" in r.text  # the prompt names the provider in use
