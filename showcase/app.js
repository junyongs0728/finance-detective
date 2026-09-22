'use strict';

// Archived runs, not a live model. Numbers retain filing, period, currency and scope.
const filings = {
  coupang: { name: '쿠팡', english: 'COUPANG', ticker: 'CPNG', end: '2025.12.31', period: '2025.01.01–12.31', url: 'https://www.sec.gov/Archives/edgar/data/1834584/000183458426000024/cpng-20251231.htm' },
  apple: { name: '애플', english: 'APPLE', ticker: 'AAPL', end: '2025.09.27', period: '2025.09.27 종료 회계연도', url: 'https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm' },
};
const cashFlow = 1773000000n;
const operatingIncome = 473000000n;
const difference = cashFlow - operatingIncome;
const millions = n => (n / 1000000n).toLocaleString('ko-KR');
const cases = {
  cash: {
    company: 'coupang', kind: '수치 계산', elapsed: '6.7초', cost: '$0.002415',
    question: '2025년 영업현금흐름에서 영업이익을 뺀 차이를 계산하고 두 수치의 원본 근거 경로를 보여줘',
    answer: `<p class="answer-lead">쿠팡의 2025년 영업현금흐름은 영업이익보다 <strong>13억 달러</strong> 많습니다.</p><div class="calculation-card"><div class="calculation-top"><p>영업현금흐름 − 영업이익</p><div class="calculation-number">${millions(difference)}<small>백만 USD</small></div></div><div class="calculation-inputs"><div><span>영업현금흐름</span><strong>${millions(cashFlow)}</strong><small>백만 USD</small></div><div><span>영업이익</span><strong>${millions(operatingIncome)}</strong><small>백만 USD</small></div></div><p class="calculation-equation">${millions(cashFlow)} − ${millions(operatingIncome)} = ${millions(difference)} · 동일 기업·기간·통화</p></div><p class="answer-note">두 수치의 단순 차이입니다. 차이가 발생한 원인을 설명하려면 관련 공시를 추가로 살펴봐야 합니다.</p>`,
    evidence: `<div class="evidence-chunk"><span>계산에 사용한 항목</span><h3>연결 현금흐름표·손익계산서</h3><p>Net cash provided by operating activities<br>Operating income</p><details><summary>원본 근거 경로 보기</summary><div class="evidence-path"><span>기업 · Coupang, Inc.</span><span>공시 · 2025년 Form 10-K</span><span>기간 · 2025.01.01–12.31 / USD</span><span>관측값 · 영업현금흐름 1,773백만</span><span>관측값 · 영업이익 473백만</span></div></details></div>`,
    steps: [['연간 재무 수치 조회', 'get_financials'], ['기간·통화 검증 후 차이 계산', 'calculate_metrics'], ['두 수치의 원본 근거 추적', 'trace_evidence']],
    note: '실제 실행에서는 관측값 ID로 조회한 수치를 Python으로 계산했습니다. 이 화면은 같은 저장 값으로 계산 결과를 표시합니다.',
  },
  supply: {
    company: 'apple', kind: '공시 기반 설명', elapsed: '9.0초', cost: '$0.007057',
    question: '애플이 공시한 공급망 리스크를 설명해줘',
    answer: `<p class="answer-lead">애플은 일부 부품의 <strong>단일 공급처 의존과 공급 확보의 불확실성</strong>을 위험 요인으로 설명합니다.<span class="citation-number">[2]</span></p><p class="answer-note">저장된 답변의 두 번째 주장을 아래에 요약했습니다.</p><ul class="answer-detail"><li><strong>특정 공급처에 대한 의존</strong>신제품에 사용하는 맞춤형 부품은 하나의 공급처에서만 구할 수 있는 경우가 있습니다.</li><li><strong>초기 생산능력의 제약</strong>새 기술을 사용하는 부품은 공급업체의 수율과 생산능력이 충분해질 때까지 공급이 제한될 수 있습니다.</li><li><strong>계약 갱신과 대체 공급처 확보</strong>기존 공급 계약을 갱신하거나 다른 공급처에서 충분한 물량을 제때 확보하지 못할 위험이 있습니다.</li></ul><p class="answer-note">공시에 기재된 위험 요인입니다. 해당 위험이 실제로 발생했다는 뜻은 아닙니다.</p>`,
    evidence: `<div class="evidence-chunk"><span>[2] 답변에 사용한 공시의 일부</span><h3>Item 1A. Risk Factors</h3><p>검색 문단 54 · 원문 인용</p><blockquote lang="en">“Additionally, the Company’s new products often utilize custom components available from only one source.”</blockquote><p>생산능력 제약과 공급 계약 위험은 연결된 공시의 이어지는 문장에서 확인할 수 있습니다.</p></div>`,
    steps: [['선택 공시에서 관련 문단 검색', 'search_filings'], ['검색 근거에 연결된 주장 생성', 'RAG'], ['인용문 대조와 별도 근거 검토', 'citation check / review']],
    note: '실제 실행의 인용은 총 2개이며, 여기에는 그중 하나와 관련 답변을 발췌했습니다. 원문 문자열 일치가 답변의 의미 정확성을 보장하지는 않습니다.',
  },
  missing: {
    company: 'coupang', kind: '근거 부족 처리', elapsed: '5.1초', cost: '$0.002716',
    question: '쿠팡의 2025년 달 기지 운영 사업을 공시 근거로 설명해줘',
    answer: `<div class="status-card"><span class="status-label">근거 부족 · insufficient_evidence</span><h2>답변을 뒷받침할 근거가 부족합니다.</h2><p>검색된 공시 문단만으로는 질문에 답할 수 없어 설명을 보류했습니다.</p></div><p class="answer-note">검색한 범위에서 충분한 근거를 찾지 못했다는 뜻입니다. 공시 전체에 해당 정보가 없음을 증명하는 결과는 아닙니다.</p>`,
    evidence: `<div class="evidence-chunk"><span>질문에 대한 인용</span><h3>충분한 근거를 확보하지 못했습니다.</h3><p>검색은 수행했지만 답변을 뒷받침하는 인용을 제시하지 않았습니다.</p></div>`,
    steps: [['선택 공시에서 관련 문단 검색', 'search_filings'], ['검색 근거의 충분성 확인', 'RAG'], ['추가 설명 없이 답변 보류', 'insufficient_evidence']],
    note: '확인한 근거 범위 안에서 답하도록 처리한 사례입니다. 한 사례의 성공이 모든 질문에서의 안전한 동작을 보장하지는 않습니다.',
  },
};

let activeCase = 'cash';
const $ = id => document.getElementById(id);
function renderCase(key) {
  activeCase = Object.hasOwn(cases, key) ? key : 'cash';
  const c = cases[activeCase];
  const company = filings[c.company];
  $('company-kicker').textContent = `${company.english} · ${company.ticker}`;
  $('analysis-title').textContent = `${company.name}의 공시를 살펴봅니다.`;
  $('company-description').textContent = `${company.period} · 연간 공시의 수치와 설명을 확인합니다.`;
  $('heading-source').href = company.url;
  $('question-text').textContent = c.question;
  $('answer-kind').textContent = c.kind;
  $('answer-content').innerHTML = c.answer;
  $('run-meta').textContent = `당시 실행 ${c.elapsed} · 예상 API 비용 ${c.cost}`;
  $('evidence-content').innerHTML = `<p class="filing-label">SEC EDGAR</p><strong class="filing-title">${company.name} · 2025 Form 10-K</strong><dl class="filing-meta"><dt>회계연도 종료</dt><dd>${company.end}</dd><dt>공시 범위</dt><dd>연결 · 연간</dd><dt>통화</dt><dd>USD</dd></dl><a class="filing-link" href="${company.url}" target="_blank" rel="noopener noreferrer">공시 원문 열기 <span aria-hidden="true">↗</span></a>${c.evidence}`;
  $('process-list').innerHTML = c.steps.map(([label,tool]) => `<li>${label}<code>${tool}</code></li>`).join('');
  $('evidence-note').textContent = c.note;
  document.querySelector('.process-details').open = false;
  document.querySelectorAll('[data-case]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.case === activeCase)));
  document.querySelectorAll('[data-company]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.company === c.company)));
}
function route() {
  if (location.hash === '#main') return;
  const about = location.hash === '#about';
  $('about-view').hidden = !about;
  $('analysis-view').hidden = about;
  document.querySelectorAll('[data-view]').forEach(link => {
    if (link.dataset.view === (about ? 'about' : 'analysis')) link.setAttribute('aria-current','page');
    else link.removeAttribute('aria-current');
  });
  if (!about) renderCase(location.hash.split('/')[1] || activeCase);
  document.querySelector('[data-view="analysis"]').href = `#analysis/${activeCase}`;
  document.title = about ? '프로젝트 소개 · 재무탐정' : `${filings[cases[activeCase].company].name} 공시 분석 · 재무탐정`;
}
document.querySelectorAll('[data-case]').forEach(button => button.addEventListener('click',() => {
  location.hash = `analysis/${button.dataset.case}`;
}));
document.querySelectorAll('[data-company]').forEach(button => button.addEventListener('click',() => {
  location.hash = `analysis/${button.dataset.company === 'apple' ? 'supply' : 'cash'}`;
}));
window.addEventListener('hashchange', route);
route();
