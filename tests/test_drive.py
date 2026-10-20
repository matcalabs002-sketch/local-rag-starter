import pytest
from rag.drive import Drive, save_client
from rag.config import RagError


class Request:
    def __init__(self, data):
        self.data = data

    def execute(self, **kw):
        return self.data


class Service:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.params = []

    def files(self):
        return self

    def get(self, **kw):
        return Request({"id": "folder", "mimeType": "application/vnd.google-apps.folder", "trashed": False})

    def list(self, **kw):
        self.params.append(kw)
        return Request(next(self.pages))


def file(id="a", mime="text/plain"):
    return {"id": id, "name": "A", "mimeType": mime, "version": "9007199254740993", "parents": ["folder"]}


def test_complete_pagination_and_unsupported():
    s = Service([{"files": [file()], "nextPageToken": "next"}, {"files": [file("b", "image/png")]}])
    files, skipped = Drive("folder", s).snapshot()
    assert len(files) == 1 and files[0].version == "9007199254740993" and skipped
    assert s.params[1]["pageToken"] == "next"


@pytest.mark.parametrize(
    "pages",
    [
        [{"files": [], "incompleteSearch": True}],
        [{}],
        [{"files": [file(), file()]}],
        [{"files": [{"id": "a"}]}],
        [{"files": [], "nextPageToken": "x"}, {"files": [], "nextPageToken": "x"}],
    ],
)
def test_invalid_snapshots_fail(pages):
    with pytest.raises(RagError):
        Drive("folder", Service(pages)).snapshot()


def test_empty_folder():
    assert Drive("folder", Service([{"files": []}])).snapshot() == ([], [])


def test_oauth_rejects_other_endpoints():
    with pytest.raises(RagError):
        save_client(
            b'{"installed":{"client_id":"a","client_secret":"b","auth_uri":"https://evil.example","token_uri":"https://evil.example"}}'
        )


class VerificationService(Service):
    def __init__(self, current, pages):
        super().__init__(pages)
        self.current = current

    def get(self, **kw):
        if kw["fileId"] == "folder":
            return super().get(**kw)
        return Request(self.current)


def verify_file(current, pages):
    from rag.types import DriveFile

    record = DriveFile("a", "A", "9007199254740993", "text/plain", "https://drive.google.com/file/d/a/view")
    Drive("folder", VerificationService(current, pages)).verify(record)


def test_verify_omitted_parents_uses_fresh_folder_listing():
    verify_file({"id": "a", "version": "9007199254740993"}, [{"files": [file()]}])


@pytest.mark.parametrize(
    "pages",
    [
        [{"files": []}],
        [{"files": [{**file(), "version": "9007199254740994"}]}],
        [{"files": [file()], "incompleteSearch": True}],
    ],
)
def test_verify_missing_parents_never_bypasses_membership_or_version(pages):
    with pytest.raises(RagError):
        verify_file({"id": "a", "version": "9007199254740993"}, pages)


@pytest.mark.parametrize(
    "current",
    [
        {"id": "a", "version": "9007199254740994", "parents": ["folder"]},
        {"id": "a", "version": "9007199254740993", "parents": []},
        {"id": "a", "version": "9007199254740993", "parents": ["other"]},
        {"id": "a", "version": "9007199254740993", "parents": ["folder"], "trashed": True},
        {"id": "a", "parents": ["folder"]},
    ],
)
def test_verify_rejects_changed_removed_trashed_or_missing_version(current):
    with pytest.raises(RagError):
        verify_file(current, [])


def test_verify_explicit_membership_needs_no_fallback():
    verify_file({"id": "a", "version": "9007199254740993", "parents": ["folder"]}, [])
