import os
import json
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta

NAVER_CLIENT_ID = os.environ['NAVER_CLIENT_ID']
NAVER_CLIENT_SECRET = os.environ['NAVER_CLIENT_SECRET']
GMAIL_ADDRESS = os.environ['GMAIL_ADDRESS']
GMAIL_APP_PASSWORD = os.environ['GMAIL_APP_PASSWORD']
RECIPIENT_EMAILS = os.environ['RECIPIENT_EMAILS'].split(',')

CATEGORIES = {
    "의왕시 동향": ["의왕시"],
    "지방공사·공단 동향": ["도시공사", "시설관리공단"],
    "경영평가 동향": ["경영평가"],
    "개발사업 동향": ["개발사업"],
    "CEO 동향": ["사장", "CEO"],
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
                "link": item['link'],
                "pubDate": item['pubDate']
            })
    return filtered

def collect_news(start_date, end_date):
    results = {}
    for category, keywords in CATEGORIES.items():
        articles = []
        seen_titles = set()
        for kw in keywords:
            items = search_naver_news(kw, start_date, end_date)
            for item in items:
                if item['title'] not in seen_titles:
                    if kw in item['title']:
                        seen_titles.add(item['title'])
                        articles.append(item)
        results[category] = articles
    return results

def build_html(news_data, date_label):
    category_icons = {
        "의왕시 동향": "🏙️",
        "지방공사·공단 동향": "🏛️",
        "경영평가 동향": "📊",
        "개발사업 동향": "🏗️",
        "CEO 동향": "👔",
    }

    content_html = ""
    for i, (category, articles) in enumerate(news_data.items(), 1):
        icon = category_icons.get(category, "📌")
        content_html += (
            "<div style='margin-top:30px;'>"
            "<div style='font-size:15px;font-weight:bold;color:white;background:#1a3a6b;"
            "padding:7px 14px;border-radius:6px;margin-bottom:12px;'>"
            + icon + " " + str(i) + ". " + category +
            "</div>"
        )
        if not articles:
            content_html += "<div style='color:#999;font-style:italic;padding:6px 0;'>해당일 관련 기사 없음</div>"
        else:
            for art in articles:
                content_html += (
                    "<div style='border:1px solid #e0e0e0;border-radius:6px;padding:10px 16px;"
                    "margin-bottom:8px;background:#fafafa;'>"
                    "<a href='" + art['link'] + "' style='color:#1a3a6b;font-weight:bold;"
                    "text-decoration:none;font-size:14px;line-height:1.6;'>"
                    + art['title'] +
                    "</a>"
                    "</div>"
                )
        content_html += "</div>"

    html = (
        "<!DOCTYPE html><html lang='ko'><head><meta charset='UTF-8'></head>"
        "<body style='font-family:Malgun Gothic,Arial,sans-serif;font-size:14px;"
        "color:#333;max-width:800px;margin:0 auto;padding:20px;'>"
        "<div style='background:#fff3cd;border-left:4px solid #ffc107;"
        "padding:10px 15px;margin-bottom:25px;border-radius:4px;"
        "font-size:13px;color:#856404;'>"
        "⚠ 본 뉴스레터는 네이버 뉴스에서 자동으로 수집한 기사 목록입니다. "
        "참고자료로 활용하시기 바랍니다."
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

    news_data = collect_news(start_date, end_date)
    html_content = build_html(news_data, date_label)
    subject = "의왕도시공사 CEO 데일리 뉴스레터(" + today.strftime('%Y.%m.%d.') + ")"
    send_email(subject, html_content)
    print("발송 완료")

if __name__ == "__main__":
    main()
