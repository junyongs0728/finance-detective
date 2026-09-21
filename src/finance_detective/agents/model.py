"""LangChain model adapter with the same atomic budget guarantees as direct RAG calls."""
import json
from openai import APIError
from langchain_openai import ChatOpenAI
from langchain_core.messages import messages_to_dict
from langchain_core.utils.function_calling import convert_to_openai_tool
from langsmith import tracing_context
from finance_detective.providers.common import ProviderError, setting
from finance_detective.rag import billing, llm


def model_name():
    return setting('OPENAI_AGENT_MODEL') or llm.model()


def invoke(messages,tools):
    secret=setting('OPENAI_API_KEY')
    if not secret:raise ProviderError('AI 분석에는 OpenAI 설정이 필요합니다.','ai_setup_required')
    selected=model_name(); cap=750
    model=ChatOpenAI(model=selected,api_key=secret,max_retries=0,timeout=30,
                     max_tokens=cap,use_responses_api=True,store=False,temperature=0)
    bound_model=model.bind_tools(tools,strict=True,parallel_tool_calls=False)
    payload={'messages':messages_to_dict(messages),'tools':[convert_to_openai_tool(t,strict=True) for t in tools]}
    bound=len(json.dumps(payload,ensure_ascii=False).encode())+2048
    if bound>int(billing.number('AI_MAX_INPUT_TOKENS')):
        raise ProviderError('Agent 입력이 길이 제한에 도달했습니다.','ai_input_limit')
    cid=billing.reserve('agent_plan',selected,bound,cap)
    try:
        # Keep traces in our SQL audit store; do not export to an ambient LangSmith account.
        with tracing_context(enabled=False):
            response=bound_model.invoke(messages,config={'callbacks':[]})
        usage=response.usage_metadata or {}
        inp=usage.get('input_tokens'); out=usage.get('output_tokens')
        if type(inp) is not int or type(out) is not int or min(inp,out)<0:
            raise ProviderError('Agent 사용량을 확인하지 못해 추가 호출을 중단했습니다.','ai_usage_unknown')
        cached=usage.get('input_token_details',{}).get('cache_read',0) or 0
        metadata=response.response_metadata
        billing.settle(cid,selected,inp,out,cached,response.id,metadata.get('model_name',selected))
        if metadata.get('status')=='incomplete' or metadata.get('finish_reason')=='length':
            raise ProviderError('도구 선택 응답이 잘려 실행하지 않았습니다.','ai_incomplete')
        return response
    except APIError as exc:
        billing.failed(cid,rejected=getattr(exc,'status_code',None) in (400,401,403,404,422,429))
        raise llm.api_failure(exc) from None
    except BaseException:
        billing.failed(cid)
        raise
