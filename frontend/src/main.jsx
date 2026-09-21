import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ArrowUp, ArrowUpRight, Plus, Search, PanelLeftClose, PanelLeftOpen, FileText, Check, ChevronDown, RotateCcw, Square, TrendingUp, ChartNoAxesCombined, BookOpen, CircleHelp } from 'lucide-react'
import './styles.css'
import { Calculations, AnalysisTrace, KnowledgeGraph } from './AnalysisDetails'

const prompts = [
  { icon: TrendingUp, label: '실적 한눈에 보기', description: '연간 매출과 영업이익 알려줘' },
  { icon: ChartNoAxesCombined, label: '계산과 근거 함께 보기', description: '2025년 영업현금흐름과 영업이익 차이를 계산하고 근거 경로를 보여줘' },
  { icon: BookOpen, label: 'AI에게 공시 물어보기', description: '주요 사업을 공시 근거로 설명해줘' },
]
const INITIAL_COMPANY = { id: 'SEC:CPNG', name: 'Coupang, Inc.', ticker: 'CPNG', provider: 'SEC' }
const fmt = (value, currency) => value == null ? '—' : (value / (currency === 'KRW' ? 1e8 : 1e6)).toLocaleString('ko-KR', { maximumFractionDigits: 2 })
const pct = (value) => value == null ? '—' : `${value.toFixed(2)}%`

function Result({ result }) {
  return <>
    <div className="steps">{result.steps.map(step => <span key={step}><Check size={12}/>{step}</span>)}</div>
    <p className="answer-text">{result.text}</p>
    {result.billing && <p className="table-note">{result.billing.cached ? '저장된 분석 재사용 · 이번 AI 비용 $0' : `이번 AI 처리 예상 비용 $${result.billing.estimated_usd.toFixed(5)}`}</p>}
    <Calculations items={result.calculations}/>
    <AnalysisTrace steps={result.agent_steps} trace={result.agent_trace}/>
    {!!result.rows.length && <div className="result-card">
      <div className="table-title"><strong>{result.company_name} · 연간 실적</strong><span>{result.currency === 'KRW' ? '억 원' : `백만 ${result.currency}`} / %</span></div>
      <div className="table-scroll"><table><thead><tr><th>{result.period_basis || '연도'}</th><th>매출</th><th>영업이익</th><th>영업현금흐름</th><th>매출 증가율</th><th>영업이익률</th></tr></thead>
        <tbody>{result.rows.map(row => <tr key={row.period_label || row.year}><th>{row.period_label || row.year}</th><td>{fmt(row.revenue, result.currency)}</td><td>{fmt(row.operating_income, result.currency)}</td><td>{fmt(row.operating_cash_flow, result.currency)}</td><td>{pct(row.revenue_growth_pct)}</td><td>{pct(row.operating_margin_pct)}</td></tr>)}</tbody></table></div>
      <p className="table-note">{result.scope} · —는 비교 자료 부족 또는 계산 불가</p>
    </div>}
    {!!result.warnings?.length && <details className="data-warnings"><summary>자료 확인 사항 {result.warnings.length}건</summary>{result.warnings.map((warning, i) => <p key={i}>{warning}</p>)}</details>}
    {result.fetched_at && <p className="table-note">수집 시각: {new Date(result.fetched_at).toLocaleString('ko-KR')} · 수집 결과는 최대 24시간 재사용합니다.</p>}
    {!!result.evidence.length && <div className="evidence-list"><p className="eyebrow">답변에 사용한 공시 근거</p>{result.evidence.map(item => <details key={item.id} className="evidence"><summary><span><FileText size={15}/>{item.citation_number ? `[${item.citation_number}] ` : ''}{item.document_title || '공시 원문'}<small>{item.page ? `PDF ${item.page}쪽` : `문단 ${item.ordinal}`}</small></span><ChevronDown size={14}/></summary>{item.section && <strong className="evidence-section">{item.section}</strong>}{item.quotes?.map((quote, i) => <blockquote key={i}>{quote}</blockquote>)}<p>{item.text}</p><a href={item.source_url} target="_blank" rel="noreferrer">공시 원문 열기 <ArrowUpRight size={13}/></a></details>)}<small className="muted">인용문이 저장된 원문에 있는지 확인했습니다. 해당 문단이 설명을 충분히 뒷받침하는지는 함께 확인해주세요.</small></div>}
    <KnowledgeGraph graph={result.knowledge_graph} error={result.graph_error}/>
    {!!result.sources.length && <div className="sources">{result.sources.map(source => <a href={source.url} key={source.url} target="_blank" rel="noreferrer"><FileText size={13}/>{source.label}<ArrowUpRight size={13}/></a>)}</div>}
  </>
}

function CompanyPicker({ selected, onSelect, onClose }) {
  const dialog = useRef(null)
  const searchInput = useRef(null)
  const [query, setQuery] = useState('')
  const [market, setMarket] = useState('ALL')
  const [state, setState] = useState({ loading: true, results: [], error: '' })
  const [retry, setRetry] = useState(0)
  useEffect(() => { dialog.current.showModal(); searchInput.current?.focus() }, [])
  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setState({ loading: true, results: [], error: '' })
    const timer = setTimeout(async () => {
      try {
        const response = await fetch('/api/companies?' + new URLSearchParams({ q: query, market }), { signal: controller.signal })
        const data = await response.json()
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '기업 검색에 실패했습니다.')
        if (active) setState({ ...data, loading: false, error: '' })
      } catch (error) {
        if (active) setState({ results: [], loading: false, error: error.message })
      }
    }, 250)
    return () => { active = false; clearTimeout(timer); controller.abort() }
  }, [query, market, retry])
  return <dialog className="company-dialog" ref={dialog} aria-labelledby="company-search-title" onCancel={onClose}>
    <div className="picker-heading"><div><p className="eyebrow">FIND A COMPANY</p><h2 id="company-search-title">어떤 기업을 살펴볼까요?</h2></div><button className="picker-close" onClick={onClose} aria-label="기업 검색 닫기">닫기</button></div>
    <label className="company-search"><Search size={18}/><input ref={searchInput} autoFocus aria-label="기업명 또는 종목코드" placeholder="삼성전자, 애플, AAPL, 005930" value={query} maxLength={100} onChange={e => setQuery(e.target.value)}/></label>
    <div className="market-tabs">{[['ALL', '전체'], ['DART', '한국'], ['SEC', '미국']].map(([value, label]) => <button key={value} aria-pressed={market === value} onClick={() => setMarket(value)}>{label}</button>)}</div>
    <div className="company-results" aria-live="polite">
      {state.loading ? <p className="picker-message" role="status">기업을 찾고 있습니다…</p> : state.error ? <div className="error-box" role="alert"><p>{state.error}</p><button onClick={() => setRetry(v => v + 1)}>다시 검색</button></div> : !state.results.length ? <p className="picker-message">검색 결과가 없습니다. 기업명이나 종목코드를 확인해주세요.</p> : state.results.map(company => <button className="company-option" key={company.id} onClick={() => onSelect(company)}><span className="market-badge">{company.provider === 'DART' ? 'KR' : 'US'}</span><span><strong>{company.name}</strong><small>{company.ticker} · {company.provider === 'DART' ? 'OpenDART' : 'SEC EDGAR'}</small></span>{company.id === selected.id ? <Check size={17}/> : <ArrowUpRight size={17}/>}</button>)}
    </div>
    {!state.loading && !state.error && <p className="picker-message">{state.total.toLocaleString()}개 검색 결과 · 최대 20개 표시</p>}
    <p className="directory-note">{state.directory_notice || '기업 검색 등재가 재무 데이터 지원을 보장하지는 않습니다.'}</p>
  </dialog>
}

function App() {
  const [selected, setSelected] = useState(INITIAL_COMPANY)
  const [picker, setPicker] = useState(false)
  const [overview, setOverview] = useState(null)
  const [overviewError, setOverviewError] = useState('')
  const [overviewLoading, setOverviewLoading] = useState(true)
  const [overviewRetry, setOverviewRetry] = useState(0)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [engine, setEngine] = useState('auto')
  const [busy, setBusy] = useState(false)
  const [phase, setPhase] = useState('공시 자료를 확인하고 있습니다')
  const [sidebar, setSidebar] = useState(true)
  const [help, setHelp] = useState(false)
  const [account, setAccount] = useState(null)
  const [accountError, setAccountError] = useState('')
  const [accessCode, setAccessCode] = useState('')
  async function refreshUsage() {
    try {
      const response = await fetch('/api/session')
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '사용량을 확인하지 못했습니다.')
      setAccount(data); setAccountError('')
    } catch (error) { setAccountError(error.message) }
  }
  async function connect(event) {
    event.preventDefault()
    try {
      const response = await fetch('/api/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: accessCode }) })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '연결하지 못했습니다.')
      setAccessCode(''); await refreshUsage()
    } catch (error) { setAccountError(error.message) }
  }
  useEffect(() => { refreshUsage() }, [])
  const end = useRef(null)
  const textarea = useRef(null)
  const controller = useRef(null)
  const generation = useRef(0)
  const hasMessages = messages.length > 0
  useEffect(() => { if (hasMessages) end.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, busy])
  useEffect(() => { if (textarea.current) { textarea.current.style.height = 'auto'; textarea.current.style.height = `${Math.min(textarea.current.scrollHeight, 160)}px` } }, [input])
  useEffect(() => () => controller.current?.abort(), [])

  useEffect(() => {
    const local = new AbortController()
    let active = true
    setOverview(null); setOverviewError(''); setOverviewLoading(true)
    const timeout = setTimeout(() => local.abort(), 70000)
    async function load() {
      try {
        const response = await fetch('/api/company-data/' + encodeURIComponent(selected.id), { signal: local.signal })
        const data = await response.json()
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '재무정보를 조회하지 못했습니다.')
        if (active) setOverview(data)
      } catch (error) {
        if (active) setOverviewError(local.signal.aborted ? '조회 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.' : error.message)
      } finally {
        clearTimeout(timeout)
        if (active) setOverviewLoading(false)
      }
    }
    load()
    return () => { active = false; local.abort(); clearTimeout(timeout) }
  }, [selected.id, overviewRetry])

  function chooseCompany(company) {
    reset(); setOverview(null); setOverviewError(''); setOverviewLoading(true)
    setSelected(company); setOverviewRetry(v => v + 1); setPicker(false)
  }

  function reset() {
    generation.current++; controller.current?.abort(); controller.current = null
    setBusy(false); setMessages([]); setInput(''); textarea.current?.focus()
  }
  function stop() { controller.current?.abort() }
  async function send(question = input) {
    const message = question.trim()
    if (!message || controller.current || message.length > 2000) return
    const local = new AbortController(); controller.current = local
    const run = ++generation.current
    setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'user', text: message }])
    setInput(''); setBusy(true); setPhase('공시 자료를 확인하고 있습니다')
    const timeout = setTimeout(() => local.abort('timeout'), 240000)
    try {
      const ask = async () => {
        const response = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message, company_id: selected.id, engine }), signal: local.signal })
        const data = await response.json()
        if (!response.ok) { if (response.status === 401 || response.status === 429) setHelp(true); throw new Error(typeof data.detail === 'string' ? data.detail : '요청을 처리하지 못했습니다. 다시 시도해주세요.') }
        return data
      }
      let data = await ask()
      if (data.status === 'preparing') {
        let progress = data.document_status
        while (progress.status !== 'ready') {
          if (run !== generation.current) return
          if (progress.status === 'failed') throw new Error(progress.error || '공시 준비에 실패했습니다.')
          setPhase(progress.chunk_count ? `공시 검색 준비 중 · ${progress.embedded_count}/${progress.chunk_count}개 문단` : '이 공시를 처음 준비하고 있습니다. 잠시 기다려주세요')
          await new Promise((resolve, reject) => {
            if (local.signal.aborted) return reject(new Error('aborted'))
            const cancel = () => { clearTimeout(timer); local.signal.removeEventListener('abort', cancel); reject(new Error('aborted')) }
            const timer = setTimeout(() => { local.signal.removeEventListener('abort', cancel); resolve() }, 1800)
            local.signal.addEventListener('abort', cancel, { once: true })
          })
          const response = await fetch('/api/rag/status/' + data.document_status.id, { signal: local.signal })
          progress = await response.json()
          if (!response.ok) throw new Error('공시 준비 상태를 확인하지 못했습니다.')
        }
        if (run !== generation.current) return
        setPhase('필요한 자료를 조회하고 계산·근거를 확인하고 있습니다')
        data = await ask()
        if (data.status === 'preparing') throw new Error('공시가 변경되었습니다. 다시 질문해주세요.')
      }
      if (run === generation.current) setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'assistant', result: data }])
    } catch (error) {
      if (run === generation.current) setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'error', text: local.signal.aborted ? (local.signal.reason === 'timeout' ? '응답 시간이 초과되었습니다.' : '요청을 중지했습니다.') : (error.message === 'Failed to fetch' ? '서버에 연결하지 못했습니다. 연결 상태를 확인하고 다시 시도해주세요.' : error.message), question: message }])
    } finally {
      clearTimeout(timeout)
      refreshUsage()
      if (run === generation.current) { controller.current = null; setBusy(false); textarea.current?.focus() }
    }
  }
  return <div className={`app ${sidebar ? '' : 'collapsed'}`}>
    <aside className="sidebar">
      <a className="brand" href="/" onClick={event => { event.preventDefault(); reset() }}><span className="brand-mark"><Search size={22}/></span><span>재무탐정<small>FINANCE DETECTIVE</small></span></a>
      <button className="new-chat" onClick={reset}><Plus size={17}/>새 대화<span>↗</span></button>
      <p className="nav-label">WORKSPACE</p>
      <div className="nav-active"><Search size={17}/>공시 탐색<span className="live-dot"/></div>
      <div className="source-panel"><p className="nav-label">현재 분석 기업</p><div className="company-logo">{selected.provider === 'DART' ? 'KR' : 'US'}</div><strong>{overview?.name || selected.name}</strong><span className="ticker">{selected.provider} · {selected.ticker}</span><button className="change-company" onClick={() => setPicker(true)}><Search size={14}/>기업 변경</button><div className="source-meta"><span>보고서</span><b>{overview?.filing.form || '조회 중'}</b><span>기준 기간</span><b>{overview?.filing.end || '—'}</b><span>통화</span><b>{overview?.currency || '—'}</b></div>{overview && <a href={overview.source_url} target="_blank" rel="noreferrer">공시 원문 보기 <ArrowUpRight size={14}/></a>}</div>
      <div className="sidebar-bottom"><span className="avatar">J</span><div>나의 리서치 공간<small>로컬 프로젝트 · v0.3</small></div></div>
    </aside>
    <main>
      <header><div className="header-left"><button className="icon-button" aria-label="사이드바 열기 또는 닫기" onClick={() => setSidebar(!sidebar)}>{sidebar ? <PanelLeftClose size={19}/> : <PanelLeftOpen size={19}/>}</button><span>공시 탐색</span><span className="header-separator">/</span><button className="header-company company-trigger" onClick={() => setPicker(true)}><Search size={14}/><span>{selected.name}</span><ChevronDown size={13}/></button><button className="icon-button header-new" aria-label="새 대화 시작" onClick={reset}><Plus size={18}/></button></div><button className="status-pill" onClick={() => setHelp(!help)}><span className="live-dot"/>공시 근거 AI<CircleHelp size={13}/></button></header>
      {help && <div className="help-banner">자동 모드의 단순 수치 조회는 AI 비용 없이 처리합니다. 설명·차이 계산·근거 경로 질문은 AI가 필요한 도구를 선택해 분석합니다. 첫 AI 분석은 공시 준비에 시간이 걸립니다. 질문마다 기간을 명시해주세요. 이전 대화 기억은 아직 지원하지 않습니다.</div>}
      {help && <div className="usage-panel">
        {account?.authenticated && account.usage ? <><strong>오늘의 AI 이용</strong><span>{account.usage.daily_requests} / {account.usage.daily_request_limit}회 · ${account.usage.daily_used_usd.toFixed(4)} / ${account.usage.daily_budget_usd.toFixed(2)}</span><small>UTC 자정에 초기화 · 공시 최초 준비도 1회 사용 · 저장된 답변 재사용은 차감하지 않습니다.</small>{account.usage.held_usd > 0 && <small>처리 중이거나 비용 확인이 필요한 예약금 ${account.usage.held_usd.toFixed(4)} 포함</small>}{account.mode === 'token' && <button onClick={async () => { await fetch('/api/session', { method: 'DELETE' }); refreshUsage() }}>연결 해제</button>}</> : <form onSubmit={connect}><label htmlFor="access-code">AI 분석 이용 코드</label><input id="access-code" type="password" autoComplete="off" value={accessCode} onChange={event => setAccessCode(event.target.value)} required minLength={20} maxLength={200}/><button>연결</button><small>기업 검색과 수치 조회는 코드 없이 이용할 수 있습니다.</small></form>}
        {accountError && <p role="alert">{accountError}</p>}
      </div>}
      <div className={`conversation ${hasMessages ? 'started' : ''}`}>
        {!hasMessages ? <section className="welcome company-welcome"><p className="eyebrow">FOLLOW THE NUMBERS. FIND THE EVIDENCE.</p><h1>궁금한 기업의<br/><span>숫자부터 살펴보세요.</span></h1><p className="welcome-copy">미국·한국 기업의 연간 실적을 출처와 함께 확인하세요.</p><button className="welcome-search" onClick={() => setPicker(true)}><Search size={19}/><span>기업명 또는 종목코드로 검색</span><span>↗</span></button>
          <div className="company-overview" aria-live="polite">{overviewLoading ? <p className="picker-message" role="status">{selected.name} 공시를 조회하고 있습니다…</p> : overviewError ? <div className="error-box" role="alert"><strong>{selected.name}</strong><p>{overviewError}</p><button onClick={() => setOverviewRetry(v => v + 1)}>다시 조회</button></div> : overview && <Result result={{ ...overview, company_name: overview.name, steps: [], text: '', evidence: [], sources: [{ label: overview.name + ' · ' + overview.filing.form, url: overview.source_url }] }}/>}</div>
          <div className="prompt-grid">{prompts.map(({icon: Icon,label,description}) => <button key={label} onClick={() => send(description)}><Icon size={20}/><strong>{label}</strong><span>{description}</span><ArrowUpRight className="prompt-arrow" size={16}/></button>)}</div><div className="scope-note"><FileText size={13}/>선택한 기업 기준 · 연간 재무 수치 · 기업별 공시 출처</div></section>
        : <div className="messages">{messages.map(message => <article key={message.id} className={`message ${message.role}`}>
          {message.role === 'user' ? <div className="user-bubble">{message.text}</div> : <><div className="assistant-label"><span className="mini-mark"><Search size={14}/></span>재무탐정 <small>{message.role === 'error' ? '안내' : message.result.status === 'unsupported' ? '지원 범위 안내' : '자료 조회 결과'}</small></div>{message.role === 'error' ? <div className="error-box" role="alert"><p>{message.text}</p><button disabled={busy} onClick={() => send(message.question)}><RotateCcw size={13}/>다시 시도</button></div> : <Result result={message.result}/>}</>}
        </article>)}{busy && <div className="thinking" role="status"><span className="mini-mark"><Search size={14}/></span><span>{phase}<span className="dots">…</span></span></div>}<div ref={end}/></div>}
      </div>
      <div className="composer-area"><form className="composer" onSubmit={e => { e.preventDefault(); send() }}><label className="sr-only" htmlFor="question">재무탐정에게 질문하기</label><textarea id="question" ref={textarea} value={input} maxLength={2000} rows={1} onChange={e => setInput(e.target.value)} placeholder={`${selected.name}의 재무제표에 대해 질문해보세요`} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) { e.preventDefault(); send() } }}/><div className="composer-bottom"><span className="scope-chip"><FileText size={13}/>{selected.ticker} · {selected.provider}</span><label className="engine-select"><span className="sr-only">분석 방식</span><select value={engine} onChange={event => setEngine(event.target.value)} disabled={busy}><option value="auto">자동</option><option value="agent">AI 심층 분석</option><option value="rag">공시 검색 답변</option></select></label><span className="input-hint">Shift + Enter 줄바꿈</span>{busy ? <button type="button" className="send" aria-label="요청 중지" onClick={stop}><Square size={15}/></button> : <button className="send" aria-label="질문 보내기" disabled={!input.trim()}><ArrowUp size={20}/></button>}</div></form><p className="disclaimer">AI 답변은 인용 원문과 함께 확인하세요. 인용문 대조가 해석의 정확성을 보장하지는 않습니다. 질문은 각각 독립적으로 처리합니다.</p></div>
    </main>
    {picker && <CompanyPicker selected={selected} onSelect={chooseCompany} onClose={() => setPicker(false)}/>}
  </div>
}
createRoot(document.getElementById('root')).render(<React.StrictMode><App/></React.StrictMode>)
