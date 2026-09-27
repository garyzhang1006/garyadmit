"""One module per source. Each exposes `scrape(fetch, limit=None) -> Iterable[dict]`.

`fetch(url) -> str` is a polite, cached HTTP GET (see _common.Fetcher).
`limit` caps how many essay pages a source touches, for smoke tests.
Each yielded dict must pass _common.make_record().
"""
