import json
import httpx
import pytest
from rag.models import Models
from rag.config import Settings, RagError, OLLAMA_URL


@pytest.mark.parametrize("vectors", [[[1.0]], [[0.0] * 768], []])
def test_invalid_embedding_rejected(vectors):
    client = httpx.Client(
        base_url=OLLAMA_URL,
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"embeddings": vectors})),
    )
    with pytest.raises(RagError):
        Models(client).embed(["hello"])


def test_embeddings_have_correct_prefix_and_do_not_truncate():
    calls = []

    def handler(req):
        assert req.url.host == "127.0.0.1"
        calls.append(json.loads(req.content))
        return httpx.Response(200, json={"embeddings": [[0.1] * 768]})

    m = Models(httpx.Client(base_url=OLLAMA_URL, transport=httpx.MockTransport(handler)))
    m.embed(["document"])
    m.embed(["question"], query=True)
    assert calls[0]["input"] == ["search_document: document"]
    assert calls[1]["input"] == ["search_query: question"] and calls[0]["truncate"] is False
    assert calls[0]["keep_alive"] == "10m"


def test_provider_catalog_and_missing_keys_are_explicit():
    catalog = {(item.provider, item.task): item for item in Models.capabilities()}
    assert catalog["ollama", "chat"].local is True
    assert catalog["openai", "chat"].connection_test_may_cost_money is True
    assert ("anthropic", "embedding") not in catalog
    with pytest.raises(RagError, match="OpenAI API key"):
        Models(settings=Settings(chat_provider="openai", chat_model="gpt-4o-mini"))


def test_openai_embeddings_are_sorted_and_dimension_checked():
    requests = []

    def handler(req):
        requests.append(json.loads(req.content))
        return httpx.Response(
            200, json={"data": [{"index": 1, "embedding": [0.2] * 768}, {"index": 0, "embedding": [0.1] * 768}]}
        )

    settings = Settings(
        embedding_provider="openai", embedding_model="text-embedding-3-small", openai_api_key="private-test-key"
    )
    client = httpx.Client(base_url="https://api.openai.com/v1", transport=httpx.MockTransport(handler))
    result = Models(settings=settings, clients={"openai": client}).embed(["one", "two"])
    assert result[0][0] == 0.1 and requests[0]["dimensions"] == 768


def test_openai_structured_output_and_anthropic_tool_output():
    openai = httpx.Client(
        base_url="https://api.openai.com/v1",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"choices": [{"message": {"content": '{"query":"hello"}'}}]})
        ),
    )
    openai_settings = Settings(chat_provider="openai", chat_model="gpt-4o-mini", openai_api_key="private-test-key")
    from rag.types import SearchQuery

    assert Models(settings=openai_settings, clients={"openai": openai}).structured([], SearchQuery).query == "hello"

    anthropic = httpx.Client(
        base_url="https://api.anthropic.com/v1",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200, json={"content": [{"type": "tool_use", "name": "return_result", "input": {"query": "hello"}}]}
            )
        ),
    )
    anthropic_settings = Settings(
        chat_provider="anthropic", chat_model="claude-3-5-haiku-latest", anthropic_api_key="private-test-key"
    )
    assert (
        Models(settings=anthropic_settings, clients={"anthropic": anthropic}).structured([], SearchQuery).query
        == "hello"
    )


def test_wrong_supabase_project_rejected():
    with pytest.raises(RagError):
        Settings(
            "postgresql://postgres@db.other.supabase.co/postgres", "folder", "https://abcdefghijklmnopqrst.supabase.co"
        ).validate()
    Settings(
        "postgresql://postgres.abcdefghijklmnopqrst:secret@aws-0-example.pooler.supabase.com:5432/postgres",
        "folder",
        "https://abcdefghijklmnopqrst.supabase.co",
    ).validate()
