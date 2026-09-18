"""sources.py -- dependency-free literature connectors for aar-harness.

Five sources, stdlib urllib only, honouring http_proxy / https_proxy:
  arxiv      structured preprint search (no key)
  openalex   bibliographic search, filters, forward citations (no key)
  crossref   DOI backfill, publisher metadata, licences (no key)
  hf         HuggingFace dataset discovery + BM25 in-dataset full-text search
  gh         GitHub code / repo search through the authenticated gh CLI

Every connector returns a list of normalized "Paper" dicts so results from
different sources can be deduplicated.  Run `python sources.py probe` to see
which sources are reachable from this machine.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aar_lib  # noqa: E402

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
ARXIV_MIN_INTERVAL = 8.0
USER_AGENT = "aar-harness/1.0 (+https://github.com/; research harness)"
MAILTO = os.environ.get("AAR_MAILTO", "aar-harness@example.invalid")
_last_arxiv_call = [0.0]


# ------------------------------------------------------------------- http

class SourceError(RuntimeError):
    def __init__(self, source, message, status=None):
        super().__init__(source + ": " + str(message))
        self.source = source
        self.status = status


def _opener():
    handlers = [urllib.request.ProxyHandler(), urllib.request.HTTPSHandler()]
    return urllib.request.build_opener(*handlers)


_OPENER = _opener()


def http_get(url, source="http", timeout=45, retries=3, backoff=2.0, accept=None, headers=None):
    """GET with proxy support and exponential backoff on 429 / 5xx / timeouts."""
    last = None
    for attempt in range(max(1, retries)):
        req = urllib.request.Request(url)
        req.add_header("User-Agent", USER_AGENT)
        if accept:
            req.add_header("Accept", accept)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with _OPENER.open(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
                continue
            raise SourceError(source, "HTTP " + str(exc.code) + " " + str(exc.reason), status=exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
                continue
    fallback = _curl_get(url, timeout, accept)
    if fallback is not None:
        return fallback
    raise SourceError(source, "unreachable: " + str(last))


def _curl_get(url, timeout, accept=None):
    """Last-resort transport.  Some proxies fail the OpenSSL handshake while the
    system curl succeeds (and vice versa), so try curl once before giving up."""
    if os.name != "nt" or os.environ.get("AAR_DISABLE_CURL_FALLBACK"):
        return None
    exe = shutil.which("curl") or shutil.which("curl.exe")
    if not exe:
        return None
    argv = [exe, "-sL", "--max-time", str(int(timeout))]
    if accept:
        argv += ["-H", "Accept: " + accept]
    argv += ["-A", USER_AGENT, url]
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=int(timeout) + 20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        return proc.stdout.decode("utf-8", errors="replace")
    except Exception:
        return None


def http_get_json(url, source="http", **kw):
    return json.loads(http_get(url, source=source, accept="application/json", **kw))


# --------------------------------------------------------------- normalize

def make_paper(source, **kw):
    paper = {"source": source, "id": None, "doi": None, "arxiv_id": None, "title": None, "authors": [], "year": None, "venue": None, "url": None, "abstract": None, "cited_by": None}
    paper.update(kw)
    if paper.get("doi"):
        paper["doi"] = normalize_doi(paper["doi"])
    return paper


def normalize_doi(doi):
    d = str(doi).strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "https://dx.doi.org/"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d or None


def paper_key(paper):
    doi = normalize_doi(paper.get("doi"))
    if doi:
        return "doi:" + doi
    if paper.get("arxiv_id"):
        return "arxiv:" + str(paper["arxiv_id"]).lower()
    return "title:" + aar_lib.slugify(paper.get("title") or "")


def dedupe(papers):
    """Merge duplicates by DOI, then arXiv id, then normalized title."""
    merged = {}
    order = []
    for p in papers:
        key = paper_key(p)
        if key not in merged:
            merged[key] = dict(p)
            merged[key]["sources"] = [p.get("source")]
            order.append(key)
            continue
        cur = merged[key]
        cur["sources"] = sorted(set(cur.get("sources", []) + [p.get("source")]))
        for field in ("doi", "arxiv_id", "abstract", "venue", "year", "url", "cited_by"):
            if not cur.get(field) and p.get(field):
                cur[field] = p[field]
        if len(p.get("authors") or []) > len(cur.get("authors") or []):
            cur["authors"] = p["authors"]
    return [merged[k] for k in order]


# -------------------------------------------------------------- 1. arxiv

def _arxiv_throttle():
    delta = time.time() - _last_arxiv_call[0]
    if delta < ARXIV_MIN_INTERVAL:
        time.sleep(ARXIV_MIN_INTERVAL - delta)
    _last_arxiv_call[0] = time.time()


def search_arxiv(query, max_results=20, start=0, sort="relevance", timeout=45, throttle_retries=2):
    """Query the arXiv Atom API.  Field prefixes: ti: abs: au: cat: all:

    arXiv throttles aggressively and answers with HTTP 406 -- not 429 -- once it does,
    so a 406 is treated as a rate-limit signal and retried with a long backoff rather
    than reported as a permanent error.  Space requests out (ARXIV_MIN_INTERVAL) and
    never parallelise this source; the block clears after a few minutes of quiet.
    """
    params = {"search_query": query, "start": str(start), "max_results": str(max_results), "sortBy": sort, "sortOrder": "descending"}
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params, safe=":,")
    url = url.replace("+", "%20")
    xml = None
    for attempt in range(throttle_retries + 1):
        _arxiv_throttle()
        try:
            xml = http_get(url, source="arxiv", timeout=timeout, accept="application/atom+xml", retries=1)
            break
        except SourceError as exc:
            if exc.status == 406 and attempt < throttle_retries:
                time.sleep(30.0 * (attempt + 1))
                continue
            raise
    root = ET.fromstring(xml)
    out = []
    for entry in root.findall(ATOM + "entry"):
        raw_id = (entry.findtext(ATOM + "id") or "").strip()
        arxiv_id = raw_id.rsplit("/", 1)[-1] if raw_id else None
        authors = [(a.findtext(ATOM + "name") or "").strip() for a in entry.findall(ATOM + "author")]
        published = entry.findtext(ATOM + "published") or ""
        out.append(make_paper("arxiv", id=arxiv_id, arxiv_id=arxiv_id, doi=entry.findtext(ARXIV_NS + "doi"), title=" ".join((entry.findtext(ATOM + "title") or "").split()), authors=[a for a in authors if a], year=(published[:4] or None), venue=(entry.findtext(ARXIV_NS + "journal_ref") or "arXiv"), url=raw_id or None, abstract=" ".join((entry.findtext(ATOM + "summary") or "").split())))
    return out


# ----------------------------------------------------------- 2. openalex

def _openalex_abstract(inverted):
    if not inverted:
        return None
    slots = []
    for word, positions in inverted.items():
        for pos in positions:
            slots.append((pos, word))
    slots.sort()
    return " ".join(w for _, w in slots)


def _openalex_paper(work):
    authors = []
    for a in (work.get("authorships") or []):
        name = (a.get("author") or {}).get("display_name")
        if name:
            authors.append(name)
    src = ((work.get("primary_location") or {}).get("source") or {})
    return make_paper("openalex", id=(work.get("id") or "").rsplit("/", 1)[-1] or None, doi=work.get("doi"), title=work.get("display_name") or work.get("title"), authors=authors, year=work.get("publication_year"), venue=src.get("display_name"), url=work.get("doi") or work.get("id"), abstract=_openalex_abstract(work.get("abstract_inverted_index")), cited_by=work.get("cited_by_count"))


def search_openalex(query, per_page=25, page=1, filters=None, sort=None, timeout=45):
    params = {"search": query, "per-page": str(per_page), "page": str(page), "mailto": MAILTO}
    if filters:
        params["filter"] = filters
    if sort:
        params["sort"] = sort
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    data = http_get_json(url, source="openalex", timeout=timeout)
    return [_openalex_paper(w) for w in (data.get("results") or [])]


def openalex_citations(work_id, per_page=50, timeout=45):
    """Forward citations of a work -- the highest-yield snowballing step."""
    wid = str(work_id).rsplit("/", 1)[-1]
    url = "https://api.openalex.org/works?filter=cites:" + urllib.parse.quote(wid) + "&per-page=" + str(per_page) + "&mailto=" + urllib.parse.quote(MAILTO)
    data = http_get_json(url, source="openalex", timeout=timeout)
    return [_openalex_paper(w) for w in (data.get("results") or [])]


def openalex_references(work_id, timeout=45):
    """Backward citations of a work."""
    wid = str(work_id).rsplit("/", 1)[-1]
    work = http_get_json("https://api.openalex.org/works/" + urllib.parse.quote(wid) + "?mailto=" + urllib.parse.quote(MAILTO), source="openalex", timeout=timeout)
    refs = [(r or "").rsplit("/", 1)[-1] for r in (work.get("referenced_works") or [])][:50]
    if not refs:
        return []
    url = "https://api.openalex.org/works?filter=openalex_id:" + "|".join(refs) + "&per-page=50&mailto=" + urllib.parse.quote(MAILTO)
    data = http_get_json(url, source="openalex", timeout=timeout)
    return [_openalex_paper(w) for w in (data.get("results") or [])]


# ----------------------------------------------------------- 3. crossref

def _crossref_paper(item):
    authors = []
    for a in (item.get("author") or []):
        name = " ".join(x for x in [a.get("given"), a.get("family")] if x).strip()
        if name:
            authors.append(name)
    parts = ((item.get("issued") or {}).get("date-parts") or [[None]])[0]
    year = str(parts[0]) if parts and parts[0] else None
    title = (item.get("title") or [None])[0]
    venue = (item.get("container-title") or [None])[0]
    return make_paper("crossref", id=item.get("DOI"), doi=item.get("DOI"), title=title, authors=authors, year=year, venue=venue, url=("https://doi.org/" + str(item.get("DOI"))) if item.get("DOI") else item.get("URL"), abstract=item.get("abstract"), cited_by=item.get("is-referenced-by-count"))


def search_crossref(query, rows=20, timeout=45):
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode({"query": query, "rows": str(rows), "mailto": MAILTO})
    data = http_get_json(url, source="crossref", timeout=timeout)
    return [_crossref_paper(i) for i in (((data.get("message") or {}).get("items")) or [])]


def lookup_crossref_doi(doi, timeout=45):
    d = normalize_doi(doi)
    if not d:
        return None
    url = "https://api.crossref.org/works/" + urllib.parse.quote(d) + "?mailto=" + urllib.parse.quote(MAILTO)
    try:
        data = http_get_json(url, source="crossref", timeout=timeout)
    except SourceError:
        return None
    msg = data.get("message")
    return _crossref_paper(msg) if msg else None


# ------------------------------------------------- 4. HuggingFace datasets

def search_hf_datasets(query, limit=10, timeout=45):
    """Dataset / benchmark discovery (Papers with Code is gone; HF fills that role)."""
    url = "https://huggingface.co/api/datasets?" + urllib.parse.urlencode({"search": query, "limit": str(limit)})
    data = http_get_json(url, source="hf", timeout=timeout)
    out = []
    for d in (data or []):
        out.append(make_paper("hf", id=d.get("id"), title=d.get("id"), year=(str(d.get("lastModified") or "")[:4] or None), venue="huggingface/datasets", url="https://huggingface.co/datasets/" + str(d.get("id")), abstract=d.get("description")))
    return out


def hf_dataset_search_rows(dataset, config, split, query, offset=0, length=10, timeout=90):
    """BM25 full-text search inside a dataset (contamination probing).

    Only datasets with Parquet exports are indexed; a 404/500 means the dataset
    is not searchable this way and the caller should fall back to reading parquet.
    """
    params = {"dataset": dataset, "config": config, "split": split, "query": query, "offset": str(offset), "length": str(min(length, 100))}
    url = "https://datasets-server.huggingface.co/search?" + urllib.parse.urlencode(params)
    return http_get_json(url, source="hf", timeout=timeout)


# ------------------------------------------------------------ 5. github

def _gh_json(args, timeout=90):
    try:
        proc = subprocess.run(["gh"] + args, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise SourceError("gh", "gh CLI not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise SourceError("gh", "timeout after " + str(timeout) + "s") from exc
    if proc.returncode != 0:
        raise SourceError("gh", (proc.stderr or proc.stdout or "non-zero exit").strip()[:300])
    try:
        return json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise SourceError("gh", "unparseable output") from exc


def gh_search_code(query, limit=10):
    rows = _gh_json(["search", "code", query, "--limit", str(limit), "--json", "repository,path,url"])
    out = []
    for r in rows:
        repo = (r.get("repository") or {}).get("nameWithOwner") or ""
        out.append(make_paper("gh", id=repo + ":" + str(r.get("path")), title=repo + ":" + str(r.get("path")), venue="github/code", url=r.get("url")))
    return out


def gh_search_repos(query, limit=10):
    rows = _gh_json(["search", "repos", query, "--limit", str(limit), "--json", "fullName,description,url,stargazersCount,updatedAt"])
    out = []
    for r in rows:
        out.append(make_paper("gh", id=r.get("fullName"), title=r.get("fullName"), venue="github/repo", url=r.get("url"), abstract=r.get("description"), cited_by=r.get("stargazersCount"), year=(str(r.get("updatedAt") or "")[:4] or None)))
    return out


# --------------------------------------------------- multi-source helpers

def multi_search(query, per_source=10, sources=("arxiv", "openalex", "crossref"), errors=None):
    """Query several sources and return one deduplicated list."""
    collected = []
    for src in sources:
        try:
            if src == "arxiv":
                collected.extend(search_arxiv(query, max_results=per_source))
            elif src == "openalex":
                collected.extend(search_openalex(query, per_page=per_source))
            elif src == "crossref":
                collected.extend(search_crossref(query, rows=per_source))
            elif src == "hf":
                collected.extend(search_hf_datasets(query, limit=per_source))
            elif src == "gh":
                collected.extend(gh_search_repos(query, limit=per_source))
            else:
                raise ValueError("unknown source " + src)
        except SourceError as exc:
            if errors is not None:
                errors.append({"source": src, "error": str(exc), "status": exc.status})
    return dedupe(collected)


def probe_sources(timeout=20):
    """Availability probe used by 00-intake to pick a retrieval tier."""
    checks = []
    def run(name, fn):
        t0 = time.time()
        try:
            n = fn()
            checks.append({"source": name, "ok": True, "items": n, "seconds": round(time.time() - t0, 2)})
        except Exception as exc:
            checks.append({"source": name, "ok": False, "error": str(exc)[:200], "seconds": round(time.time() - t0, 2)})
    run("arxiv", lambda: len(search_arxiv("all:agent memory", max_results=1, timeout=timeout)))
    run("openalex", lambda: len(search_openalex("agent memory", per_page=1, timeout=timeout)))
    run("crossref", lambda: len(search_crossref("agent memory", rows=1, timeout=timeout)))
    run("hf", lambda: len(search_hf_datasets("agent", limit=1, timeout=timeout)))
    run("gh", lambda: len(gh_search_repos("agent memory", limit=1)))
    ok = [c["source"] for c in checks if c["ok"]]
    tier = "full" if len(ok) >= 4 else ("basic" if ok else "offline")
    return {"checked_at": aar_lib.utcnow(), "tier": tier, "available": ok, "checks": checks}


def main(argv):
    if not argv or argv[0] == "probe":
        print(json.dumps(probe_sources(), indent=2))
        return 0
    cmd = argv[0]
    query = argv[1] if len(argv) > 1 else "agent memory"
    limit = int(argv[2]) if len(argv) > 2 else 3
    errors = []
    if cmd == "multi":
        papers = multi_search(query, per_source=limit, errors=errors)
    elif cmd in ("arxiv", "openalex", "crossref", "hf", "gh"):
        papers = multi_search(query, per_source=limit, sources=(cmd,), errors=errors)
    else:
        print("usage: sources.py [probe|multi|arxiv|openalex|crossref|hf|gh] [query] [limit]")
        return 2
    print(json.dumps({"query": query, "count": len(papers), "errors": errors, "papers": papers}, indent=2, ensure_ascii=False))
    return 0 if papers or not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
