"""Retrieve the exact selected filing and retain section-level provenance."""
import hashlib
import io
import re
from urllib.parse import urlencode, urlsplit
import warnings
import zipfile
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from finance_detective.providers.common import ROOT, ProviderError, fetch
from finance_detective.providers.dart_company import key

MAX_RAW = 40 * 1024 * 1024
MAX_CHUNKS = 1600


def extract_blocks(raw, provider):
    # DART custom XML contains HTML entities/constructs that truncate strict XML parsing.
    # html.parser consumes the full document; do not execute embedded scripts or links.
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(raw, 'html.parser')
    for node in soup.find_all(['script','style','noscript','ix:header','ix:hidden']): node.decompose()
    blocks=[]; section='본문'
    tags=['title','p'] if provider=='DART' else ['h1','h2','h3','h4','p','div']
    for node in soup.find_all(tags):
        if node.find_parent('table'): continue
        if node.name=='div' and node.find(['div','p','table','h1','h2','h3','h4']): continue
        text=' '.join(node.get_text(' ',strip=True).split())
        if not text: continue
        if node.name in ('title','h1','h2','h3','h4') or (len(text)<150 and re.match(r'(?i)^item\s+\d',text)):
            section=text; continue
        if len(text)<35: continue
        # Flattened tables are excluded: their column/sign semantics are not reliable evidence.
        blocks.append({'section':section[:250], 'text':text})
    if sum(len(b['text']) for b in blocks)<1000:
        raise ProviderError('공시 본문을 충분히 읽지 못했습니다. 원문 형식을 확인해야 합니다.', 'document_parse_error')
    return blocks


def split_blocks(blocks, doc_id):
    chunks=[]; buffer=''; section=''
    def flush(text, title):
        for offset in range(0,len(text),1200):
            part=text[offset:offset+1400].strip()
            if len(part)<35: continue
            ordinal=len(chunks)+1
            chunks.append({'id':f'{doc_id}:{ordinal}', 'ordinal':ordinal,'section':title,'text':part})
    for block in blocks:
        if buffer and (block['section']!=section or len(buffer)+len(block['text'])>1400):
            flush(buffer,section);buffer=''
        section=block['section']
        if len(block['text'])>1400:
            if buffer:flush(buffer,section);buffer=''
            flush(block['text'],section)
        else:buffer=(buffer+'\n'+block['text']).strip()
    if buffer:flush(buffer,section)
    if not chunks or len(chunks)>MAX_CHUNKS:
        raise ProviderError(f'문서 크기가 현재 처리 범위를 벗어났습니다. 문서당 최대 {MAX_CHUNKS}개 문단을 지원합니다.', 'document_too_large')
    return chunks


def download(data):
    accession=data['filing']['accession']
    provider=data['provider']
    if provider=='DART':
        if not re.fullmatch(r'\d{14}',accession):raise ProviderError('공시 번호 형식 오류')
        # Never persist or log this credential-bearing URL.
        raw=fetch('https://opendart.fss.or.kr/api/document.xml?'+urlencode({'crtfc_key':key(),'rcept_no':accession}), max_bytes=MAX_RAW)
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                filename=accession+'.xml'  # Main filing only; attachment scope is explicit.
                info=archive.getinfo(filename)
                if info.file_size>MAX_RAW:raise ProviderError('공시 원문 크기 제한을 초과했습니다.', 'document_too_large')
                document=archive.read(filename)
        except (zipfile.BadZipFile,KeyError):
            raise ProviderError('DART 공시 원문을 받지 못했습니다. 인증키와 공시 번호를 확인해주세요.', 'document_unavailable') from None
    else:
        url=data['source_url']; parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.netloc!='www.sec.gov' or not parsed.path.startswith('/Archives/edgar/data/'):
            raise ProviderError('허용된 SEC 공시 주소가 아닙니다.', 'invalid_source')
        document=fetch(url, max_bytes=MAX_RAW)
    if len(document)>MAX_RAW:raise ProviderError('공시 원문 크기 제한을 초과했습니다.', 'document_too_large')
    digest=hashlib.sha256(document).hexdigest()
    directory=ROOT/'data/raw/rag';directory.mkdir(parents=True,exist_ok=True)
    (directory/(digest+('.xml' if provider=='DART' else '.html'))).write_bytes(document)
    return document,digest
