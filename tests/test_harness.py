import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from scopebrief.benchmark import run_benchmark
from scopebrief.documents import parse_markdown
from scopebrief.harness import answer
from scopebrief.model import ChatModel
from scopebrief.settings import Settings
from scopebrief.store import Store


@pytest.fixture
def store(tmp_path):
    db = Store(tmp_path / "test.db")
    db.initialize()
    return db


def test_benchmark_targets_versions_and_avoids_leakage():
    report = asyncio.run(run_benchmark())
    harness = report["metrics"]["harness"]
    assert harness["passed"] == harness["total"]
    assert harness["gold_hits"] == harness["gold_total"]
    assert harness["stale_citations"] == harness["leak_cases"] == 0
    assert report["metrics"]["baseline"]["stale_citations"] > 0


def test_headings_do_not_parse_inside_code_fences():
    body = "## 回退 [rollback]\r\n\r\n用以下命令\r\n~~~sh\r\n# 一行注释\r\n~~~\r\n"
    [section] = parse_markdown(body)
    assert section.topic == "rollback"
    assert section.start_line == 3
    assert section.end_line == 6
    assert "# 一行注释" in section.content


def test_long_line_is_rejected_and_does_not_create_empty_revision(store):
    with pytest.raises(ValueError, match="换行"):
        store.publish("beichen", "release", "修订", "数" * 800)
    assert sorted(
        d["revision"]
        for d in store.documents("member")
        if d["project_id"] == "beichen" and d["key"] == "release"
    ) == [1, 2]


def test_concurrent_publish_assigns_distinct_monotonic_versions(store):
    def publish(index):
        return store.publish("beichen", "release", f"修订 {index}", f"第 {index} 次并行更新。")

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(publish, range(4)))
    assert {r.rsplit("@", 1)[1] for r in ids} == {"3", "4", "5", "6"}
    rows = store.evidence("member", ["beichen"], current_only=True)
    assert {e.revision for e in rows if e.key == "release"} == {6}


def test_current_decisions_conflict_and_require_human_review(store):
    store.publish("beichen", "release-qa", "QA 结论", "## QA 签字 [decision=hold]\n等待复测。")
    result = asyncio.run(answer(store, "member", "北辰可以上线吗？", ["beichen"]))
    assert result["status"] == "insufficient"
    assert result["findings"][0]["status"] == "conflict"
    assert {e["decision"] for e in result["citations"]} == {"go", "hold"}


@pytest.mark.parametrize(
    ("provider_quote", "source_id", "expected"),
    [
        ("北辰可进入 10% 灰度", "E1", "model"),
        ("北辰可进入 99% 灰度", "E1", "fallback"),
        ("北辰可进入 10% 灰度", "E2", "fallback"),
    ],
)
def test_model_quotes_are_checked_and_input_is_role_scoped(
    store,
    provider_quote,
    source_id,
    expected,
):
    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        user_input = json.loads(payload["messages"][1]["content"])
        assert "ORBIT-734" not in json.dumps(user_input, ensure_ascii=False)
        assert len(user_input["evidence"]) == 1
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"highlights": [{"source_id": source_id, "quote": provider_quote}]}
                            )
                        }
                    }
                ],
                "usage": {"total_tokens": 123},
            },
        )

    async def run():
        config = Settings(model_base_url="https://stub.invalid/v1", model_name="fixture")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await answer(
                store,
                "member",
                "北辰可以上线吗？",
                ["beichen", "bridge"],
                model=ChatModel(config, client),
            )

    result = asyncio.run(run())
    assert result["generator"] == expected
    assert result["findings"][0]["status"] == "go"
    assert "99%" not in result["citations"][0]["quote"]
    if expected == "model":
        assert result["citations"][0]["quote"] == provider_quote
        assert result["usage"] == {"total_tokens": 123}


def test_model_timeout_degrades_to_evidence(store):
    async def handler(_request):
        await asyncio.sleep(1)
        raise AssertionError("timeout should interrupt this handler")

    async def run():
        config = Settings(
            model_base_url="https://stub.invalid/v1",
            model_name="fixture",
            model_timeout=0.01,
        )
        events = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await answer(
                store,
                "member",
                "潮汐可以上线吗？",
                ["tide"],
                model=ChatModel(config, client),
                on_event=lambda stage, *_: events.append(stage),
            )
        assert "fallback" in events
        return result

    assert asyncio.run(run())["generator"] == "fallback"
