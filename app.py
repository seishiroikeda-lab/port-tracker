from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request

app = Flask(__name__)

# 北九州港湾WEBシステムの実URL
BASE_URL = "http://www.kitaqport.or.jp/HTML1000/PROC2004.asp"


def fetch_day_records(target_date: datetime):
    """
    指定した日付で PROC2004.asp に対して POST し、
    その日の入出港データをレコード(list[dict])として返す。
    """
    payload = {
        "kikan_nen1": target_date.strftime("%Y"),  # 年
        "kikan_tuki1": target_date.strftime("%m"),  # 月（ゼロ埋め）
        "kikan_hi1": target_date.strftime("%d"),    # 日（ゼロ埋め）
        "commit": "照会",
    }

    # User-Agent にツール名と連絡先を明記
    headers = {
        "User-Agent": "KitaQPortChecker/1.0 (+seishiroikeda@gmail.com)",
        "Referer": BASE_URL,
    }

    resp = requests.post(BASE_URL, data=payload, headers=headers, timeout=15)

    # 古い日本語サイト想定：エンコーディングを補正
    if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "latin-1"):
        resp.encoding = "cp932"  # Shift_JIS 系を想定

    html = resp.text
    return parse_records_from_html(html, target_date)


def parse_records_from_html(html: str, target_date: datetime):
    """
    HTML からテーブルをパースして、レコード(list[dict])を返す。
    想定カラム：
      岸壁 / ビット / 着岸日時 / 離岸日時 / 状態 / ｺｰﾙｻｲﾝ /
      船名 / 総ﾄﾝ数(gt) / 全長(m) / 船種 / 船籍 / 前港 / 次港 / 申請者
    ※ 実際のテーブル構造が違う場合は、この関数内のインデックスを調整する。
    """
    soup = BeautifulSoup(html, "html.parser")

    # ページ内で最初に出てくる table をターゲットにする想定
    # 必要に応じて soup.find_all("table")[n] に変更
    table = soup.find("table")
    if not table:
        return []

    records = []
    rows = table.find_all("tr")

    # 1 行目がヘッダ行である前提でスキップ
    for row in rows[1:]:
        cols = row.find_all(["td", "th"])
        # カラム数が足りない行はスキップ
        if len(cols) < 13:
            continue

        values = [c.get_text(strip=True) for c in cols]

        # 必要に応じてインデックス調整
        record = {
            "date": target_date.strftime("%Y-%m-%d"),
            "ganpeki": values[0],      # 岸壁
            "bit": values[1],          # ビット
            "chakugan": values[2],     # 着岸日時
            "rigan": values[3],        # 離岸日時
            "status": values[4],       # 状態
            "callsign": values[5],     # ｺｰﾙｻｲﾝ
            "ship_name": values[6],    # 船名
            "gross_ton": values[7],    # 総ﾄﾝ数(gt)
            "length_m": values[8],     # 全長(m)
            "ship_type": values[9],    # 船種
            "flag": values[10],        # 船籍
            "prev_port": values[11],   # 前港
            "next_port": values[12],   # 次港
        }

        # 13列目以降に申請者がある想定
        record["applicant"] = values[13] if len(values) > 13 else ""

        records.append(record)

    return records


def match_ship(ship_name: str, keyword: str) -> bool:
    """
    船名が、入力されたキーワードを含んでいるかどうか（部分一致）。
    """
    if not ship_name or not keyword:
        return False

    s = ship_name.strip()
    k = keyword.strip()

    # 単純な部分一致（必要なら大文字小文字・全角半角の正規化を追加）
    return k in s


@app.route("/", methods=["GET", "POST"])
def index():
    results = []
    ship_keyword = ""
    start_date = None
    end_date = None

    if request.method == "POST":
        ship_keyword = request.form.get("ship_name", "").strip()

        if ship_keyword:
            # 今日を基準日とする（サーバのローカルタイム）
            base_date = datetime.today()
            start_date = base_date.date()
            end_date = (base_date + timedelta(days=13)).date()  # 今日含めて14日間

            # 今日から 14 日分をループ
            for offset in range(14):
                day = base_date + timedelta(days=offset)
                day_records = fetch_day_records(day)

                # 船名でフィルタ
                for rec in day_records:
                    if match_ship(rec["ship_name"], ship_keyword):
                        results.append(rec)

            # まず船名 → 日付 → 着岸日時の順でソート
            results.sort(key=lambda r: (r["ship_name"], r["date"], r["chakugan"]))

            # 同一船名を 1 件に統合（最も早いレコードだけ残す）
            unique_results = []
            seen_ships = set()

            for rec in results:
                name = rec["ship_name"]
                if name in seen_ships:
                    continue
                seen_ships.add(name)
                unique_results.append(rec)

            results = unique_results

    return render_template(
        "index.html",
        results=results,
        ship_keyword=ship_keyword,
        start_date=start_date,
        end_date=end_date,
    )


if __name__ == "__main__":
    # 開発用サーバー起動
    # 本番環境では gunicorn 等の WSGI サーバー経由で動かす想定
    app.run(debug=True)
