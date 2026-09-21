"""Reject invented citation IDs and quotes. This is NOT semantic entailment verification."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from finance_detective.providers.common import ProviderError

class Citation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    evidence_id:str
    span_id:str=Field(min_length=1,max_length=80)

class Claim(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text:str=Field(min_length=1,max_length=600)
    citations:list[Citation]=Field(min_length=1,max_length=3)

class GroundedAnswer(BaseModel):
    model_config=ConfigDict(extra='forbid')
    status:Literal['answered','insufficient_evidence']
    claims:list[Claim]=Field(max_length=3)
    limitations:str=Field(max_length=1600)


def normalize(text):return ' '.join(text.split())


def source_spans(chunk):
    # The model selects immutable source slices; Python copies the quote verbatim.
    return [{'id':f"{chunk['id']}@{i}",'text':chunk['text'][offset:offset+400]}
            for i,offset in enumerate(range(0,len(chunk['text']),320),1)
            if len(chunk['text'][offset:offset+400].strip())>=12]


def validate_answer(raw,evidence):
    try:answer=GroundedAnswer.model_validate(raw)
    except ValidationError:raise ProviderError('AI 응답 구조를 검증하지 못해 답변을 보류했습니다.','citation_validation_failed') from None
    if (answer.status=='answered')!=bool(answer.claims):
        raise ProviderError('AI 답변 상태와 근거가 일치하지 않습니다.','citation_validation_failed')
    candidates={c['id']:c for c in evidence}
    hydrated=answer.model_dump()
    for claim in hydrated['claims']:
        if re.search(r'https?://|\[[^\]]*\]\(',claim['text']):
            raise ProviderError('검증되지 않은 링크가 포함되어 답변을 보류했습니다.','citation_validation_failed')
        for cite in claim['citations']:
            chunk=candidates.get(cite['evidence_id'])
            spans={s['id']:s['text'] for s in source_spans(chunk)} if chunk else {}
            if cite['span_id'] not in spans:
                raise ProviderError('공시에 없는 인용 위치여서 답변을 보류했습니다.','citation_validation_failed')
            cite['quote']=spans[cite['span_id']]
            assert cite['quote'] in chunk['text']
    return hydrated
