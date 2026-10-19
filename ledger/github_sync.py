from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import PurePosixPath
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import storage
from .models import ValidationError


class SyncError(RuntimeError):
    pass


@dataclass
class Settings:
    owner: str = "show1133"
    repo: str = "Accounting"
    branch: str = "main"
    path: str = "data/ledger.json"
    token: str = field(default="", repr=False)

    @classmethod
    def from_env(cls) -> Settings:
        settings = cls(
            owner=os.getenv("GITHUB_OWNER", "show1133"),
            repo=os.getenv("GITHUB_REPO", "Accounting"),
            branch=os.getenv("GITHUB_BRANCH", "main"),
            path=os.getenv("LEDGER_PATH", "data/ledger.json"),
            token=os.getenv("GITHUB_TOKEN", ""),
        )
        if not all((settings.owner, settings.repo, settings.branch, settings.path)):
            raise SyncError("GitHub 擁有者、儲存庫、分支與路徑不可空白")
        path = PurePosixPath(settings.path)
        if path.is_absolute() or ".." in path.parts or "\\" in settings.path:
            raise SyncError("LEDGER_PATH 必須是儲存庫內的相對路徑")
        return settings


class GitHubSync:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=0.3, status_forcelist=[429, 500, 502, 503, 504],
                        allowed_methods=frozenset(["GET"]), respect_retry_after_header=False)
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.settings.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        self.base_url = "https://api.github.com/repos/" + quote(self.settings.owner, safe="") + "/" + quote(self.settings.repo, safe="")
        self.content_url = self.base_url + "/contents/" + quote(self.settings.path, safe="/")
        self.state_file = storage.DATA_DIR / ".github-sync.json"

    def _request(self, method: str, url: str, **kwargs):
        if not self.settings.token:
            raise SyncError("請先在 .env 或環境變數設定 GITHUB_TOKEN")
        try:
            response = self.session.request(method, url, timeout=(10, 45), **kwargs)
        except requests.RequestException:
            raise SyncError("GitHub 連線失敗，請檢查網路；上傳若逾時，請先確認遠端狀態再重試") from None
        if response.status_code == 404 and kwargs.pop("params", None) is not None:
            return None
        if response.status_code not in (200, 201):
            messages = {
                401: "權杖無效或已到期",
                403: "權限不足或 API 額度已用盡，請確認 Contents: Read and write",
                404: "找不到儲存庫，請確認名稱、分支及權杖存取範圍",
                409: "遠端版本衝突，未覆寫；請先下載並合併帳本",
                422: "GitHub 拒絕寫入，請確認分支、路徑與儲存庫規則",
            }
            raise SyncError(messages.get(response.status_code, f"GitHub 暫時無法處理（HTTP {response.status_code}）"))
        try:
            return response.json()
        except ValueError:
            raise SyncError("GitHub 回傳格式無效") from None

    def _key(self) -> str:
        value = f"{self.base_url}/{self.settings.branch}/{self.settings.path}"
        return hashlib.sha256(value.encode()).hexdigest()

    def _state(self) -> dict:
        if not self.state_file.exists():
            return {}
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            raise SyncError("同步狀態檔損壞，請保留本機備份後重新下載帳本") from None

    def _remember(self, sha: str) -> None:
        state = self._state()
        state[self._key()] = sha
        storage.atomic_json(self.state_file, state)

    def _remote(self):
        return self._request("GET", self.content_url, params={"ref": self.settings.branch})

    def push(self, records, *, dry_run: bool = False, force: bool = False,
             allow_public: bool = False) -> str:
        payload = json.dumps([row.to_dict() for row in records], ensure_ascii=False, indent=2) + "\n"
        storage.records_from_payload(json.loads(payload))
        if dry_run:
            return (f"試跑：{len(records)} 筆 → {self.settings.owner}/{self.settings.repo} "
                    f"[{self.settings.branch}] {self.settings.path}；未連線、未上傳")
        repository = self._request("GET", self.base_url)
        if repository.get("private") is not True and not allow_public:
            raise SyncError("此為公開儲存庫，帳務將對所有人公開。建議改為私人儲存庫；確認公開請加 --allow-public")
        remote = self._remote()
        if remote is not None and (not isinstance(remote, dict) or remote.get("type") != "file" or not remote.get("sha")):
            raise SyncError("遠端帳本路徑不是有效檔案")
        if remote and not force and self._state().get(self._key()) != remote["sha"]:
            raise SyncError("遠端帳本尚未下載或已被修改；請先 pull 合併，確認覆寫請加 --force")
        body = {"message": "Update daily ledger", "branch": self.settings.branch,
                "content": base64.b64encode(payload.encode("utf-8")).decode("ascii")}
        if remote:
            body["sha"] = remote["sha"]
        result = self._request("PUT", self.content_url, json=body)
        self._remember(result["content"]["sha"])
        return "帳本已上傳 GitHub"

    def pull(self, *, force: bool = False) -> str:
        if storage.LEDGER_FILE.exists() and storage.load_records() and not force:
            raise SyncError("本機已有帳務；下載會取代本機帳本，請先匯出備份，確認後加 --force")
        remote = self._remote()
        if remote is None:
            raise SyncError("遠端帳本不存在，未修改本機資料")
        try:
            if remote.get("encoding") != "base64" or remote.get("type") != "file":
                raise ValueError
            payload = json.loads(base64.b64decode(remote["content"]).decode("utf-8-sig"))
            records = storage.records_from_payload(payload)
        except (KeyError, ValueError, TypeError, ValidationError):
            raise SyncError("遠端帳本格式或資料驗證失敗，未修改本機資料") from None
        storage.save_records(records)
        self._remember(remote["sha"])
        return f"已下載 {len(records)} 筆帳務（原本資料已自動備份）"