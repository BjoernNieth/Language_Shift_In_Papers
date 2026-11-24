# arXiv OAI-PMH: the requests `fetch_metadata.py` sends

All requests below were sent and checked on 2026-11-18. Use them in Postman to see what the script sees.

## Basics
- **Endpoint:** `https://oaipmh.arxiv.org/oai` (the old `https://export.arxiv.org/oai2` redirects here with 301).
- **Method:** `GET`, all arguments as query parameters (in Postman: the *Params* tab).
- **Header:** `User-Agent: arxiv-metadata-research-harvest/0.1` (the script sends this; any descriptive value works).
- **Pace:** at most one request every 3 seconds, one connection at a time
  ([Terms of Use](https://info.arxiv.org/help/api/tou.html)). Fine for clicking in Postman; don't run a Postman
  collection runner without a delay.
- **Responses** are XML. **Errors also come back as HTTP 200**, with an `<error code="…">` element instead of
  the result. Only server overload is a real HTTP error: `503` with a `Retry-After` header (seconds to wait).
- **Caching:** the `<responseDate>` is often hours or days old. arXiv serves cached responses, so the same request
  returns the same result for a while.
- Protocol reference: [OAI-PMH 2.0](https://www.openarchives.org/OAI/openarchivesprotocol.html);
  arXiv's page: [info.arxiv.org/help/oa](https://info.arxiv.org/help/oa/index.html).

## 1. Identify: what is this server?
```
GET https://oaipmh.arxiv.org/oai?verb=Identify
```
Look at `<earliestDatestamp>2005-09-16</earliestDatestamp>`: no `from` date may be earlier (see the error example
in 6). `<granularity>YYYY-MM-DD</granularity>`: dates are whole days, no times.

## 2. ListMetadataFormats: which formats are there?
```
GET https://oaipmh.arxiv.org/oai?verb=ListMetadataFormats
```
Four formats: `oai_dc` (generic Dublin Core), `arXiv`, `arXivOld`, `arXivRaw`. The script uses **`arXivRaw`**
because it is the only one that lists every version with its date and size. Its field definitions:
[arXivRaw.xsd](https://oaipmh.arxiv.org/OAI/arXivRaw.xsd).

## 3. ListSets: the subject areas
```
GET https://oaipmh.arxiv.org/oai?verb=ListSets
```
Top-level sets: `physics`, `math`, `cs`, `q-bio`, `q-fin`, `stat`, `eess`, `econ`. The script doesn't filter by
set (it harvests everything), but you can (see 7).

## 4. GetRecord: one paper
```
GET https://oaipmh.arxiv.org/oai?verb=GetRecord&identifier=oai:arXiv.org:1701.03483&metadataPrefix=arXivRaw
```
| Param | Value |
|---|---|
| `verb` | `GetRecord` |
| `identifier` | `oai:arXiv.org:` + arXiv ID |
| `metadataPrefix` | `arXivRaw` |

The best request for understanding the format. This paper has four versions (v1 2017-01-12, v4 2026-01-15) and
three categories. Old-style IDs work the same way: `identifier=oai:arXiv.org:hep-th/9901001`.

How the record becomes a CSV row (`row()` in the script):

| XML | CSV column |
|---|---|
| `<header><datestamp>` | `datestamp` (last time arXiv changed the record, **not** the publication date) |
| `<header status="deleted">`, or no `<arXivRaw>` / no `<version>` | no row; logged in `data/metadata/skipped.csv` with the reason (`deleted`, `no_metadata`, `no_versions`) |
| `<id>` | `id` |
| `<title>` | `title` (whitespace collapsed) |
| `<categories>` (space-separated) | `categories`; the **first** one is `primary_category` |
| part of the primary category before the `.` | `archive` (`math.DG` → `math`, `cond-mat.mes-hall` → `cond-mat`) |
| archive, with all physics archives merged | `group` (our choice, not arXiv's: `cond-mat`, `hep-th`, `astro-ph`, `quant-ph`, … → `physics`) |
| first `<version><date>` | `v1_date`, `v1_year` |
| number of `<version>` elements | `n_versions` |
| last `<version><date>` | `last_date` |
| first / last `<version><size>` | `v1_size_kb`, `last_size_kb` |
| first `<version><source_type>` | `v1_source_type` (raw code, often empty; not interpreted) |
| `<license>`, `<doi>`, `<journal-ref>` | same names |

Not kept: `<abstract>`, `<authors>`, `<submitter>`, `<comments>`, `<msc-class>`.

The header's `<setSpec>` values (`math:math:DG`, `physics:cond-mat:mes-hall`) list the sets of all categories.
The script doesn't use them.

## 5. ListRecords: many papers, first page
```
GET https://oaipmh.arxiv.org/oai?verb=ListRecords&metadataPrefix=arXivRaw&from=2026-11-02&until=2026-11-02
```
| Param | Value |
|---|---|
| `verb` | `ListRecords` |
| `metadataPrefix` | `arXivRaw` |
| `from`, `until` | `YYYY-MM-DD`, both inclusive |

**`from`/`until` filter by datestamp (last change), not by publication date.** This one day returns papers
from 2009, 2016, 2017 …, because arXiv touched their records on 2026-11-02. That's why the script harvests
everything and reads the publication date from v1.

The script asks for one calendar month per chunk (`from=2026-11-01&until=2026-11-30`); the first chunk starts at
`2005-09-16`. A page has up to 1,300 records (about 3.4 MB). At the end of the page:
```xml
<resumptionToken expirationDate='2026-11-19T00:00:00Z'>verb%3DListRecords%26metadataPrefix%3DarXivRaw%26from%3D2026-11-02%26until%3D2026-11-02%26skip%3D1300</resumptionToken>
```
The token is (URL-encoded) the original request plus `skip=1300`. It expires at the next midnight UTC. An empty
or missing token means the last page.

## 6. ListRecords: next page
```
GET https://oaipmh.arxiv.org/oai?verb=ListRecords&resumptionToken=verb%3DListRecords%26metadataPrefix%3DarXivRaw%26from%3D2026-11-02%26until%3D2026-11-02%26skip%3D1300
```
| Param | Value |
|---|---|
| `verb` | `ListRecords` |
| `resumptionToken` | the token text, **pasted exactly as it appears in the XML** |

Send **only** these two parameters (no `metadataPrefix`, `from`, `until`). Both pasting the token as-is and
encoding it once more work. The script repeats this until there is no token.

Errors worth triggering once:
```
GET https://oaipmh.arxiv.org/oai?verb=ListRecords&metadataPrefix=arXivRaw&from=2005-01-01&until=2005-01-31
```
→ `<error code='badArgument'>… Reason: start date too early</error>` (HTTP 200).
Other codes: `noRecordsMatch` (nothing changed in that range; the script treats it as an empty month),
`badResumptionToken` (expired or mistyped token), `cannotDisseminateFormat` (unknown `metadataPrefix`).

## 7. ListRecords with a set (not used by the script)
```
GET https://oaipmh.arxiv.org/oai?verb=ListRecords&metadataPrefix=arXivRaw&set=cs&from=2026-11-02&until=2026-11-02
```
Restricts to one subject area. It includes **cross-lists**: papers whose primary category is elsewhere but that
are also listed in `cs` (the first record here is a `math-ph` paper). Filtering by `primary_category` in the CSV
is therefore not the same as harvesting a set.

## What the script does, as a sequence of these requests
```
for each month M from 2005-09 to now:
    ListRecords(arXivRaw, from=first day of M (≥ 2005-09-16), until=last day of M)     # request 5
    while the response has a resumptionToken:
        ListRecords(resumptionToken=…)                                                  # request 6
    write data/metadata/parts/skipped/M.csv, then data/metadata/parts/M.csv
merge all parts → data/metadata/arxiv_metadata.csv (one row per id, the newest datestamp wins)
             and data/metadata/skipped.csv
```
Between all requests: 3 s pause. On HTTP 503: wait `Retry-After` seconds. On network errors: wait 30, 60, 90 … s,
give up after 10 attempts.
