import sys
import json
import os
import logging
from dotenv import load_dotenv
from unicodedata import normalize
# from openai import OpenAI
from openai import AzureOpenAI
from playwright.sync_api import sync_playwright
from pathlib import Path
from urllib.parse import urljoin

# if os.getenv("OPENAI_API_KEY") is None:
#     from dotenv import load_dotenv
#     dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
#     load_dotenv(dotenv_path)

# ✅ まず dotenv_path を定義
dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
load_dotenv(dotenv_path)

# ログ設定
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
logger.info(f"[DEBUG] .env path = {dotenv_path}")
logger.info(f"[DEBUG] OPENAI_API_KEY = {os.getenv('OPENAI_API_KEY')[:8]}...")

# client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
client = AzureOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    api_version=os.getenv("OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("OPENAI_API_BASE")
)

# ChatGPTが出力する英語カテゴリとCOSCOの日本語PDF名の対応表
region_map = {
    # 洋主要基幹航路
    "AMERICA CANADA": "アメリカ・カナダサービス",
    "AUSTRALIA": "オーストラリアサービス",
    "NEW ZEALAND": "ニュージーランドサービス",
    "EUROPE": "ヨーロッパサービス",
    "MEDITERRANEAN": "地中海サービス",
    "RED SEA": "紅海サービス",
    "MIDDLE EAST": "中近東サービス",
    "SOUTH AMERICA": "南米東岸・西岸サービス",
    "AFRICA": "アフリカサービス",

    # 東南アジア・南アジア
    "KOREA": "韓国（釜山）向けサービス",
    "SOUTH EAST ASIA": "タイ・ベトナム向け直行サービス",
    "MALAYSIA SINGAPORE INDONESIA": "シンガポール・マレーシア・インドネシア向け直行サービス",
    "SOUTH ASIA": "インド・スリランカ向けサービス／上海経由",

    # 中国・台湾
    "CHINA FEEDER": "上海・長江流域フィーダーサービス",
    "NINGBO WENZHOU": "寧波・温州サービス",
    "QINGDAO LIANYUNGANG": "青島・連雲港サービス",
    "XINGANG DALIAN YINGKOU": "新港・大連・営口・威海サービス",
    "HONGKONG PEARL": "香港・南中国及びパールリバーデルタフィーダーサービス",
    "TAIWAN": "台湾サービス（KTX1 / KTX3）"
}

def get_region_by_chatgpt(destination_keyword: str, silent=False):
    prompt = f"""
あなたは国際物流に詳しいアシスタントです。

以下の目的地「{destination_keyword}」が、COSCO社スケジュールページ（https://world.lines.coscoshipping.com/japan/jp/services/localschedule/1/1）の**輸出**欄に掲載されているカテゴリのうち、どれに該当するかを判断してください。

次のリストから最も適切なカテゴリを1つ選び、**その英語キー（大文字）だけを1行で出力**してください。説明や記号は不要です。

["AMERICA CANADA", "AUSTRALIA", "NEW ZEALAND", "EUROPE", "MEDITERRANEAN", "RED SEA", "MIDDLE EAST", "SOUTH AMERICA", "AFRICA", "KOREA", "SOUTH EAST ASIA", "MALAYSIA SINGAPORE INDONESIA", "SOUTH ASIA", "CHINA FEEDER", "NINGBO WENZHOU", "QINGDAO LIANYUNGANG", "XINGANG DALIAN YINGKOU", "HONGKONG PEARL", "TAIWAN"]
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        result = response.choices[0].message.content.strip().upper().strip('"')

        if not silent:
            logger.info(f"[ChatGPT返答] {result}")

        if result not in region_map:
            raise ValueError(f"ChatGPTの返答が不正です: {result}")

        return region_map[result]
    
    except Exception as e:
        logger.exception("[ERROR] ChatGPTによる地域判定失敗")
        raise

    # result = response.choices[0].message.content.strip()
    # logger.info(f"[ChatGPT日本語カテゴリ名 判定結果] → '{result}'")

    # return result

def normalize_text(s: str) -> str:
    """ 文字列を正規化して空白を削除 """
    if not s:
        return ""
    return "".join(s.split()).lower()

def get_pdf_links(destination_keyword, silent=False):
    pdf_links = []
    region_jp = get_region_by_chatgpt(destination_keyword, silent=silent)

    # def normalize_text(s):
    #     return normalize('NFKC', s).replace(' ', '').replace('　', '').lower()

    if not silent:
        logger.info(f"[INFO] ChatGPTにより得られた日本語カテゴリ名: {region_jp}")

    base_url = "https://world.lines.coscoshipping.com"
    target_url = "https://world.lines.coscoshipping.com/japan/jp/services/localschedule/1/1"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        # User-Agent 設定
        page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"
        })

        page.goto(target_url, timeout=60000)

        # JavaScriptの完了待機 - PDFリンクがレンダリングされるまで待機
        try:
            logger.info("[INFO] PDFリンクのレンダリング待機中...")
            page.wait_for_function(
                """() => {
                    return document.querySelectorAll("a[href$='.pdf']").length > 0;
                }""",
                timeout=15000
            )
        except Exception as e:
            logger.warning("[WARNING] PDFリンクのレンダリング待機に失敗しました。")

        # リンク取得
        links = page.query_selector_all("a")
        logger.info(f"[INFO] リンク数: {len(links)}")

        for link in links:
            href = link.get_attribute("href")
            text = link.text_content()
        
            # ✅ デバッグ用ログ出力
            logger.info(f"[DEBUG] href: {href}, text: '{text}'")

            # 空白および改行を削除して正規化
            normalized_text = normalize_text(text)
            normalized_region = normalize_text(region_jp)

            # ✅ hrefがNoneでないことを確認してから処理を続行
            if href and href.endswith(".pdf"):
                # 相対URLを絶対URLに変換
                full_url = urljoin(base_url, href)

                # ✅ 「輸出」または「exp」を含むリンクのみ対象
                if (
                    ("輸出" in normalized_text or "exp" in href.lower()) and
                    normalized_region in normalized_text
                ):
                    pdf_links.append(full_url)
                    logger.info(f"[MATCH] {text} → {full_url}")

        browser.close()

    return pdf_links


if __name__ == "__main__":
    try:
        if len(sys.argv) < 2:
            logger.error("❌ 実行引数が不足しています。使用例: `python get_cosco_pdf_links.py Los Angeles`")
            print("[]")
            sys.exit(1)

        keyword = sys.argv[1]
        silent = "--silent" in sys.argv

        result = get_pdf_links(keyword, silent=silent)
        print(json.dumps(result, ensure_ascii=False))  # subprocess用出力

    except Exception as e:
        logger.exception("[ERROR] get_cosco_pdf_links実行中に例外:")
        print("[]")  # subprocess 側で json.loads に失敗させないため
        sys.exit(1)


# BeautifulSoup版のコード（予備）

# import sys
# import json
# import os
# import logging
# from dotenv import load_dotenv
# from unicodedata import normalize
# from pathlib import Path
# import requests
# from bs4 import BeautifulSoup
# from openai import OpenAI

# # .env 読み込み
# dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
# load_dotenv(dotenv_path)

# # ログ設定
# logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
# logger = logging.getLogger(__name__)
# logger.info(f"[DEBUG] .env path = {dotenv_path}")
# logger.info(f"[DEBUG] OPENAI_API_KEY = {os.getenv('OPENAI_API_KEY')[:8]}...")

# # OpenAIクライアント
# client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# region_map = {
#     # 洋主要基幹航路
#     "AMERICA CANADA": "アメリカ・カナダサービス",
#     "AUSTRALIA": "オーストラリアサービス",
#     "NEW ZEALAND": "ニュージーランドサービス",
#     "EUROPE": "ヨーロッパサービス",
#     "MEDITERRANEAN": "地中海サービス",
#     "RED SEA": "紅海サービス",
#     "MIDDLE EAST": "中東サービス",
#     "SOUTH AMERICA": "南米東岸・西岸サービス",
#     "AFRICA": "アフリカサービス",

#     # 東南アジア・南アジア
#     "KOREA": "韓国（釜山）向けサービス",
#     "SOUTH EAST ASIA": "タイ・ベトナム向け直行サービス",
#     "MALAYSIA SINGAPORE INDONESIA": "シンガポール・マレーシア・インドネシア直行サービス",
#     "SOUTH ASIA": "インド・スリランカ向けサービス（上海経由）",

#     # 中国・台湾
#     "CHINA FEEDER": "長江流域フィーダーサービス",
#     "NINGBO WENZHOU": "寧波・温州サービス",
#     "QINGDAO LIANYUNGANG": "青島・連雲港サービス",
#     "XINGANG DALIAN YINGKOU": "新港・大連・営口・威海サービス",
#     "HONGKONG PEARL": "香港・南中国パールリバーサービス",
#     "TAIWAN": "台湾サービス（KTX1 / KTX3）"
# }

# def get_region_by_chatgpt(destination_keyword: str, silent=False):
#     prompt = f"""
# # あなたは国際物流に詳しいアシスタントです。

# # 以下の目的地「{destination_keyword}」が、COSCO社スケジュールページ（https://world.lines.coscoshipping.com/japan/jp/services/localschedule/1/1）の**輸出**欄に掲載されているカテゴリのうち、どれに該当するかを判断してください。

# # 次のリストから最も適切なカテゴリを1つ選び、**その英語キー（大文字）だけを1行で出力**してください。説明や記号は不要です。

# # ["AMERICA CANADA", "AUSTRALIA", "NEW ZEALAND", "EUROPE", "MEDITERRANEAN", "RED SEA", "MIDDLE EAST", "SOUTH AMERICA", "AFRICA", "KOREA", "SOUTH EAST ASIA", "MALAYSIA SINGAPORE INDONESIA", "SOUTH ASIA", "CHINA FEEDER", "NINGBO WENZHOU", "QINGDAO LIANYUNGANG", "XINGANG DALIAN YINGKOU", "HONGKONG PEARL", "TAIWAN"]
# """

#     try:
#         response = client.chat.completions.create(
#             model="gpt-4o",
#             messages=[{"role": "user", "content": prompt}],
#             temperature=0
#         )
#         result = response.choices[0].message.content.strip().upper()

#         if not silent:
#             logger.info(f"[ChatGPT返答] {result}")

#         if result not in region_map:
#             raise ValueError(f"ChatGPTの返答が不正です: {result}")

#         return region_map[result]

#     except Exception as e:
#         logger.exception("[ERROR] ChatGPTによる地域判定失敗")
#         raise

# def normalize_text(s: str) -> str:
#     return normalize('NFKC', s).replace(' ', '').replace('　', '').lower()

# def get_pdf_links(destination_keyword, silent=False):
#     pdf_links = []
#     region_jp = get_region_by_chatgpt(destination_keyword, silent=silent)

#     if not silent:
#         logger.info(f"[INFO] ChatGPTにより得られた日本語カテゴリ名: {region_jp}")

#     url = "https://world.lines.coscoshipping.com/japan/jp/services/localschedule/1/1"
#     headers = {"User-Agent": "Mozilla/5.0"}

#     try:
#         response = requests.get(url, headers=headers, timeout=10)
#         response.raise_for_status()
#     except Exception as e:
#         logger.exception("[ERROR] requests.get に失敗しました")
#         raise

#     # ✅ レスポンスHTMLをデバッグ用に保存
#     with open("cosco_debug.html", "wb") as f:
#         f.write(response.content)
#         logger.info("[DEBUG] COSCOページHTMLを cosco_debug.html に保存しました")

#     soup = BeautifulSoup(response.content, "html.parser")
#     links = soup.find_all("a", href=True)

#     for link in links:
#         text = link.get_text(strip=True)
#         href = link["href"]

#         # if (
#         #     href.endswith(".pdf")
#         #     and ("輸出" in text or "exp" in href.lower())
#         #     and normalize_text(region_jp) in normalize_text(text)
#         # ):
#         #     full_url = f"https://world.lines.coscoshipping.com{href}" if href.startswith("/") else href
#         #     pdf_links.append(full_url)
#         #     if not silent:
#         #         logger.info(f"[MATCH] {text} → {full_url}")

#         # if href.endswith(".pdf"):
#         #     full_url = f"https://world.lines.coscoshipping.com{href}" if href.startswith("/") else href
#         #     logger.info(f"[DEBUG MATCH] {text} → {full_url}")
#         #     pdf_links.append(full_url)
#         logger.debug(f"[候補] text: {text}, href: {href}")
#         logger.debug(f"[比較] region='{normalize_text(region_jp)}' in '{normalize_text(text)}'")
        
#         if href.endswith(".pdf"):
#             full_url = f"https://world.lines.coscoshipping.com{href}" if href.startswith("/") else href
#             logger.info(f"[全PDF候補] {text} → {full_url}")
#             pdf_links.append(full_url)

#     return pdf_links

# if __name__ == "__main__":
#     try:
#         if len(sys.argv) < 2:
#             logger.error("❌ 実行引数が不足しています。使用例: python get_cosco_pdf_links.py Los Angeles")
#             print("[]")
#             sys.exit(1)

#         keyword = sys.argv[1]
#         silent = "--silent" in sys.argv

#         result = get_pdf_links(keyword, silent=silent)
#         print(json.dumps(result, ensure_ascii=False))  # subprocess用出力

#     except Exception as e:
#         logger.exception("[ERROR] get_cosco_pdf_links実行中に例外:")
#         print("[]")
#         sys.exit(1)