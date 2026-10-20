from types import SimpleNamespace
import pytest
from rag.chat import Chat, MISSING, PRIVATE_GREETING
from rag.types import AnswerDraft, SearchQuery, Source
from rag.config import RagError


class Store:
    def __init__(self):
        self.saved = []
        self.turns = []
        self.sources = [
            Source(
                number=1,
                file_id="a",
                file_name="A",
                version="1",
                url="https://drive.google.com/file/d/a/view",
                text="Refunds within 14 days.",
                score=0.7,
            )
        ]

    def history(self, s):
        return self.turns

    def revision(self):
        return 1

    def search(self, v):
        return self.sources, 1

    def save_turn(self, *args):
        self.saved.append(args)


class Models:
    def __init__(self):
        self.calls = []
        self.ids = [1]
        self.supported = True

    def embed(self, texts, query=False):
        self.calls.append(("embed", texts, query))
        return [[1.0] * 768]

    def structured(self, messages, schema):
        self.calls.append(("structured", messages))
        if schema is SearchQuery:
            return SearchQuery(query="What is the refund time limit?")
        return AnswerDraft(answer="Within 14 days.", citation_ids=self.ids if self.supported else [])


def test_search_precedes_answer_and_sources_are_real():
    s = Store()
    m = Models()
    a = Chat(s, m).answer("s", "Refund policy?")
    assert m.calls[0][0] == "embed" and a.sources[0].file_id == "a" and len(s.saved) == 1


def test_chat_progress_tracks_real_work_before_displaying_saved_answer():
    stages = []
    s = Store()
    answer = Chat(s, Models(), on_stage=stages.append).answer("s", "What is the refund policy?")
    assert stages == [
        "Reading recent conversation",
        "Finding relevant passages",
        "Writing an answer from the passages",
        "Checking cited sources",
        "Saving the verified answer",
    ]
    assert answer.sources and len(s.saved) == 1


def test_empty_library_never_calls_generator():
    s = Store()
    s.sources = []
    m = Models()
    a = Chat(s, m).answer("s", "Missing fact?")
    assert a.text == MISSING and len(m.calls) == 1


def test_greeting_is_friendly_uncited_and_skips_models():
    s = Store()
    m = Models()
    a = Chat(s, m).answer("s", "Hello!")
    assert a.text == PRIVATE_GREETING and a.sources == [] and m.calls == []
    assert a.timings["total"] >= 0 and len(s.saved) == 1


def test_unsupported_and_invented_citation():
    s = Store()
    m = Models()
    m.supported = False
    assert Chat(s, m).answer("s", "Unknown?").text == MISSING
    m.supported = True
    m.ids = [99]
    with pytest.raises(RagError):
        Chat(s, m).answer("s", "Unknown?")
    assert len(s.saved) == 1


def test_followup_rewrites_search_from_history():
    s = Store()
    s.turns = [{"question": "Refunds?", "answer": "14 days"}]
    m = Models()
    Chat(s, m).answer("s", "What is the deadline?")
    assert m.calls[0][0] == "structured" and m.calls[1][1] == ["What is the refund time limit?"]


def test_standalone_question_skips_rewrite_even_with_history():
    s = Store()
    s.turns = [{"question": "Refunds?", "answer": "14 days"}]
    m = Models()
    Chat(s, m).answer("s", "What is the project code?")
    assert m.calls[0][0] == "embed"


def test_ambiguous_question_without_context_asks_for_clarification():
    s = Store()
    m = Models()
    a = Chat(s, m).answer("s", "Tell me more")
    assert "Which project" in a.text and not a.sources and m.calls == []


def test_context_is_bounded_and_citations_must_be_in_sent_evidence():
    s = Store()
    s.sources = [
        Source(
            number=1,
            file_id="a",
            file_name="A",
            version="1",
            url="https://drive.google.com/file/d/a/view",
            text="x" * 1500,
            score=0.7,
        ),
        Source(
            number=2,
            file_id="b",
            file_name="B",
            version="1",
            url="https://drive.google.com/file/d/b/view",
            text="y" * 1500,
            score=0.6,
        ),
    ]
    m = Models()
    m.settings = SimpleNamespace(max_context_chars=1000)
    m.ids = [2]
    with pytest.raises(RagError):
        Chat(s, m).answer("s", "What is the refund policy?")


def test_question_length():
    with pytest.raises(RagError):
        Chat(Store(), Models()).answer("s", "x" * 3001)


def test_activity_failure_does_not_misreport_a_saved_answer(caplog):
    store = Store()

    def broken(*args, **kwargs):
        raise RuntimeError("private database detail")

    store.log_activity = broken
    answer = Chat(store, Models()).answer("session", "What is the refund policy?")
    assert answer.sources and len(store.saved) == 1
    assert "activity could not be recorded" in caplog.text and "private database detail" not in caplog.text
