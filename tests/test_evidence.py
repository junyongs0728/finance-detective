from finance_detective.retrieval.evidence import rank


def test_relevant_source_and_no_match():
    chunks=[{"id":"a","text":"Operating cash flow decreased due to receivables", "page":5,"source_url":"https://example.com/#page=5"},
            {"id":"b","text":"Revenue increased in retail sales", "page":6,"source_url":"https://example.com/#page=6"}]
    result=rank(chunks,"cash flow")
    assert result[0]["id"]=="a"
    assert result[0]["page"]==5
    assert rank(chunks,"zzzzzz")==[]
    assert rank(chunks,"")==[]
    assert rank([],"cash")==[]


def test_cached_and_uncached_rank_agree():
    from finance_detective.retrieval.evidence import LexicalIndex
    chunks=[{"id":"a","text":"cash flow cash", "page":1}, {"id":"b","text":"retail revenue", "page":2}]
    index=LexicalIndex(chunks)
    for query in ("cash", "revenue", "unknown", ""):
        assert index.rank(query)==rank(chunks,query)


def test_cache_refreshes_when_file_changes(tmp_path, monkeypatch):
    import json
    from finance_detective.retrieval import evidence
    path=tmp_path/'index.json'
    monkeypatch.setattr(evidence,'INDEX',path)
    payload={"document":"test","chunks":[{"id":"a","text":"cash flow"}]}
    path.write_text(json.dumps(payload))
    assert evidence.search('cash')['results'][0]['id']=='a'
    payload['chunks']=[{"id":"new","text":"revenue growth growth growth"}]
    path.write_text(json.dumps(payload))
    assert evidence.search('cash')['results']==[]
    assert evidence.search('revenue')['results'][0]['id']=='new'
