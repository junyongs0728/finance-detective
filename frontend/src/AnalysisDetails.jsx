import React, { useState } from 'react'
import { ChevronDown, ArrowUpRight, GitBranch, Check, Calculator } from 'lucide-react'

const kinds = { Company: '기업', Filing: '공시', Period: '기간', Observation: '재무 수치', Metric: '지표', Evidence: '원본 근거' }
const relations = { FILED: '공시함', REPORTS: '보고함', FOR_PERIOD: '해당 기간', MEASURES: '해당 지표', SUPPORTED_BY: '수치의 원본 항목', CONTAINS: '포함함' }
const toolNames = { get_financials: '재무 수치 조회', calculate_metrics: '수치 계산', search_filings: '공시 근거 검색', trace_evidence: '근거 관계 조회' }
const displayValue = value => /^-?\d+$/.test(String(value)) ? BigInt(value).toLocaleString('ko-KR') : Number(value).toLocaleString('ko-KR', { maximumFractionDigits: 2 })

export function Calculations({ items }) {
  if (!items?.length) return null
  return <div className="calculation-list">{items.map(item => <section className="calculation-card" key={item.id}>
    <div className="calculation-heading"><Calculator size={16}/><strong>{item.operation === 'difference' ? '차이' : item.operation === 'growth_pct' ? '전년 대비 증가율' : '비율'}</strong><span>코드로 계산한 값</span></div>
    <p>{item.label}</p><strong className="calculation-value">{displayValue(item.value)} <small>{item.unit}</small></strong>
    <p className="table-note">{item.left.metric_label} {displayValue(item.left.value)} {item.left.currency} · {item.right.metric_label} {displayValue(item.right.value)} {item.right.currency}</p>
    <details><summary>계산식과 범위 확인</summary><p>{item.formula}</p><p>왼쪽: {item.left.period_label} · 오른쪽: {item.right.period_label} · {item.scope}</p></details>
  </section>)}</div>
}

export function AnalysisTrace({ steps, trace }) {
  if (!steps?.length) return null
  return <details className="analysis-trace"><summary><span><Check size={15}/>분석 과정 · 도구 {steps.length}회</span><ChevronDown size={14}/></summary>
    <ol>{steps.map(step => <li key={step.step}><strong>{toolNames[step.tool] || step.tool}</strong><span>{step.status === 'ok' ? '완료' : '실행 조건 확인 필요'} · {(step.latency_ms / 1000).toFixed(2)}초</span>{step.error_code && <small>{step.error_code}</small>}
      <details><summary>호출 내용</summary><pre>{JSON.stringify(step.arguments, null, 2)}</pre></details></li>)}</ol>
    {trace && <p className="table-note">분석 기록 {trace.run_id} · 모델 도구 선택 {trace.turns}회{trace.stop_reason ? ' · 실행 한도에 도달해 종료' : ''}</p>}
  </details>
}

export function KnowledgeGraph({ graph, error }) {
  const [active, setActive] = useState(null)
  if (error) return <p className="table-note">근거 관계 탐색: {error.message}</p>
  if (!graph?.nodes?.length) return null
  const selected = graph.nodes.find(n => n.id === active) || graph.nodes.find(n => n.kind === 'Observation') || graph.nodes[0]
  const byId = Object.fromEntries(graph.nodes.map(n => [n.id, n]))
  const edges = graph.edges.filter(e => e.source === selected.id || e.target === selected.id)
  return <details className="knowledge-panel"><summary><span><GitBranch size={16}/>기업과 근거의 관계 탐색</span><ChevronDown size={14}/></summary>
    <p className="table-note">항목을 누르면 연결된 공시·기간·수치·근거를 확인할 수 있습니다. 수치의 원본 항목과 설명 문단을 구분해 표시합니다.</p>
    <div className="knowledge-groups">{Object.entries(kinds).map(([kind, label]) => <section key={kind}><h3>{label}<span>{graph.nodes.filter(n => n.kind === kind).length}</span></h3><div>{graph.nodes.filter(n => n.kind === kind).map(node => <button key={node.id} className={selected.id === node.id ? 'selected' : ''} aria-pressed={selected.id === node.id} onClick={() => setActive(node.id)}>{node.label}{node.properties.evidence_kind && <small>{node.properties.evidence_kind === 'structured_fact' ? '수치 원본' : '설명 문단'}</small>}</button>)}</div></section>)}</div>
    <section className="knowledge-selected" aria-live="polite"><p className="eyebrow">선택한 {kinds[selected.kind]}</p><h3>{selected.label}</h3>
      {selected.properties.value != null && <p className="knowledge-value">{displayValue(selected.properties.value)} {selected.properties.currency} · {selected.properties.scope}</p>}
      {selected.properties.text && <p className="graph-excerpt">{selected.properties.text}</p>}
      {selected.properties.source_url && <a href={selected.properties.source_url} target="_blank" rel="noreferrer">원문 확인 <ArrowUpRight size={13}/></a>}
      <ul className="relation-list">{edges.map(e => <li key={`${e.source}-${e.type}-${e.target}`}><button onClick={() => setActive(e.source)}>{byId[e.source].label}</button><span>→ {relations[e.type]} →</span><button onClick={() => setActive(e.target)}>{byId[e.target].label}</button></li>)}</ul>
    </section><p className="table-note">실제 관계 저장소 조회 · 저장된 원본과 노드·관계 일치 확인</p>
  </details>
}
