"""Run-scoped, typed tools. The model chooses actions, never arbitrary numbers/code."""
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from langchain.tools import tool
from finance_detective.providers.common import ProviderError
from finance_detective.providers.registry import mentioned_companies
from finance_detective.rag import search
from finance_detective.knowledge import ontology, graph

Metric = Literal['revenue','operating_income','operating_cash_flow']


class StrictInput(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)


class FinancialQuery(StrictInput):
    years:list[int]=Field(description='조회할 회계연도. 빈 배열이면 요청 범위의 모든 연도.',max_length=3)
    metrics:list[Metric]=Field(description='조회할 지표. 빈 배열이면 세 지표 모두.',max_length=3)


class Calculation(StrictInput):
    operation:Literal['difference','ratio_pct','growth_pct']=Field(description='차이=왼쪽-오른쪽, 비율=왼쪽/오른쪽*100, 증가율=(왼쪽-오른쪽)/오른쪽*100. 증가율은 왼쪽이 다음 연도.')
    left_id:str=Field(description='get_financials에서 반환된 왼쪽 관측값 ID',max_length=80)
    right_id:str=Field(description='get_financials에서 반환된 오른쪽 관측값 ID',max_length=80)


class SearchQuery(StrictInput):
    query:str=Field(description='선택 기업·공시 안에서 검색할 구체적 한국어 또는 영어 질의.',min_length=2,max_length=500)


class TraceQuery(StrictInput):
    observation_ids:list[str]=Field(description='get_financials에서 반환된 근거 탐색 대상 ID.',min_length=1,max_length=6)


def calculate(operation,left,right):
    if left['company_id']!=right['company_id'] or left['accession']!=right['accession']:
        raise ProviderError('다른 기업이나 공시의 수치는 계산할 수 없습니다.','calculation_scope_invalid')
    if left['unit']!=right['unit'] or left['scope']!=right['scope']:
        raise ProviderError('통화 또는 연결 기준이 다른 수치는 계산할 수 없습니다.','calculation_scope_invalid')
    if operation=='growth_pct':
        if left['metric']!=right['metric'] or left['year']!=right['year']+1:
            raise ProviderError('증가율은 같은 지표의 연속된 두 연도로 계산해주세요.','calculation_period_invalid')
    elif any(left.get(k)!=right.get(k) for k in ('period_label','start','end')):
        raise ProviderError('차이와 비율 계산에는 같은 기간의 수치가 필요합니다.','calculation_period_invalid')
    a,b=Decimal(left['value']),Decimal(right['value'])
    if operation=='difference': value=a-b; unit=left['unit']; expression='left - right'
    else:
        if b<=0:raise ProviderError('분모가 0 이하인 비율은 계산하지 않습니다.','calculation_denominator_invalid')
        value=((a-b) if operation=='growth_pct' else a)/b*100
        value=value.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        unit='%'; expression='(left - right) / right * 100' if operation=='growth_pct' else 'left / right * 100'
    return {'id':ontology.identity('calculation',operation,left['id'],right['id']),
            'operation':operation,'value':str(value),'unit':unit,'formula':expression,
            'left':left,'right':right,'scope':left['scope'],
            'label':f"{left['period_label']} {left['metric_label']} {'−' if operation=='difference' else '÷'} {right['period_label']} {right['metric_label']}"}


@dataclass
class ToolContext:
    data:dict
    document:dict
    years:set[int]
    facts:dict=field(init=False)
    seen:set[str]=field(default_factory=set)
    calculations:list=field(default_factory=list)
    evidence:dict=field(default_factory=dict)
    retrieval:list=field(default_factory=list)
    graph_paths:list=field(default_factory=list)
    graph_result:dict|None=None
    tools:list=field(init=False)

    def __post_init__(self):
        self.facts={r['id']:r for r in ontology.observations(self.data) if r['year'] in self.years}
        self.tools=self.build_tools()

    def snapshot(self):
        return ontology.build_snapshot(self.data,self.document,list(self.evidence.values()))

    def prepare_graph(self):
        snapshot=self.snapshot(); graph.project(snapshot)
        self.graph_result=graph.read(snapshot['id'])
        return snapshot

    def build_tools(self):
        @tool(args_schema=FinancialQuery)
        def get_financials(years:list[int],metrics:list[str])->dict:
            """선택 기업·공시의 검증된 연간 재무 관측값과 ID를 조회한다. 계산·수치 근거 탐색 전에 실행한다."""
            if set(years)-self.years:
                raise ProviderError('요청한 기간 범위를 벗어난 조회입니다.','tool_scope_invalid')
            rows=[r for r in self.facts.values() if (not years or r['year'] in years) and (not metrics or r['metric'] in metrics)]
            self.seen.update(r['id'] for r in rows)
            return {'observations':rows,'company_id':self.data['company_id']}

        @tool(args_schema=Calculation)
        def calculate_metrics(operation:str,left_id:str,right_id:str)->dict:
            """실제로 조회된 두 관측값 ID로만 차이·비율·증가율을 계산한다. 숫자 입력이나 임의 코드 실행은 없다."""
            if {left_id,right_id}-self.seen:
                raise ProviderError('먼저 get_financials로 두 수치를 조회해주세요.','unobserved_fact')
            result=calculate(operation,self.facts[left_id],self.facts[right_id])
            if result['id'] not in {r['id'] for r in self.calculations}:self.calculations.append(result)
            return result

        @tool(args_schema=SearchQuery)
        def search_filings(query:str)->dict:
            """선택 기업·공시의 서술문을 하이브리드 검색한다. 원인·사업·위험 설명에는 반드시 사용한다."""
            if mentioned_companies(query)-{self.data['company_id']}:
                raise ProviderError('선택 기업 외의 검색은 허용하지 않습니다.','tool_scope_invalid')
            if len(self.retrieval)>=2:
                raise ProviderError('한 질문의 근거 검색은 2회까지 가능합니다.','tool_search_limit')
            items,meta=search.retrieve(self.document['id'],query,limit=6)
            self.retrieval.append(meta)
            for item in items:self.evidence[item['id']]=item
            # Return search observations, not generated conclusions or hidden reasoning.
            return {'evidence':[{'id':e['id'],'section':e['section'],'text':e['text']} for e in items],
                    'notice':'검색 결과는 원인이라는 결론이 아니다. 최종 생성 단계에서 원문 근거를 검토한다.'}

        @tool(args_schema=TraceQuery)
        def trace_evidence(observation_ids:list[str])->dict:
            """조회된 수치에서 공시·기간·원본 재무 항목으로 가는 실제 Neo4j 경로를 조회한다."""
            if set(observation_ids)-self.seen:
                raise ProviderError('먼저 해당 수치를 조회해주세요.','unobserved_fact')
            snapshot=self.prepare_graph()
            paths=graph.trace(snapshot['id'],observation_ids)
            self.graph_paths=paths
            return {'paths':paths,'snapshot_id':snapshot['id'],'engine':'neo4j',
                    'notice':'structured_fact는 숫자의 원본 항목이다. 서술문이 숫자의 변동 원인을 설명한다는 뜻은 아니다.'}
        return [get_financials,calculate_metrics,search_filings,trace_evidence]
