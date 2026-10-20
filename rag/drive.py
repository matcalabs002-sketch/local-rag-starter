import io
import json

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
except ImportError:
    Credentials = Request = InstalledAppFlow = build = MediaIoBaseDownload = None
    httplib2 = AuthorizedHttp = None


def require_google():
    if build is None:
        raise RagError("Install the optional Drive integration: pip install -e '.[drive]'")


from .config import PRIVATE, MAX_FILE_BYTES, RagError, write_private
from .types import DriveFile

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
GOOGLE_DOC = "application/vnd.google-apps.document"
FOLDER = "application/vnd.google-apps.folder"
SUPPORTED = {
    GOOGLE_DOC,
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
FIELDS = "id,name,mimeType,version,parents,trashed,size"


def save_client(raw: bytes):
    try:
        data = json.loads(raw)
        entry = data["installed"]
        if not entry["client_id"] or not entry["client_secret"]:
            raise ValueError()
        # Only genuine Google OAuth endpoints; never follow arbitrary URLs in an uploaded file.
        if (
            entry["auth_uri"] != "https://accounts.google.com/o/oauth2/auth"
            or entry["token_uri"] != "https://oauth2.googleapis.com/token"
        ):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise RagError("Choose the Desktop app OAuth JSON downloaded from Google Cloud.") from None
    write_private(PRIVATE / "google-client.json", json.dumps(data))


def authorize():
    require_google()
    path = PRIVATE / "google-client.json"
    if not path.exists():
        raise RagError("Upload your Google Desktop app OAuth JSON in Setup first.")
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)
        creds = flow.run_local_server(
            host="localhost",
            port=0,
            open_browser=True,
            timeout_seconds=180,
            authorization_prompt_message="Finish connecting Google in the browser.",
            success_message="Google Drive connected. You can close this tab and return to Document Library.",
            access_type="offline",
            prompt="consent",
        )
        write_private(PRIVATE / "google-token.json", creds.to_json())
    except Exception:
        raise RagError("Google sign-in was not completed. Check the OAuth test-user setting and try again.") from None


class Drive:
    def __init__(self, folder, service=None):
        self.folder = folder
        if service is not None:
            self.service = service
            return
        require_google()
        try:
            creds = Credentials.from_authorized_user_file(str(PRIVATE / "google-token.json"), SCOPES)
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                write_private(PRIVATE / "google-token.json", creds.to_json())
            if not creds.valid:
                raise ValueError()
            self.service = build(
                "drive", "v3", http=AuthorizedHttp(creds, http=httplib2.Http(timeout=60)), cache_discovery=False
            )
        except Exception:
            raise RagError("Connect Google Drive in Setup. Your sign-in may have expired.") from None

    @staticmethod
    def request(request):
        try:
            return request.execute(num_retries=3)
        except Exception:
            raise RagError(
                "Google Drive could not complete the request. Check your connection and folder access, then retry."
            ) from None

    def snapshot(self):
        folder = self.request(
            self.service.files().get(fileId=self.folder, fields="id,mimeType,trashed,driveId", supportsAllDrives=True)
        )
        if folder.get("id") != self.folder or folder.get("mimeType") != FOLDER or folder.get("trashed"):
            raise RagError("The selected folder is missing or in the bin. No documents were removed.")
        params = dict(
            q=f"'{self.folder}' in parents and trashed = false",
            fields=f"nextPageToken,incompleteSearch,files({FIELDS})",
            pageSize=1000,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            corpora="user",
        )
        if folder.get("driveId"):
            params.update(corpora="drive", driveId=folder["driveId"])
        files = []
        skipped = []
        seen = set()
        tokens = set()
        while True:
            page = self.request(self.service.files().list(**params))
            if page.get("incompleteSearch") or not isinstance(page.get("files"), list):
                raise RagError("Google returned an incomplete folder list. No documents were removed.")
            for raw in page["files"]:
                if (
                    not all(raw.get(k) for k in ("id", "name", "version", "mimeType"))
                    or self.folder not in raw.get("parents", [])
                    or raw.get("trashed")
                ):
                    raise RagError("Google returned incomplete file details. No documents were removed.")
                if raw["id"] in seen:
                    raise RagError("The folder changed while it was being listed. Please retry sync.")
                seen.add(raw["id"])
                if raw["mimeType"] not in SUPPORTED:
                    skipped.append(
                        raw["name"] + " (folder)" if raw["mimeType"] == FOLDER else raw["name"] + " (unsupported type)"
                    )
                    continue
                files.append(
                    DriveFile(
                        raw["id"],
                        raw["name"],
                        str(raw["version"]),
                        raw["mimeType"],
                        f"https://drive.google.com/file/d/{raw['id']}/view",
                        int(raw.get("size", 0)),
                    )
                )
            token = page.get("nextPageToken")
            if not token:
                break
            if token in tokens:
                raise RagError("Google repeated a listing page. No documents were removed.")
            tokens.add(token)
            params["pageToken"] = token
        return files, skipped

    def download(self, file):
        if file.size > MAX_FILE_BYTES:
            raise RagError("This document exceeds the 50 MB file limit. Split it into smaller documents.")
        request = (
            self.service.files().export_media(fileId=file.id, mimeType="text/plain")
            if file.mime_type == GOOGLE_DOC
            else self.service.files().get_media(fileId=file.id, supportsAllDrives=True)
        )
        output = io.BytesIO()
        downloader = MediaIoBaseDownload(output, request, chunksize=1024 * 1024)
        try:
            done = False
            while not done:
                _, done = downloader.next_chunk(num_retries=3)
                if output.tell() > MAX_FILE_BYTES:
                    raise RagError("This document exceeds the 50 MB file limit.")
        except RagError:
            raise
        except Exception:
            raise RagError(
                "A document could not be downloaded. It may have moved, lost access, or exceeded Google’s export limit. Its previous version was kept."
            ) from None
        return output.getvalue()

    def verify(self, file):
        current = self.request(self.service.files().get(fileId=file.id, fields=FIELDS, supportsAllDrives=True))
        unchanged = (
            current.get("id") == file.id and not current.get("trashed") and str(current.get("version")) == file.version
        )
        if unchanged and "parents" not in current:
            # Drive can omit parents on files.get even when files.list returns them.
            # Missing metadata is not proof of a move. Recheck the complete folder,
            # preserving the same pagination, membership and version safeguards.
            fresh_files, _ = self.snapshot()
            unchanged = any(candidate.id == file.id and candidate.version == file.version for candidate in fresh_files)
        elif unchanged:
            unchanged = self.folder in current["parents"]
        if not unchanged:
            raise RagError(
                "The document changed or left the folder during indexing. This attempt was not published; any previously indexed version remains available. The next sync will retry."
            )
