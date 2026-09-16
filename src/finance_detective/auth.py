"""Local developer identity or server-issued access codes; never trust a client user ID."""
import hashlib
from urllib.parse import urlsplit
from finance_detective.providers.common import setting, ProviderError
from finance_detective.rag import store

COOKIE='fd_access'


def check_origin(request):
    origin=request.headers.get('origin')
    if origin and urlsplit(origin).netloc!=request.headers.get('host'):
        raise ProviderError('다른 사이트에서 시작된 요청은 허용하지 않습니다.','ai_forbidden')


def token_user(token):
    if not token or len(token)>200:return None
    digest=hashlib.sha256(token.encode()).hexdigest()
    with store.connection() as db:
        row=db.execute('SELECT id FROM ai_users WHERE token_hash=%s AND disabled=false',(digest,)).fetchone()
    return row['id'] if row else None


def resolve(request,required=False):
    check_origin(request)
    mode=setting('AI_AUTH_MODE') or 'token'  # Deployment fails closed unless local mode is explicit.
    if mode not in ('local','token'):raise ProviderError('AI 인증 모드 설정을 확인해주세요.','ai_auth_config')
    if mode=='local':
        peer=request.client.host if request.client else ''
        host=request.url.hostname
        if peer not in ('127.0.0.1','::1') or host not in ('127.0.0.1','localhost','::1'):
            raise ProviderError('로컬 개발 모드는 이 컴퓨터에서만 사용할 수 있습니다.','ai_forbidden')
        return 'local-owner'
    header=request.headers.get('authorization','')
    token=header[7:] if header.startswith('Bearer ') else request.cookies.get(COOKIE,'')
    user=token_user(token)
    if required and not user:raise ProviderError('AI 분석 이용 코드를 입력해주세요.','ai_auth_required')
    return user
