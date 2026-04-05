"""
Germanistik 学术追踪 — 期刊爬虫
目标期刊：
  1. 《德语人文研究》 - 湖南师范大学 / 知网目录页
  2. 《德国研究》     - 同济大学德国研究中心
  3. 《德文月刊》     - 德语国家研究方向

运行方式：python scrape_journals.py
输出：data/papers_raw.json（追加模式，去重）
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import hashlib
import os
import re
from datetime import datetime
from pathlib import Path

# ── 配置 ────────────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
RAW_FILE = DATA_DIR / "papers_raw.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 礼貌爬取间隔（秒）
CRAWL_DELAY = 3


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def paper_id(title: str, journal: str, year: int) -> str:
    """生成论文唯一ID，用于去重"""
    raw = f"{title}|{journal}|{year}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def load_existing() -> dict:
    """读取已有数据，返回 {id: paper} 字典"""
    if RAW_FILE.exists():
        with open(RAW_FILE, "r", encoding="utf-8") as f:
            papers = json.load(f)
        return {p["id"]: p for p in papers}
    return {}


def save_all(papers: dict):
    """保存全部论文（按日期倒序）"""
    sorted_list = sorted(
        papers.values(),
        key=lambda p: (p.get("year", 0), p.get("issue_num", 0)),
        reverse=True
    )
    with open(RAW_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted_list, f, ensure_ascii=False, indent=2)
    print(f"[保存] 共 {len(sorted_list)} 篇论文 → {RAW_FILE}")


def get_page(url: str) -> BeautifulSoup | None:
    """安全获取页面"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = resp.apparent_encoding
        if resp.status_code == 200:
            return BeautifulSoup(resp.text, "html.parser")
        print(f"[警告] {url} 返回 {resp.status_code}")
    except Exception as e:
        print(f"[错误] {url}: {e}")
    return None


# ── 爬虫 1：《德语人文研究》───────────────────────────────────────────────────
# 知网期刊目录页（公开摘要）
# URL 模式：https://navi.cnki.net/knavi/journals/YYYY_issue

def scrape_dyrwj(existing: dict, max_issues: int = 6) -> list:
    """
    《德语人文研究》
    CN 43-1412/H  ISSN 2095-9125
    知网期刊主页：https://navi.cnki.net/knavi/journals/DYRW/detail
    """
    journal_name = "德语人文研究"
    base_url = "https://navi.cnki.net/knavi/journals/DYRW/detail"
    new_papers = []

    print(f"\n[{journal_name}] 开始抓取...")
    soup = get_page(base_url)
    if not soup:
        # 备用：直接构造近期期号URL
        print(f"[{journal_name}] 主页不可达，尝试备用策略")
        return _scrape_cnki_fallback(journal_name, "DYRW", existing)

    # 解析期号列表
    issue_links = soup.select("a[href*='year=']")[:max_issues]
    for link in issue_links:
        href = link.get("href", "")
        issue_url = f"https://navi.cnki.net{href}" if href.startswith("/") else href
        papers = _parse_cnki_issue(issue_url, journal_name, existing)
        new_papers.extend(papers)
        time.sleep(CRAWL_DELAY)

    return new_papers


def _scrape_cnki_fallback(journal_name: str, journal_code: str, existing: dict) -> list:
    """
    备用策略：直接访问知网期刊的RSS或文章列表
    知网提供的公开接口：按年/期查询
    """
    new_papers = []
    current_year = datetime.now().year

    for year in [current_year, current_year - 1]:
        for issue in range(1, 5):  # 每年4期
            url = (
                f"https://navi.cnki.net/knavi/journals/{journal_code}/"
                f"detail?uniplatform=NZKPT&year={year}&issue=0{issue}"
            )
            papers = _parse_cnki_issue(url, journal_name, existing)
            new_papers.extend(papers)
            time.sleep(CRAWL_DELAY)

    return new_papers


def _parse_cnki_issue(url: str, journal_name: str, existing: dict) -> list:
    """解析知网单期文章列表"""
    soup = get_page(url)
    if not soup:
        return []

    new_papers = []
    # 知网期刊详情页的文章条目选择器（实际部署时需根据页面结构调整）
    articles = soup.select(".article-item, .content-item, li.item")

    for art in articles:
        title_el = art.select_one(".title, .name, a.title")
        abstract_el = art.select_one(".abstract, .summary")
        author_el = art.select_one(".author, .writers")

        if not title_el:
            continue

        title = title_el.get_text(strip=True)
        abstract = abstract_el.get_text(strip=True) if abstract_el else ""
        authors = author_el.get_text(strip=True) if author_el else ""

        # 从URL或页面提取年/期
        year_match = re.search(r"year=(\d{4})", url)
        issue_match = re.search(r"issue=0?(\d+)", url)
        year = int(year_match.group(1)) if year_match else datetime.now().year
        issue_num = int(issue_match.group(1)) if issue_match else 1

        pid = paper_id(title, journal_name, year)
        if pid in existing:
            continue  # 已有，跳过

        paper = {
            "id": pid,
            "journal": journal_name,
            "year": year,
            "issue_num": issue_num,
            "issue": f"第{issue_num}期",
            "title": title,
            "title_de": None,
            "authors": authors,
            "abstract": abstract,
            "source_url": url,
            "scraped_at": datetime.now().isoformat(),
            "ai_analyzed": False,
            "is_new": True,
        }
        new_papers.append(paper)
        print(f"  [新] {title[:40]}...")

    return new_papers


# ── 爬虫 2：《德国研究》──────────────────────────────────────────────────────
# 同济大学德国研究中心官网
# http://germanstudies.tongji.edu.cn/

def scrape_degyj(existing: dict) -> list:
    """
    《德国研究》
    同济大学德国研究中心
    季刊，CSSCI来源期刊
    """
    journal_name = "德国研究"
    new_papers = []

    # 同济德国研究期刊目录页（实际URL需验证）
    urls_to_try = [
        "http://germanstudies.tongji.edu.cn/index.php/journal",
        "https://germanstudies.tongji.edu.cn/journal",
        "http://www.germanstudies.cn/journal",
    ]

    print(f"\n[{journal_name}] 开始抓取...")
    for url in urls_to_try:
        soup = get_page(url)
        if not soup:
            continue

        articles = soup.select("article, .paper-item, .article-entry, li.paper")
        for art in articles:
            title_el = art.select_one("h2, h3, .title, a")
            abstract_el = art.select_one(".abstract, p.summary")
            author_el = art.select_one(".author, .byline")

            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            abstract = abstract_el.get_text(strip=True) if abstract_el else ""
            authors = author_el.get_text(strip=True) if author_el else ""

            # 尝试从文本提取年份
            year_text = art.get_text()
            year_match = re.search(r"(20\d{2})", year_text)
            year = int(year_match.group(1)) if year_match else datetime.now().year

            pid = paper_id(title, journal_name, year)
            if pid in existing or not title:
                continue

            paper = {
                "id": pid,
                "journal": journal_name,
                "year": year,
                "issue_num": 1,
                "issue": _extract_issue(art.get_text()),
                "title": title,
                "title_de": None,
                "authors": authors,
                "abstract": abstract,
                "source_url": url,
                "scraped_at": datetime.now().isoformat(),
                "ai_analyzed": False,
                "is_new": True,
            }
            new_papers.append(paper)
            print(f"  [新] {title[:40]}...")
            time.sleep(CRAWL_DELAY)

        if new_papers:
            break  # 成功则不尝试其他URL

    if not new_papers:
        print(f"  [{journal_name}] 官网无法访问，标记为待手动补录")

    return new_papers


# ── 爬虫 3：《德文月刊》/《德语国家研究》──────────────────────────────────────
# 注：「德文月刊」可能指《Deutsch Perfekt》汉语版或内部刊物
# 实际部署时需要你确认具体期刊的CNKI收录号或官网

def scrape_dfyk(existing: dict) -> list:
    """
    《德文月刊》/ 德语国家研究方向期刊
    策略：通过知网高级检索抓取"德语国家"相关期刊
    """
    journal_name = "德文月刊"
    new_papers = []
    print(f"\n[{journal_name}] 开始抓取...")

    # 知网高级检索（期刊名称检索，公开接口）
    search_url = (
        "https://kns.cnki.net/kns8s/defaultresult/index?"
        "crossids=CJFD&korder=&kw=德语&kf=RT&v=&uniplatform=NZKPT"
    )

    soup = get_page(search_url)
    if not soup:
        print(f"  [{journal_name}] 检索页不可达")
        return []

    results = soup.select(".result-table-list tr, .article-item")
    for item in results[:20]:
        title_el = item.select_one(".name a, td.name a")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)

        # 过滤：只要德语研究相关
        keywords = ["德语", "德国", "德文", "德意志", "德奥", "日耳曼"]
        if not any(kw in title for kw in keywords):
            continue

        abstract_el = item.select_one(".abstract, .summary")
        author_el = item.select_one(".author")
        year_el = item.select_one(".year, td.year")

        abstract = abstract_el.get_text(strip=True) if abstract_el else ""
        authors = author_el.get_text(strip=True) if author_el else ""
        year_text = year_el.get_text(strip=True) if year_el else str(datetime.now().year)
        year_match = re.search(r"(20\d{2})", year_text)
        year = int(year_match.group(1)) if year_match else datetime.now().year

        pid = paper_id(title, journal_name, year)
        if pid in existing:
            continue

        paper = {
            "id": pid,
            "journal": journal_name,
            "year": year,
            "issue_num": 1,
            "issue": "",
            "title": title,
            "title_de": None,
            "authors": authors,
            "abstract": abstract,
            "source_url": search_url,
            "scraped_at": datetime.now().isoformat(),
            "ai_analyzed": False,
            "is_new": True,
        }
        new_papers.append(paper)
        print(f"  [新] {title[:40]}...")

    return new_papers


# ── 工具：提取期号 ────────────────────────────────────────────────────────────

def _extract_issue(text: str) -> str:
    m = re.search(r"第?\s*([一二三四1234])\s*期", text)
    if m:
        return f"第{m.group(1)}期"
    m2 = re.search(r"No\.\s*(\d+)", text)
    if m2:
        return f"No.{m2.group(1)}"
    return ""


# ── 历史补录策略 ──────────────────────────────────────────────────────────────

def backfill_historical(existing: dict, target_total: int = 200) -> list:
    """
    当近期论文不足时，补录历史高价值文章
    策略：按年份倒序，从2020年开始往前推
    """
    current_count = len(existing)
    if current_count >= target_total:
        print(f"[历史补录] 已有 {current_count} 篇，暂不补录")
        return []

    needed = target_total - current_count
    print(f"[历史补录] 当前 {current_count} 篇，需补录约 {needed} 篇历史文章")

    # 实际补录逻辑：扩展年份范围重跑各期爬虫
    # 这里返回空列表，由调度器决定是否触发
    return []


# ── 主入口 ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print(f"Germanistik 爬虫启动 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    existing = load_existing()
    print(f"[已有] {len(existing)} 篇论文")

    all_new = []

    # 抓取各期刊
    all_new.extend(scrape_dyrwj(existing))
    all_new.extend(scrape_degyj(existing))
    all_new.extend(scrape_dfyk(existing))

    # 合并去重
    for paper in all_new:
        existing[paper["id"]] = paper

    # 历史补录
    backfill_historical(existing)

    # 保存
    save_all(existing)

    print(f"\n[完成] 本次新增 {len(all_new)} 篇")
    print("=" * 60)

    return len(all_new)


if __name__ == "__main__":
    main()
