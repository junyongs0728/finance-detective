import json, os, ssl, time, threading, hashlib, tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from datetime import datetime, timezone
import certifi
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[3]
NETWORK_LOCK=threading.Lock()

class ProviderError(Exception):
    def __init__(self,message,code="provider_error"):
        super().__init__(message);self.code=code


def setting(name):
    return os.environ.get(name) or dotenv_values(ROOT/".env").get(name) or ""


def fetch(url):
    # Serialize provider requests to keep this local app below 3 requests/sec.
    with NETWORK_LOCK:
        time.sleep(.35)
        req=Request(url,headers={"User-Agent":setting("SEC_USER_AGENT") or "FinanceDetective educational financial analysis", "Accept":"application/json,application/zip,*/*"})
        try:
            with urlopen(req,timeout=15,context=ssl.create_default_context(cafile=certifi.where())) as r:
                return r.read()
        except HTTPError as e:
            raise ProviderError(f"공시 공급자가 요청에 응답하지 못했습니다 (HTTP {e.code}). 잠시 후 다시 시도해주세요.") from None
        except (URLError,TimeoutError):
            raise ProviderError("공시 공급자 연결 시간이 초과되었거나 연결할 수 없습니다.") from None


def fetch_json(url):
    try:return json.loads(fetch(url))
    except ValueError:raise ProviderError("공시 공급자 응답 형식이 올바르지 않습니다.") from None


def write_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    # Distinct temporary files also support simultaneous writes from different workers.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        try:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def preserve_raw(company_id,payload):
    raw=json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()
    digest=hashlib.sha256(raw).hexdigest()
    path=ROOT/"data/raw/companies"/company_id.replace(":","_")/(digest+".json")
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    return digest


def now():return datetime.now(timezone.utc).isoformat()
