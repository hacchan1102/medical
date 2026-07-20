# -*- coding: utf-8 -*-
"""
みんなの薬剤師 記事自動生成パイプライン
- pipeline/keywords.csv から次の pending キーワードを取得
- Claude API で記事素材(JSON)を生成
- 既存コラム(column-cold-early.html)を雛形にHTMLを組み立て
- 検証(FAQ同期・JSON-LD・受診目安・NG表現)に合格したら
  column-<slug>.html を作成し、column.html と sitemap.xml を更新
- 生成したファイル名を pipeline/last_generated.txt に書き出す(ワークフローが使用)

実行: python3 pipeline/generate_article.py
必要: 環境変数 ANTHROPIC_API_KEY  (テスト時は MOCK_JSON=path で API を使わず実行可)
"""
import csv, json, os, re, sys, datetime, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(ROOT, "pipeline", "keywords.csv")
SKELETON = os.path.join(ROOT, "column-cold-early.html")
TODAY = datetime.date.today()
TODAY_ISO = TODAY.isoformat()
TODAY_JP = f"{TODAY.year}年{TODAY.month}月{TODAY.day}日"
BASE_URL = "https://www.minnnanoyakuzaishi.com/"

ALLOWED_LINKS = [
    "headache.html", "cold.html", "allergy.html", "stomach.html",
    "constipation.html", "diarrhea.html", "throat.html", "fatigue.html",
    "medicines.html", "column.html", "index.html#symptoms",
    "column-cold-early.html", "column-fever-adult.html", "column-headache-types.html",
    "column-headache-daily.html", "column-period-pain.html", "column-hangover.html",
    "column-allergy-drowsy.html", "column-constipation-habit.html",
    "column-constipation-relief.html", "column-diarrhea-care.html",
    "column-heartburn.html", "column-nausea.html", "column-stomachache.html",
    "column-pharmacist-consult.html",
]
BANNED = ["必ず治", "絶対に安全", "副作用はありません", "100%", "誰でも安心", "受診は不要"]
GRADIENTS = [
    "linear-gradient(145deg,#FCA5A5,#F87171)", "linear-gradient(145deg,#93C5FD,#60A5FA)",
    "linear-gradient(145deg,#6EE7B7,#34D399)", "linear-gradient(145deg,#FCD34D,#FBBF24)",
    "linear-gradient(145deg,#A78BFA,#818CF8)", "linear-gradient(145deg,#F9A8D4,#F472B6)",
    "linear-gradient(145deg,#67E8F9,#22D3EE)", "linear-gradient(145deg,#FDBA74,#FB923C)",
]

PROMPT = """あなたは日本の看護師・薬剤師が監修するOTC医薬品情報サイト「みんなの薬剤師」の編集者です。
次のキーワードで、市販薬の選び方コラム記事の素材をJSONで作成してください。

キーワード: {keyword}
仮タイトル: {working_title}
補足: {notes}

# 絶対に守るルール(医療系サイトのため厳守)
- 断定的な効果効能の保証はしない。「〜とされています」「〜ことがあります」等の控えめな表現を使う
- 特定の商品名を推奨しない。成分名(一般名)で説明する
- 成分の説明には必ず「製品によって配合が異なるためパッケージ・添付文書を確認」の趣旨を入れる
- 必ず「⚠️ 受診の目安」に相当するセクションを1つ入れ、受診すべき危険なサインを箇条書きで示す。閾値は低め(保守的)にする
- 妊娠中・授乳中・子ども・高齢者・持病のある人への注意に言及する
- 誇大表現・不安を煽る表現は使わない

# 出力形式
JSONのみを出力(前置き・コードブロック記号なし)。構造:
{{
  "title": "SEOタイトル(30字前後、サイト名は含めない)",
  "h1": "記事見出し(titleと同じでも可)",
  "description": "meta description(80〜100字、「看護師・薬剤師が解説」を含める)",
  "card_text": "一覧カード用の説明(40〜60字)",
  "icon_emoji": "記事を表す絵文字1つ",
  "points": ["この記事のポイント4つ。重要語は<strong>タグ可", "...", "...", "..."],
  "sections": [
    {{"emoji": "見出し絵文字", "heading": "見出し(絵文字は含めない)",
      "html": "<p class=\\"body-text\\">本文</p> 形式。表が有効な箇所は<table class=\\"info-table\\"><tr><th>項目</th><td>説明</td></tr>...</table>、箇条書きは<ul style=\\"margin:0 0 1.5rem 1.3rem;color:var(--slate);line-height:1.95\\"><li>..</li></ul>を使用"}}
  ],
  "faq": [{{"q": "質問", "a": "回答(1〜3文)"}}],
  "related": [{{"href": "リンク先", "label": "絵文字+ラベル"}}]
}}

# 条件
- sections は4〜6個。うち1つは heading に「受診」を含む警告セクション(emoji は ⚠️)
- 成分や選び方の説明が中心のセクションでは info-table を使う
- faq はちょうど5個
- related はちょうど4個。href は次のリストからのみ選ぶ(medicines.html には ?q=キーワード を付けてよい):
{allowed}
- 本文の合計は1200〜1800字程度。同じ内容の繰り返しをしない
"""


GEMINI_MODELS = [
    os.environ.get("GEMINI_MODEL", ""),
    "gemini-flash-latest", "gemini-3.5-flash", "gemini-2.5-flash",
]


def call_gemini(prompt: str) -> str:
    """Gemini API (Google AI Studio, 無料枠あり・クレカ不要)"""
    key = os.environ["GEMINI_API_KEY"].strip()
    last_err = None
    for model in [m for m in GEMINI_MODELS if m]:
        try:
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                data=json.dumps({
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "maxOutputTokens": 8192,
                        "responseMimeType": "application/json",
                    },
                }).encode(),
                headers={"Content-Type": "application/json", "x-goog-api-key": key},
            )
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.loads(r.read().decode())
            parts = data["candidates"][0]["content"]["parts"]
            print(f"Gemini model used: {model}")
            return "".join(p.get("text", "") for p in parts)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()[:500]
            except Exception:
                pass
            last_err = f"{model}: HTTP {e.code} {body}"
            print(f"[Gemini] {last_err}")
            if e.code == 404:  # モデル名が変わった場合は次の候補を試す
                continue
            raise RuntimeError(f"Gemini API エラー: HTTP {e.code}\n{body}")
    raise RuntimeError(f"No Gemini model worked: {last_err}")


def call_claude(prompt: str) -> str:
    """Anthropic API (従量課金。ANTHROPIC_API_KEY がある場合のみ)"""
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({
            "model": "claude-sonnet-4-6",
            "max_tokens": 4000,
            "messages": [{"role": "user", "content": prompt}],
        }).encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": os.environ["ANTHROPIC_API_KEY"].strip(),
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.loads(r.read().decode())
    return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")


def api_call(prompt: str) -> str:
    if os.environ.get("GEMINI_API_KEY"):
        return call_gemini(prompt)
    if os.environ.get("ANTHROPIC_API_KEY"):
        return call_claude(prompt)
    raise RuntimeError("GEMINI_API_KEY か ANTHROPIC_API_KEY のどちらかを設定してください")


def parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0))


def validate(a: dict) -> list:
    errs = []
    if not (20 <= len(a.get("description", "")) <= 130):
        errs.append("description length out of range")
    if len(a.get("points", [])) != 4:
        errs.append("points must be 4")
    secs = a.get("sections", [])
    if not (4 <= len(secs) <= 6):
        errs.append("sections must be 4-6")
    if not any("受診" in s.get("heading", "") for s in secs):
        errs.append("missing 受診 section")
    if len(a.get("faq", [])) != 5:
        errs.append("faq must be 5")
    rel = a.get("related", [])
    if len(rel) != 4:
        errs.append("related must be 4")
    for r in rel:
        base = r.get("href", "").split("?")[0]
        if base not in ALLOWED_LINKS:
            errs.append(f"related href not allowed: {r.get('href')}")
    joined = json.dumps(a, ensure_ascii=False)
    for w in BANNED:
        if w in joined:
            errs.append(f"banned phrase: {w}")
    if "<script" in joined.lower():
        errs.append("script tag not allowed")
    return errs


def build_page(a: dict, slug: str) -> str:
    s = open(SKELETON, encoding="utf-8").read()
    fname = f"column-{slug}.html"
    url = BASE_URL + fname

    # ---- head: title / descriptions / og / canonical ----
    old_title = re.search(r"<title>(.*?)</title>", s).group(1)
    site_suffix = "｜" + old_title.split("｜", 1)[1] if "｜" in old_title else ""
    s = s.replace(f"<title>{old_title}</title>", f"<title>{a['title']}{site_suffix}</title>")
    old_desc = re.search(r'<meta name="description" content="([^"]*)"', s).group(1)
    s = s.replace(old_desc, a["description"])
    old_ogt = re.search(r'<meta property="og:title" content="([^"]*)"', s).group(1)
    s = s.replace(old_ogt, a["title"])
    s = re.sub(r'(<link rel="canonical" href=")[^"]*(")', r"\g<1>" + url + r"\g<2>", s)
    s = re.sub(r'(<meta property="og:url" content=")[^"]*(")', r"\g<1>" + url + r"\g<2>", s)

    # ---- JSON-LD: rebuild from skeleton graph ----
    m = re.search(r'(<script type="application/ld\+json">)(.*?)(</script>)', s, re.S)
    data = json.loads(m.group(2))
    graph = data["@graph"] if isinstance(data, dict) and "@graph" in data else data
    new_graph = []
    for node in graph:
        t = node.get("@type")
        if t == "BreadcrumbList":
            for item in node["itemListElement"]:
                if item.get("position") == 3:
                    item["name"] = a["h1"]
                    item["item"] = url
            new_graph.append(node)
        elif t == "Article":
            node["headline"] = a["h1"]
            node["description"] = a["description"]
            node["datePublished"] = TODAY_ISO
            node["dateModified"] = TODAY_ISO
            for key in ("mainEntityOfPage", "url"):
                if key in node:
                    if isinstance(node[key], dict):
                        node[key]["@id"] = url
                    else:
                        node[key] = url
            new_graph.append(node)
        elif t == "FAQPage":
            continue  # rebuilt below
        else:
            new_graph.append(node)
    new_graph.append({
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": f["q"],
             "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
            for f in a["faq"]
        ],
    })
    if isinstance(data, dict) and "@graph" in data:
        data["@graph"] = new_graph
    else:
        data = new_graph
    s = s[:m.start()] + m.group(1) + json.dumps(data, ensure_ascii=False) + m.group(3) + s[m.end():]

    # ---- breadcrumb (visible) ----
    s = re.sub(r'(<nav class="breadcrumb">.*?<span>›</span>\s*)[^<]+(\s*</nav>)',
               r"\g<1>" + a["h1"] + r"\g<2>", s, flags=re.S)

    # ---- article body ----
    pts = "\n".join(f"      <li>{p}</li>" for p in a["points"])
    sec_html = []
    for sec in a["sections"]:
        sec_html.append(f'  <h2 class="section-title">{sec["emoji"]} {sec["heading"]}</h2>\n  {sec["html"]}')
    faq_html = "\n".join(
        f'    <div class="faq-item"><p class="faq-q">{f["q"]}</p><p class="faq-a">{f["a"]}</p></div>'
        for f in a["faq"])
    body = f'''<h1 class="page-h1">{a["h1"]}</h1>
  <p class="meta-line">監修：<strong>みんなの薬剤師（看護師・薬剤師）</strong>　最終更新日：{TODAY_JP}</p>

  <div class="intro-text">
    <strong style="display:block;margin-bottom:.7rem;font-size:1.08rem;color:var(--blue)">この記事のポイント</strong>
    <ul style="margin:0 0 0 1.2rem;line-height:1.95;color:var(--slate)">
{pts}
    </ul>
  </div>

{chr(10).join(sec_html)}

  <h2 class="section-title">よくある質問</h2>
  <section class="faq-section">
{faq_html}
  </section>
  '''
    bstart = s.find('<h1 class="page-h1"')
    bend = s.find("</article>", bstart)
    s = s[:bstart] + body + s[bend:]

    # ---- related links ----
    rel = "".join(f'<a class="related-link" href="{r["href"]}">{r["label"]}</a>' for r in a["related"])
    s = re.sub(r'(<section class="related-section"><div class="related-links">).*?(</div></section>)',
               r"\g<1>" + rel + r"\g<2>", s, flags=re.S)
    return s


def final_check(html: str) -> list:
    errs = []
    try:
        for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
            json.loads(x)
    except Exception as e:
        errs.append(f"JSON-LD broken: {e}")
    vis = html.count('class="faq-q"')
    q = len(re.findall(r'"@type":\s*"Question"', html))
    fp = len(re.findall(r'"@type":\s*"FAQPage"', html))
    if not (vis == q == 5 and fp == 1):
        errs.append(f"FAQ sync mismatch vis={vis} q={q} fp={fp}")
    if 'class="intro-text"' not in html:
        errs.append("missing points box")
    if html.count('class="related-link"') != 4:
        errs.append("related links != 4")
    if "cold-early" in html.split("</head>")[0]:
        errs.append("head still references skeleton URL")
    return errs


def update_column_index(a: dict, slug: str):
    p = os.path.join(ROOT, "column.html")
    s = open(p, encoding="utf-8").read()
    used = len(re.findall(r'class="column-card"', s))
    grad = GRADIENTS[used % len(GRADIENTS)]
    card = f'''            <a class="column-card" href="column-{slug}.html">
        <span class="column-icon" style="background:{grad};color:#fff;">{a["icon_emoji"]}</span>
        <div class="column-body"><h3>{a["h1"]}</h3><p>{a["card_text"]}</p><span class="column-more">続きを読む →</span></div>
      </a>
'''
    i = s.find('<div class="column-grid">')
    i = s.find("\n", i) + 1
    s = s[:i] + card + s[i:]
    open(p, "w", encoding="utf-8").write(s)


def update_sitemap(slug: str):
    p = os.path.join(ROOT, "sitemap.xml")
    s = open(p, encoding="utf-8").read()
    entry = f'''  <url>
    <loc>{BASE_URL}column-{slug}.html</loc>
    <lastmod>{TODAY_ISO}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.6</priority>
  </url>
'''
    s = s.replace("</urlset>", entry + "</urlset>")
    open(p, "w", encoding="utf-8").write(s)


def main():
    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8")))
    target = next((r for r in rows if r["status"] == "pending"), None)
    if target is None:
        print("No pending keywords. Nothing to do.")
        open(os.path.join(ROOT, "pipeline", "last_generated.txt"), "w").write("")
        return
    slug = target["slug"]
    fname = f"column-{slug}.html"
    if os.path.exists(os.path.join(ROOT, fname)):
        print(f"{fname} already exists; marking done and exiting.")
        target["status"] = "done"
    else:
        prompt = PROMPT.format(keyword=target["keyword"], working_title=target["working_title"],
                               notes=target["notes"] or "特になし",
                               allowed="\n".join("  - " + x for x in ALLOWED_LINKS))
        mock = os.environ.get("MOCK_JSON")
        if mock:
            article = json.load(open(mock, encoding="utf-8"))
        else:
            article = None
            last_errs = []
            for attempt in range(2):
                p2 = prompt if attempt == 0 else prompt + "\n\n前回の出力には次の問題がありました。修正して再出力:\n" + "\n".join(last_errs)
                try:
                    raw = api_call(p2)
                except Exception as e:
                    print("APIの呼び出しに失敗しました（キー設定を確認してください）:", e)
                    sys.exit(1)
                try:
                    cand = parse_json(raw)
                except Exception as e:
                    last_errs = [f"JSON parse error: {e}"]
                    continue
                last_errs = validate(cand)
                if not last_errs:
                    article = cand
                    break
            if article is None:
                print("Generation failed validation:", last_errs)
                sys.exit(1)
        if mock:
            errs = validate(article)
            if errs:
                print("Mock validation errors:", errs)
                sys.exit(1)
        html = build_page(article, slug)
        errs = final_check(html)
        if errs:
            print("Final check failed:", errs)
            sys.exit(1)
        open(os.path.join(ROOT, fname), "w", encoding="utf-8").write(html)
        update_column_index(article, slug)
        update_sitemap(slug)
        target["status"] = "done"
        target["notes"] = (target["notes"] + " | " if target["notes"] else "") + f"generated {TODAY_ISO}"
        print(f"Generated {fname}")
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as fo:
        w = csv.DictWriter(fo, fieldnames=["slug", "keyword", "working_title", "status", "notes"])
        w.writeheader()
        w.writerows(rows)
    open(os.path.join(ROOT, "pipeline", "last_generated.txt"), "w").write(fname)


if __name__ == "__main__":
    main()
