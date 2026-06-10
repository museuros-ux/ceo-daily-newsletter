import os
import json
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from google import genai
from google.genai import types

NAVER_CLIENT_ID = os.environ['NAVER_CLIENT_ID']
NAVER_CLIENT_SECRET = os.environ['NAVER_CLIENT_SECRET']
GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
GMAIL_ADDRESS = os.environ['GMAIL_ADDRESS']
GMAIL_APP_PASSWORD = os.environ['GMAIL_APP_PASSWORD']
RECIPIENT_EMAILS = os.environ['RECIPIENT_EMAILS'].split(',')

NEARBY_ORGS = ["안양도시공사", "군포도시공사", "시흥도시공사", "안산도시공사", "과천도시공사", "광명도시공사", "용인도시공사"]

CATEGORIES = {
    "의왕시 동향": ["의왕시"],
    "지방공사·공단 동향": ["도시공사", "지방공사", "지방공단", "지방공기업", "시설관리공단"],
    "경영평가 동향": ["경영평가"],
    "개발 동향": ["도시개발", "도시재생", "택지개발", "재개발", "재건축"],
    "CEO 동향": ["시설공단 이사장", "지방공기업 대표"],
}

SECONDARY_FILTER = {
    "경영평가 동향": ["공기업", "지방공사", "지방공단", "도시공사", "시설공단", "공단", "공사"],
}

def get_date_range():
    today = datetime.utcnow() + timedelta(hours=9)
    weekday = today.weekday()
    if weekday == 0:
        start = today - timedelta(days=3)
        end = today - timedelta(days=1)
    else:
        start = today - timedelta(days=1)
        end = today - timedelta(days=1)
    return start.replace(hour=0, minute=0, second=0), end.replace(hour=23, minute=59, second=59)

def parse_naver_date(date_str):
    try:
        return datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S +0900")
    except:
        return None

def search_naver_news(query, start_date, end_date, display=100):
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    params = {"query": query, "display": display, "sort": "date"}
    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        items = res.json().get('items', [])
    except:
        return []
    filtered = []
    for item in items:
        pub_date = parse_naver_date(item.get('pubDate', ''))
        if pub_date and start_date <= pub_date <= end_date:
            filtered.append({
                "title": item['title'].replace('<b>', '').replace('</b>', ''),
                "description": item['description'].replace('<b>', '').replace('</b>', ''),
                "link": item['link'],
                "pubDate": item['pubDate']
            })
    return filtered

def collect_nearby_org_news(start_date, end_date):
    articles = []
    seen_titles = set()
    for org in NEARBY_ORGS:
        items = search_naver_news(org, start_date, end_date)
        for item in items:
            if item['title'] not in seen_titles:
                if org in item['title']:
                    seen_titles.add(item['title'])
                    articles.append(item)
    return articles

def collect_news(start_date, end_date):
    results = {}
    for category, keywords in CATEGORIES.items():
        articles = []
        seen_titles = set()
        for kw in keywords:
            items = search_naver_news(kw, start_date, end_date)
            for item in items:
                if item['title'] not in seen_titles:
                    title = item['title']
                    desc = item['description']
                    combined = title + desc

                    # 지방공사·공단: 인근 도시공사 7개 제외
                    if category == "지방공사·공단 동향":
                        if any(org in combined for org in NEARBY_ORGS):
                            continue

                    # 경영평가: 2차 필터
                    if category == "경영평가 동향":
                        if not any(f in combined for f in SECONDARY_FILTER["경영평가 동향"]):
                            continue

                    seen_titles.add(title)
                    articles.append(item)
        results[category] = articles
    return results

def build_news_text(news_data):
    news_text = ""
    for category, articles in news_data.items():
        news_text += f"\n## {category}\n"
        if not articles:
            news_text += "- 해당 기간 기사 없음\n"
        else:
            for a in articles[:20]:
                news_text += "- 제목: " + a['title'] + " | 설명: " + a['description'] + " | 링크: " + a['link'] + "\n"
    return news_text

def build_nearby_news_text(articles):
    if not articles:
        return "- 해당 기간 기사 없음\n"
    news_text = ""
    for a in articles[:30]:
        news_text += "- 제목: " + a['title'] + " | 설명: " + a['description'] + " | 링크: " + a['link'] + "\n"
    return news_text

def call_gemini_json(prompt, retries=3):
    import time
    client = genai.Client(api_key=GEMINI_API_KEY)
    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model='gemini-3.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                )
            )
            return json.loads(response.text)
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(10)
            else:
                raise e

def get_nearby_json(nearby_articles, date_label):
    news_text = build_nearby_news_text(nearby_articles)
    prompt = (
        f"아래는 {date_label} 수집된 인근 도시공사 보도자료입니다 (제목|설명|링크 형식):\n"
        + news_text
        + "\n\n아래 JSON 형식으로만 응답하세요. JSON 외 다른 텍스트 절대 금지.\n\n"
        "{\n"
        '  "인근도시공사": [\n'
        '    {"기관명": "안양도시공사", "제목요약": "주체, 핵심내용 형태로 20자 내외 요약", "동향": ["꼭지1", "꼭지2"], "출처": [{"제목": "기사제목", "링크": "기사링크"}]}\n'
        "  ]\n"
        "}\n\n"
        "작성 기준:\n"
        "- 동일한 사건을 다룬 중복 기사는 하나로 병합. 출처 배열에 관련 링크 최대 3개까지 포함\n"
        "- 각 동향은 2~3개 꼭지로 개조식 작성. 특수기호 사용 금지\n"
        "- 각 꼭지는 명사형 또는 단문으로 끝낼 것. 서술식 금지\n"
        "- 기관명은 정확하게 표기\n"
        "- 제목요약: 반드시 주체(기관명, 지자체명 등)를 원문 그대로 정확하게 포함하여 '주체, 핵심내용' 형태로 20자 내외로 요약. 기관명 임의 축약 금지\n"
        "- 원문에 없는 내용 절대 생성 금지\n"
        "- 관련 기사 없으면 빈 배열 []\n"
        "JSON만 출력. 다른 텍스트 없음."
    )
    return call_gemini_json(prompt)

def get_insight_json(news_data, date_label):
    news_text = build_news_text(news_data)
    prompt = (
        "당신은 뉴스 분석 AI입니다.\n\n"
        f"아래는 {date_label} 수집된 보도자료입니다 (제목|설명|링크 형식):\n"
        + news_text
        + "\n\n아래 JSON 형식으로만 응답하세요. JSON 외 다른 텍스트 절대 금지.\n\n"
        "{\n"
        '  "의왕시 동향": [\n'
        '    {"제목요약": "주체, 핵심내용 형태로 20자 내외 요약", "동향": ["꼭지1", "꼭지2"], "출처": [{"제목": "기사제목", "링크": "기사링크"}]}\n'
        "  ],\n"
        '  "지방공사·공단 동향": [\n'
        '    {"제목요약": "주체, 핵심내용 형태로 20자 내외 요약", "동향": ["꼭지1", "꼭지2"], "출처": [{"제목": "기사제목", "링크": "기사링크"}]}\n'
        "  ],\n"
        '  "경영평가 동향": [\n'
        '    {"제목요약": "주체, 핵심내용 형태로 20자 내외 요약", "동향": ["꼭지1", "꼭지2"], "출처": [{"제목": "기사제목", "링크": "기사링크"}]}\n'
        "  ],\n"
        '  "개발 동향": [\n'
        '    {"제목요약": "주체, 핵심내용 형태로 20자 내외 요약", "동향": ["꼭지1", "꼭지2"], "출처": [{"제목": "기사제목", "링크": "기사링크"}]}\n'
        "  ],\n"
        '  "CEO 동향": [\n'
        '    {"제목요약": "주체, 핵심내용 형태로 20자 내외 요약", "동향": ["꼭지1", "꼭지2"], "출처": [{"제목": "기사제목", "링크": "기사링크"}]}\n'
        "  ]\n"
        "}\n\n"
        "작성 기준:\n"
        "- 수집된 기사가 있으면 반드시 해당 카테고리에 포함할 것. 임의로 제외하지 말 것\n"
        "- 동일한 사건·정책을 다룬 중복 기사는 하나로 병합하여 동향 1개로만 작성\n"
        "- 병합 시 관련 기사 링크를 출처 배열에 최대 3개까지 포함\n"
        "- 완전히 다른 독립적인 이슈만 별개 동향으로 분리할 것\n"
        "- 제목요약: 반드시 주체(기관명, 지자체명 등)를 원문 그대로 정확하게 포함하여 '주체, 핵심내용' 형태로 20자 내외로 요약. 기관명 임의 축약 금지\n"
        "- 각 동향은 기사 내용을 2~3개 꼭지로 나눠 개조식으로 작성. 특수기호(○ 등) 사용 금지\n"
        "- 각 꼭지는 명사형 또는 단문으로 끝낼 것. 서술식 금지\n"
        "- 지방공사·공단 동향: 무연고자 장례·복지 서비스 등 본연 업무와 무관한 기사 제외\n"
        "- 관련 기사 없으면 빈 배열 []\n"
        "- 출처 제목과 링크는 반드시 원문에 실제로 존재하는 기사만\n"
        "- 원문에 없는 내용 절대 생성 금지\n"
        "JSON만 출력. 다른 텍스트 없음."
    )
    return call_gemini_json(prompt)

def build_html(nearby_json, insight_json, date_label):
    category_icons = {
        "의왕시 동향": "🏙️",
        "인근 도시공사 동향": "🏢",
        "지방공사·공단 동향": "🏛️",
        "경영평가 동향": "📊",
        "개발 동향": "🏗️",
        "CEO 동향": "👔",
    }

    def render_articles(category, articles):
        html = ""
        if not articles:
            return "<div style='color:#999;font-style:italic;padding:6px 0;'>해당일 관련 기사 없음</div>"
        for j, item in enumerate(articles, 1):
            org_name = item.get('기관명', '')
            title_summary = item.get('제목요약', '')
            dong_list = item.get('동향', [])
            sources = item.get('출처', [])[:3]

            dong_html = "".join(
                "<li style='margin:4px 0;line-height:1.7;color:#333;'>" + d + "</li>"
                for d in dong_list
            )

            source_html = ""
            if sources:
                source_items = "".join(
                    "<div style='margin:3px 0;'>"
                    "<a href='" + s['링크'] + "' style='color:#2c5f9e;font-size:12px;'>📎 " + s['제목'] + "</a>"
                    "</div>"
                    for s in sources if s.get('링크')
                )
                if source_items:
                    source_html = "<div style='margin-top:6px;'>출처:<br>" + source_items + "</div>"

            if org_name:
                header = "[" + org_name + "] " + str(j) + ". " + title_summary
            else:
                header = category + " " + str(j) + ". " + title_summary

            html += (
                "<div style='border:1px solid #e0e0e0;border-radius:6px;padding:12px 16px;"
                "margin-bottom:12px;background:#fafafa;'>"
                "<div style='font-weight:bold;color:#1a3a6b;margin-bottom:8px;'>"
                + header +
                "</div>"
                "<ul style='margin:4px 0 8px 0;padding-left:18px;'>" + dong_html + "</ul>"
                + source_html +
                "</div>"
            )
        return html

    content_html = ""
    num = 1

    content_html += (
        "<div style='margin-top:30px;'>"
        "<div style='font-size:15px;font-weight:bold;color:white;background:#1a3a6b;"
        "padding:7px 14px;border-radius:6px;margin-bottom:12px;'>"
        "🏙️ " + str(num) + ". 의왕시 동향</div>"
    )
    content_html += render_articles("의왕시 동향", insight_json.get("의왕시 동향", []))
    content_html += "</div>"
    num += 1

    content_html += (
        "<div style='margin-top:30px;'>"
        "<div style='font-size:15px;font-weight:bold;color:white;background:#1a3a6b;"
        "padding:7px 14px;border-radius:6px;margin-bottom:12px;'>"
        "🏢 " + str(num) + ". 인근 도시공사 동향</div>"
    )
    content_html += render_articles("인근 도시공사 동향", nearby_json.get("인근도시공사", []))
    content_html += "</div>"
    num += 1

    remaining = ["지방공사·공단 동향", "경영평가 동향", "개발 동향", "CEO 동향"]
    for category in remaining:
        icon = category_icons.get(category, "📌")
        content_html += (
            "<div style='margin-top:30px;'>"
            "<div style='font-size:15px;font-weight:bold;color:white;background:#1a3a6b;"
            "padding:7px 14px;border-radius:6px;margin-bottom:12px;'>"
            + icon + " " + str(num) + ". " + category + "</div>"
        )
        content_html += render_articles(category, insight_json.get(category, []))
        content_html += "</div>"
        num += 1

    html = (
        "<!DOCTYPE html><html lang='ko'><head><meta charset='UTF-8'></head>"
        "<body style='font-family:Malgun Gothic,Arial,sans-serif;font-size:14px;"
        "color:#333;max-width:800px;margin:0 auto;padding:20px;'>"
        "<div style='background:#fff3cd;border-left:4px solid #ffc107;"
        "padding:10px 15px;margin-bottom:25px;border-radius:4px;"
        "font-size:13px;color:#856404;'>"
        "⚠ 본 뉴스레터는 AI(Gemini)가 자동으로 수집·분석하여 작성한 내용입니다. "
        "기사 선별 과정에서 오류가 있을 수 있으니 참고자료로 활용하시기 바랍니다."
        "</div>"
        "<h1 style='font-size:22px;color:#1a3a6b;border-bottom:3px solid #1a3a6b;"
        "padding-bottom:10px;margin-bottom:5px;text-align:center;'>"
        "🏢 의왕도시공사 CEO 데일리 뉴스레터"
        "</h1>"
        "<div style='text-align:center;color:#666;font-size:13px;margin-bottom:30px;'>"
        + date_label +
        "</div>"
        + content_html +
        "</body></html>"
    )
    return html

def send_email(subject, html_content):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = GMAIL_ADDRESS
    msg['To'] = ', '.join(RECIPIENT_EMAILS)
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, RECIPIENT_EMAILS, msg.as_string())

def main():
    today = datetime.utcnow() + timedelta(hours=9)
    weekday = today.weekday()
    start_date, end_date = get_date_range()

    if weekday == 0:
        date_label = (
            (today - timedelta(days=3)).strftime('%m.%d') + "(금) ~ "
            + (today - timedelta(days=1)).strftime('%m.%d') + "(일)"
        )
    else:
        yesterday = today - timedelta(days=1)
        date_label = yesterday.strftime('%m.%d(%a)')

    nearby_articles = collect_nearby_org_news(start_date, end_date)
    news_data = collect_news(start_date, end_date)
    nearby_json = get_nearby_json(nearby_articles, date_label)
    insight_json = get_insight_json(news_data, date_label)
    html_content = build_html(nearby_json, insight_json, date_label)
    subject = "의왕도시공사 CEO 데일리 뉴스레터(" + today.strftime('%Y.%m.%d.') + ")"
    send_email(subject, html_content)
    print("발송 완료")

if __name__ == "__main__":
    main()
