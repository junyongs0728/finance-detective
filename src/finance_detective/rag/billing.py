"""Atomic budget reservations. All money is integer micro-USD, never float dollars."""
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal, ROUND_CEILING
import uuid
from finance_detective.providers.common import setting, ProviderError
from . import store

USER=ContextVar('ai_user',default=None)
REQUEST=ContextVar('ai_request',default=None)
PRICE_VERSION='openai-standard-2026-09-16'
# USD per million tokens == micro-USD per token. Reviewed official price snapshot.
PRICES={'gpt-4.1-mini':('0.4','0.1','1.6'),'gpt-4.1':('2','0.5','8'),
        'text-embedding-3-small':('0.02','0.02','0')}
for alias in ('gpt-4.1-mini','gpt-4.1'):
    PRICES[alias+'-2025-04-14']=PRICES[alias]
DEFAULTS={'AI_DAILY_BUDGET_USD':'5','AI_MONTHLY_BUDGET_USD':'30','AI_USER_DAILY_BUDGET_USD':'1',
          'AI_REQUEST_BUDGET_USD':'0.15','AI_USER_DAILY_REQUESTS':'50','AI_MAX_CONCURRENT_REQUESTS':'4',
          'AI_MAX_INPUT_TOKENS':'64000','AI_CACHE_TTL_SECONDS':'86400'}
CHARGE='COALESCE(actual_microusd,reserved_microusd)'


def number(name):
    try:
        value=Decimal(setting(name) or DEFAULTS[name])
        if not value.is_finite() or value<0:raise ValueError()
        return value
    except (ValueError,ArithmeticError):raise ProviderError('AI 비용 설정값을 확인해주세요.','ai_cost_config') from None


def dollars(name):return int(number(name)*1_000_000)


def price(model,input_tokens,output_tokens=0,cached_tokens=0):
    if model not in PRICES:raise ProviderError('이 모델의 요금표가 등록되어 있지 않아 호출을 중단했습니다.','ai_unpriced_model')
    if min(input_tokens,output_tokens,cached_tokens)<0 or cached_tokens>input_tokens:raise ValueError('Invalid usage')
    inp,cached,out=map(Decimal,PRICES[model])
    return int(((input_tokens-cached_tokens)*inp+cached_tokens*cached+output_tokens*out).to_integral_value(rounding=ROUND_CEILING))


@contextmanager
def as_user(user_id):
    token=USER.set(user_id)
    try:yield
    finally:USER.reset(token)


def require_user():
    user=USER.get()
    if not user:raise ProviderError('AI 분석을 사용하려면 이용 코드로 연결해주세요.','ai_auth_required')
    return user


def lock(db):db.execute('SELECT pg_advisory_xact_lock(72016002)')


def totals(db,user_id,request_id=None):
    return db.execute(f'''SELECT
        COALESCE(SUM({CHARGE}) FILTER(WHERE created_at>=date_trunc('day',now())),0) AS day,
        COALESCE(SUM({CHARGE}) FILTER(WHERE created_at>=date_trunc('month',now())),0) AS month,
        COALESCE(SUM({CHARGE}) FILTER(WHERE user_id=%s AND created_at>=date_trunc('day',now())),0) AS user_day,
        COALESCE(SUM({CHARGE}) FILTER(WHERE request_id=%s),0) AS request
        FROM ai_calls WHERE created_at>=date_trunc('month',now()) OR request_id=%s''',
        (user_id,request_id,request_id)).fetchone()


@contextmanager
def operation(kind):
    user=require_user(); rid=uuid.uuid4().hex
    with store.connection() as db:
        lock(db)
        # Recover abandoned workers after a generous lease; keep their money held.
        db.execute("""UPDATE ai_calls SET status='uncertain',finished_at=now()
            WHERE status='reserved' AND request_id IN
            (SELECT id FROM ai_requests WHERE status='active' AND created_at<now()-interval '15 minutes')""")
        db.execute("UPDATE ai_requests SET status='failed',ended_at=now() WHERE status='active' AND created_at<now()-interval '15 minutes'")
        if user=='local-owner':db.execute("INSERT INTO ai_users(id) VALUES('local-owner') ON CONFLICT DO NOTHING")
        owner=db.execute('SELECT disabled FROM ai_users WHERE id=%s',(user,)).fetchone()
        if not owner or owner['disabled']:raise ProviderError('사용할 수 없는 이용 코드입니다.','ai_auth_required')
        count=db.execute("SELECT count(*) AS n FROM ai_requests WHERE user_id=%s AND created_at>=date_trunc('day',now())",(user,)).fetchone()['n']
        if count>=int(number('AI_USER_DAILY_REQUESTS')):raise ProviderError('오늘의 AI 분석 횟수를 모두 사용했습니다. 수치 조회는 계속 가능합니다.','ai_user_limit')
        active=db.execute("SELECT count(*) AS total,count(*) FILTER(WHERE user_id=%s) AS mine FROM ai_requests WHERE status='active'",(user,)).fetchone()
        if active['mine'] or active['total']>=int(number('AI_MAX_CONCURRENT_REQUESTS')):
            raise ProviderError('진행 중인 AI 분석이 있습니다. 잠시 후 다시 시도해주세요.','ai_busy')
        db.execute('INSERT INTO ai_requests(id,user_id,kind) VALUES(%s,%s,%s)',(rid,user,kind))
    token=REQUEST.set(rid); status='failed'
    try:
        yield rid
        status='completed'
    finally:
        REQUEST.reset(token)
        with store.connection() as db:
            db.execute('UPDATE ai_requests SET status=%s,ended_at=now() WHERE id=%s',(status,rid))


def reserve(stage,model,input_bound,max_output=0):
    user=require_user(); rid=REQUEST.get()
    if not rid:raise ProviderError('비용 추적 범위 밖의 AI 호출을 차단했습니다.','ai_cost_context')
    cost=price(model,input_bound,max_output)
    cid=uuid.uuid4().hex
    with store.connection() as db:
        lock(db)
        request=db.execute('SELECT status,user_id FROM ai_requests WHERE id=%s',(rid,)).fetchone()
        if not request or request['status']!='active' or request['user_id']!=user:
            raise ProviderError('AI 실행 시간이 만료되어 추가 호출을 중단했습니다.','ai_request_expired')
        usage=totals(db,user,rid)
        for field,setting_name in [('day','AI_DAILY_BUDGET_USD'),('month','AI_MONTHLY_BUDGET_USD'),
                                   ('user_day','AI_USER_DAILY_BUDGET_USD'),('request','AI_REQUEST_BUDGET_USD')]:
            if usage[field]+cost>dollars(setting_name):
                message='오늘의 개인 AI 이용 금액 한도에 도달했습니다.' if field=='user_day' else 'AI 분석 예산에 도달해 추가 호출을 중단했습니다. 수치 조회는 계속 가능합니다.'
                raise ProviderError(message,'ai_user_limit' if field=='user_day' else 'ai_budget_exceeded')
        db.execute('''INSERT INTO ai_calls(id,request_id,user_id,stage,model,reserved_microusd,price_version)
            VALUES(%s,%s,%s,%s,%s,%s,%s)''',(cid,rid,user,stage,model,cost,PRICE_VERSION))
    return cid


def settle(cid,model,input_tokens,output_tokens=0,cached_tokens=0,response_id=None,resolved_model=None):
    actual=price(model,input_tokens,output_tokens,cached_tokens)
    with store.connection() as db:
        lock(db)
        row=db.execute('SELECT status,reserved_microusd FROM ai_calls WHERE id=%s FOR UPDATE',(cid,)).fetchone()
        if not row or row['status'] not in ('reserved','uncertain'):raise ValueError('Call already settled or missing')
        # Store billed usage even if model output later fails schema/grounding validation.
        db.execute('''UPDATE ai_calls SET status='completed',actual_microusd=%s,input_tokens=%s,output_tokens=%s,
            cached_input_tokens=%s,provider_response_id=%s,resolved_model=%s,finished_at=now() WHERE id=%s''',
            (actual,input_tokens,output_tokens,cached_tokens,response_id,resolved_model or model,cid))
    if actual>row['reserved_microusd']:
        raise ProviderError('실제 사용량이 비용 예약치를 초과해 후속 호출을 중단했습니다. 요금·토큰 계산을 확인해주세요.','ai_cost_bound')


def failed(cid,rejected=False):
    # Timeouts may still be billed. Never silently release an uncertain reservation.
    with store.connection() as db:
        db.execute("UPDATE ai_calls SET status=%s,actual_microusd=%s,finished_at=now() WHERE id=%s AND status='reserved'",
                   ('rejected' if rejected else 'uncertain',0 if rejected else None,cid))


def report(rid):
    with store.connection() as db:
        rows=db.execute('''SELECT stage,model,resolved_model,status,input_tokens,output_tokens,cached_input_tokens,
            actual_microusd,reserved_microusd FROM ai_calls WHERE request_id=%s ORDER BY created_at,id''',(rid,)).fetchall()
    return {'request_id':rid,'estimated_usd':sum(r['actual_microusd'] if r['actual_microusd'] is not None else r['reserved_microusd'] for r in rows)/1e6,
            'price_version':PRICE_VERSION,'calls':rows}


def usage(user):
    with store.connection() as db:
        values=totals(db,user)
        count=db.execute("SELECT count(*) AS n FROM ai_requests WHERE user_id=%s AND created_at>=date_trunc('day',now())",(user,)).fetchone()['n']
        held=db.execute("SELECT COALESCE(sum(reserved_microusd),0) AS n FROM ai_calls WHERE user_id=%s AND status IN ('reserved','uncertain') AND created_at>=date_trunc('day',now())",(user,)).fetchone()['n']
    return {'user_id':user,'daily_used_usd':float(values['user_day'])/1e6,'daily_budget_usd':dollars('AI_USER_DAILY_BUDGET_USD')/1e6,
            'daily_requests':count,'daily_request_limit':int(number('AI_USER_DAILY_REQUESTS')),
            'held_usd':float(held)/1e6,'reset_timezone':'UTC'}
