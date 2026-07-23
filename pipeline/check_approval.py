# -*- coding: utf-8 -*-
"""
メール返信による記事の公開承認チェッカー
- Gmail(IMAP)で直近3日の受信メールを確認
- 「Re: 【レビュー依頼】新規コラム: column-xxx.html」への返信を探す
- 本文の先頭行が OK系 → 該当PRをMerge(公開) / NG系 → PRをClose(破棄)
- 処理結果を確認メールで返信者(自分)に通知
- PRがすでにMerge/Close済みなら何もしない(二重処理防止)

必要な環境変数: GMAIL_USERNAME, GMAIL_APP_PASSWORD, GH_TOKEN, GH_REPO
"""
import imaplib, email, os, re, ssl, subprocess, json, smtplib, datetime
from email.header import decode_header, make_header
from email.mime.text import MIMEText

USER = os.environ["GMAIL_USERNAME"].strip()
PW = os.environ["GMAIL_APP_PASSWORD"].strip()
REPO = os.environ["GH_REPO"]

APPROVE = ("OK", "ＯＫ", "承認", "公開", "MERGE", "マージ", "LGTM")
REJECT = ("NG", "ＮＧ", "却下", "非公開", "CLOSE", "クローズ", "破棄")


def decode_subj(raw):
    try:
        return str(make_header(decode_header(raw or "")))
    except Exception:
        return raw or ""


def body_first_line(msg):
    """返信本文の最初の有効行(引用部を除く)を返す"""
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                cs = part.get_content_charset() or "utf-8"
                try:
                    text = part.get_payload(decode=True).decode(cs, errors="replace")
                except Exception:
                    continue
                break
    else:
        cs = msg.get_content_charset() or "utf-8"
        try:
            text = msg.get_payload(decode=True).decode(cs, errors="replace")
        except Exception:
            text = ""
    for line in text.splitlines():
        t = line.strip()
        if not t or t.startswith(">"):
            continue
        # Gmailの引用ヘッダ行(「2026年…に … さんは書きました:」/ "On ... wrote:")以降は引用
        if re.match(r"^(On .+wrote:|\d{4}年.+書きました)", t):
            break
        return t
    return ""


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True,
                       env={**os.environ, "GH_REPO": REPO})
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def find_open_pr(slug):
    code, out, err = gh("pr", "list", "--repo", REPO, "--head", f"art-{slug}",
                        "--state", "open", "--json", "number,title")
    if code != 0 or not out:
        return None
    prs = json.loads(out)
    return prs[0]["number"] if prs else None


def send_mail(subject, body):
    m = MIMEText(body, "plain", "utf-8")
    m["Subject"] = subject
    m["From"] = USER
    m["To"] = USER
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(USER, PW)
        s.send_message(m)


def main():
    M = imaplib.IMAP4_SSL("imap.gmail.com")
    M.login(USER, PW)
    M.select("INBOX")
    since = (datetime.date.today() - datetime.timedelta(days=3)).strftime("%d-%b-%Y")
    typ, data = M.search(None, f"(SINCE {since})")
    ids = data[0].split() if data and data[0] else []
    handled = 0
    for mid in reversed(ids[-200:]):
        typ, hdr = M.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
        if typ != "OK" or not hdr or not hdr[0]:
            continue
        subj = decode_subj(email.message_from_bytes(hdr[0][1]).get("Subject"))
        if "レビュー依頼" not in subj or not subj.lower().startswith("re"):
            continue
        m2 = re.search(r"column-([a-z0-9-]+)\.html", subj)
        if not m2:
            continue
        slug = m2.group(1)
        typ, full = M.fetch(mid, "(BODY.PEEK[])")
        msg = email.message_from_bytes(full[0][1])
        first = body_first_line(msg).upper()
        decision = None
        if any(first.startswith(w) for w in APPROVE):
            decision = "approve"
        elif any(first.startswith(w) for w in REJECT):
            decision = "reject"
        if decision is None:
            continue
        pr = find_open_pr(slug)
        if pr is None:
            continue  # すでに処理済み or 該当なし
        fname = f"column-{slug}.html"
        if decision == "approve":
            code, out, err = gh("pr", "merge", str(pr), "--repo", REPO, "--merge", "--delete-branch")
            if code == 0:
                print(f"MERGED PR#{pr} ({fname})")
                send_mail(f"【公開完了】{fname}",
                          f"「OK」の返信を確認したため、記事を公開しました。\n"
                          f"数分後に https://www.minnnanoyakuzaishi.com/{fname} で確認できます。\n\n"
                          f"※Search Console での「インデックス登録をリクエスト」もお忘れなく。")
                handled += 1
            else:
                print(f"MERGE FAILED PR#{pr}: {err}")
                send_mail(f"【要確認】公開に失敗しました: {fname}",
                          f"自動公開(Merge)に失敗しました。GitHubのPRを直接ご確認ください。\n{err[:500]}")
        else:
            code, out, err = gh("pr", "close", str(pr), "--repo", REPO, "--delete-branch")
            if code == 0:
                print(f"CLOSED PR#{pr} ({fname})")
                send_mail(f"【破棄しました】{fname}",
                          "「NG」の返信を確認したため、この記事は公開せず破棄しました。\n"
                          "同じテーマを作り直したい場合は、pipeline/keywords.csv の該当行の status を pending に戻してください。")
                handled += 1
    M.logout()
    print(f"done. handled={handled}")


if __name__ == "__main__":
    main()
