"""Radar diário de canais novos para o Buscador de Nichos.

Roda 1x por dia (GitHub Actions). Pesquisa os nichos de kw.json com UMA chave (secret YT_KEY),
acumula canais novos em data/novos_<lang>.json e atualiza os números dos canais já achados.
Critério (igual ao app): 1º vídeo há no máx. 90 dias, até 15 vídeos, 20 mil+ views no canal.
Só usa a biblioteca padrão do Python.
"""
import json, os, sys, math, re, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
KEY = os.environ.get("YT_KEY", "").strip()
API = "https://www.googleapis.com/youtube/v3/"
NEW_AGE, NEW_MAXV, NEW_MINVIEWS = 90, 15, 20000
# pesquisas por idioma em cada execução (100 unidades cada). Total 60 = 6.000 unidades.
BUDGET = json.loads(os.environ.get("RADAR_BUDGET") or '{"pt":20,"en":16,"es":10,"de":7,"fr":7}')
REGION = {"pt": "BR", "en": "US", "es": "MX", "de": "DE", "fr": "FR"}
WINDOWS = [30, 7, 90]  # período da pesquisa, alterna a cada volta completa nas palavras
NOW = datetime.now(timezone.utc)
# nichos prioritários aparecem 2x no rodízio de cada dia
PRIORITY = {"Curiosidades": 2, "Jogos": 2, "História": 2, "Documentário": 2, "Música": 2, "Mistérios e Dark": 2}
OLD_CAT = {"Oceano": "Animais e Natureza", "Pré-história": "Animais e Natureza", "Animais": "Animais e Natureza",
           "Arqueologia e Mistérios": "Mistérios e Dark"}
MOVIE_RE = re.compile(r"filme completo|full movie|pel[ií]cula completa|film complet|ganzer film|filme dublado|"
                      r"movie recap|resumo d[eo] filme|filme de a[cç][aã]o|filme de terror|recap\b", re.I)


def is_movie(e):
    """Canal de filme: maioria dos vídeos é da categoria Filmes (1) com 1h+, ou títulos de filme completo/recap."""
    v = e["vids"]
    if not v:
        return False
    long_film = sum(1 for x in v if x.get("cat") == "1" and x["secs"] >= 3600)
    titled = sum(1 for x in v if MOVIE_RE.search(x["title"]))
    return long_film * 2 >= len(v) or titled * 2 >= len(v)

units = 0
search_blocked = False


class QuotaError(Exception):
    pass


def yt(ep, cost, **p):
    global units
    p["key"] = KEY
    url = API + ep + "?" + urllib.parse.urlencode({k: v for k, v in p.items() if v not in ("", None)})
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            j = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            j = json.load(e)
        except Exception:
            raise RuntimeError(f"HTTP {e.code} em {ep}")
    if "error" in j:
        msg = j["error"].get("message", "")
        if re.search(r"quota|Search Queries|dailyLimit", msg, re.I):
            raise QuotaError(msg[:200])
        raise RuntimeError(f"{ep}: {msg[:200]}")
    units += cost
    return j


def iso(d):
    return datetime.fromisoformat(d.replace("Z", "+00:00"))


def days_since(d):
    return max(1e-9, (NOW - iso(d)).total_seconds() / 86400)


def secs(d):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "") or None
    if not m:
        return 0
    return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)


def vid_obj(v):
    s = secs((v.get("contentDetails") or {}).get("duration"))
    views = int(v["statistics"].get("viewCount", 0))
    th = v["snippet"]["thumbnails"]
    return {"id": v["id"], "cat": v["snippet"].get("categoryId"), "title": v["snippet"]["title"], "thumb": (th.get("medium") or th.get("default"))["url"],
            "views": views, "secs": s, "short": 0 < s <= 180, "date": v["snippet"]["publishedAt"],
            "vpd": views / max(1, days_since(v["snippet"]["publishedAt"]))}


def ch_fields(c):
    st = c["statistics"]
    return {"name": c["snippet"]["title"], "handle": c["snippet"].get("customUrl", ""),
            "avatar": (c["snippet"]["thumbnails"].get("default") or {}).get("url", ""),
            "country": c["snippet"].get("country", ""), "hidden": bool(st.get("hiddenSubscriberCount")),
            "subs": int(st.get("subscriberCount", 0)), "total": int(st.get("viewCount", 0)),
            "nvid": int(st.get("videoCount", 0))}


def finish(e):
    e["vids"].sort(key=lambda v: -v["views"])
    e["vids"] = e["vids"][:6]
    e["shortsPct"] = round(100 * sum(v["short"] for v in e["vids"]) / max(1, len(e["vids"])))
    return e


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def refresh(lst):
    """Atualiza inscritos/views de todos os canais e vídeos guardados (1 unidade a cada 50)."""
    by = {e["id"]: e for e in lst}
    ids = list(by)
    for i in range(0, len(ids), 50):
        for c in yt("channels", 1, part="snippet,statistics", id=",".join(ids[i:i + 50])).get("items", []):
            by[c["id"]].update(ch_fields(c))
    vmap = {v["id"]: (e, v) for e in lst for v in e["vids"]}
    vids = list(vmap)
    for i in range(0, len(vids), 50):
        for v in yt("videos", 1, part="snippet,statistics,contentDetails", id=",".join(vids[i:i + 50])).get("items", []):
            e, old = vmap[v["id"]]
            old.update(vid_obj(v))
    for e in lst:
        finish(e)


def discover(lang, st, lst, n):
    global search_blocked
    allkw = load(os.path.join(ROOT, "kw.json"), {})[lang]
    cats = list(dict.fromkeys(c for _, c in allkw))
    cycle = [c for c in cats if PRIORITY.get(c, 1) >= 1] + [c for c in cats if PRIORITY.get(c, 1) >= 2]
    kwidx = st.setdefault("kwc", {})
    known = {e["id"] for e in lst}
    chk = st.setdefault("chk", {})
    added = 0
    for _ in range(n):
        if search_blocked:
            break
        ci = st.get("cyc", 0)
        st["cyc"] = ci + 1
        cat = cycle[ci % len(cycle)]
        kws = [q for q, c in allkw if c == cat]
        k = kwidx.get(cat, 0)
        kwidx[cat] = k + 1
        q = kws[k % len(kws)]
        win = WINDOWS[(k // len(kws)) % len(WINDOWS)]
        after = (NOW - timedelta(days=win)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            r = yt("search", 100, part="snippet", type="video", q=q, order="relevance", publishedAfter=after,
                   maxResults=50, relevanceLanguage=lang, regionCode=REGION[lang], safeSearch="none")
        except QuotaError as e:
            print(f"  ! pesquisa bloqueada: {e}")
            search_blocked = True
            st["cyc"] = ci  # tenta a mesma palavra amanhã
            kwidx[cat] = k
            break
        ids = [i for i in dict.fromkeys(x["snippet"]["channelId"] for x in r.get("items", []))
               if i not in known and i not in chk]
        found = 0
        for i in range(0, len(ids), 50):
            for c in yt("channels", 1, part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50])).get("items", []):
                chk[c["id"]] = NOW.isoformat()
                f = ch_fields(c)
                if not (0 < f["nvid"] <= NEW_MAXV and f["total"] >= NEW_MINVIEWS):
                    continue
                pl = yt("playlistItems", 1, part="contentDetails", maxResults=50,
                        playlistId=c["contentDetails"]["relatedPlaylists"]["uploads"])
                items = pl.get("items", [])
                dates = sorted(x["contentDetails"].get("videoPublishedAt") for x in items if x["contentDetails"].get("videoPublishedAt"))
                if not dates or days_since(dates[0]) > NEW_AGE:
                    continue
                vr = yt("videos", 1, part="snippet,statistics,contentDetails",
                        id=",".join(x["contentDetails"]["videoId"] for x in items[:50]))
                if not vr.get("items"):
                    continue
                e = {"id": c["id"], **f, "created": dates[0], "first": dates[0], "cat": cat, "kw": q,
                     "found": NOW.strftime("%Y-%m-%d"), "vids": [vid_obj(v) for v in vr["items"]]}
                if is_movie(e):
                    continue
                lst.append(finish(e))
                known.add(c["id"])
                found += 1
        added += found
        print(f"  [{lang}] '{q}' ({win}d): {len(ids)} canais checados, {found} novos")
    return added


def main():
    if not KEY:
        sys.exit("Falta a variável YT_KEY")
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    state = load(os.path.join(ROOT, "data", "state.json"), {})
    summary = {}
    for lang, n in BUDGET.items():
        path = os.path.join(ROOT, "data", f"novos_{lang}.json")
        lst = load(path, {"list": []})["list"]
        st = state.setdefault(lang, {})
        # limpa: canais que passaram de 90 dias do 1º vídeo e checagens com +5 dias
        lst = [e for e in lst if days_since(e["first"]) <= NEW_AGE]
        st["chk"] = {k: v for k, v in st.get("chk", {}).items() if days_since(v) <= 5}
        try:
            refresh(lst)
            added = discover(lang, st, lst, n)
        except QuotaError as e:
            print(f"  ! cota acabou: {e}")
            added = 0
        lst = [e for e in lst if e["nvid"] <= NEW_MAXV * 2 and not is_movie(e)]  # cresceu muito ou é canal de filme
        for e in lst:
            e["cat"] = OLD_CAT.get(e["cat"], e["cat"])
        save(path, {"updated": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "lang": lang, "count": len(lst), "list": lst})
        summary[lang] = {"total": len(lst), "novos_hoje": added}
        print(f"[{lang}] total {len(lst)} | +{added} hoje | unidades até agora: {units}")
    state["last"] = {"at": NOW.isoformat(), "units": units, "search_blocked": search_blocked, "summary": summary}
    save(os.path.join(ROOT, "data", "state.json"), state)
    print("RESUMO", json.dumps(state["last"], ensure_ascii=False))


if __name__ == "__main__":
    main()
