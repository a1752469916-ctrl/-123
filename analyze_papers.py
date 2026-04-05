"""
Germanistik 学术追踪 — AI 分析模块

对每篇论文调用 Claude API，生成：
  1. 理论范式定位（文学/文化学/语言学 三个维度的位置）
  2. 核心研究问题
  3. 在德语研究学科中的坐标（属于哪个子领域，处于前沿/主流/经典）
  4. 综合价值评分（1-5）+ 理论创新评分（1-5）

运行：python analyze_papers.py
读取：data/papers_raw.json
输出：data/papers_analyzed.json + data/daily_report.json
"""

import json
import os
import time
from pathlib import Path
from datetime import datetime
import anthropic

# ── 配置 ─────────────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent.parent / "data"
RAW_FILE      = DATA_DIR / "papers_raw.json"
ANALYZED_FILE = DATA_DIR / "papers_analyzed.json"
REPORT_FILE   = DATA_DIR / "daily_report.json"

# Claude API（密钥从环境变量读取，GitHub Actions 中设置 Secret）
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
MODEL = "claude-opus-4-5"

# 每次分析的间隔（避免超速）
API_DELAY = 1.5

# ── 核心 Prompt ───────────────────────────────────────────────────────────────

ANALYSIS_SYSTEM = """你是一位专业的德语学术研究顾问，专精于德语文学研究、文化学（Kulturwissenschaft / Kulturtechnik）和德语语言学。
你的任务是分析中文德语学术论文，帮助研究生快速判断论文的学术价值和研究定位。

输出必须是合法的 JSON，不要有任何额外文字，严格遵守以下结构：
{
  "paradigm_label": "主要理论范式，如：文化技术理论、文化记忆研究、认知语言学等",
  "paradigm_tags": ["范式标签1", "范式标签2"],
  "discipline_position": {
    "domain": "文学研究 | 文化学研究 | 语言学研究 | 跨学科",
    "subdomain": "具体子领域，如：德语现代文学、媒介考古学、构式语法学",
    "status": "前沿探索 | 主流方向 | 经典议题 | 本土化移植"
  },
  "research_question": "一句话概括核心研究问题",
  "theoretical_positioning": "2-4句话，说明该论文使用了什么理论工具、问的是什么性质的问题、在德语文学/文化学/语言学研究的谱系中处于哪个位置。用学术语言，直接说定位，不要夸奖。",
  "value_score": 整数1-5,
  "innovation_score": 整数1-5,
  "value_headline": "一句话，说明这篇文章值得读的最关键理由（不要用'本文''该文'）",
  "for_whom": "简要说明哪种研究取向的读者最应该读这篇"
}

评分标准：
- value_score 5分：方法论范例 / 提出新框架 / 填补显著空白
- value_score 4分：理论应用扎实，对特定研究方向有重要参考价值
- value_score 3分：标准学术成果，有参考价值但无突破
- value_score 2分：综述或工具性论文，选择性参考
- value_score 1分：过时或低质量

innovation_score 标准：
- 5：提出原创概念/框架
- 4：跨范式创造性融合
- 3：新材料+成熟方法
- 2：成熟方法+惯常材料
- 1：重复已有研究"""


ANALYSIS_USER_TEMPLATE = """请分析以下论文：

期刊：{journal}
年份：{year} {issue}
标题：{title}
作者及机构：{authors}
摘要：{abstract}"""


# ── 单篇分析 ──────────────────────────────────────────────────────────────────

def analyze_paper(paper: dict) -> dict | None:
    """调用 Claude API 分析单篇论文"""
    prompt = ANALYSIS_USER_TEMPLATE.format(
        journal=paper.get("journal", ""),
        year=paper.get("year", ""),
        issue=paper.get("issue", ""),
        title=paper.get("title", ""),
        authors=paper.get("authors", "（作者信息缺失）"),
        abstract=paper.get("abstract", "（摘要缺失）"),
    )

    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=800,
            system=ANALYSIS_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()

        # 清理可能的 markdown 代码块包裹
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        result = json.loads(raw)
        return result

    except json.JSONDecodeError as e:
        print(f"  [解析错误] {paper['title'][:30]}: {e}")
        return None
    except Exception as e:
        print(f"  [API错误] {paper['title'][:30]}: {e}")
        return None


# ── 批量分析 ──────────────────────────────────────────────────────────────────

def run_analysis():
    """分析所有未处理的论文"""
    if not RAW_FILE.exists():
        print("[错误] papers_raw.json 不存在，请先运行爬虫")
        return

    # 读取原始数据
    with open(RAW_FILE, "r", encoding="utf-8") as f:
        raw_papers = json.load(f)

    # 读取已分析数据
    if ANALYZED_FILE.exists():
        with open(ANALYZED_FILE, "r", encoding="utf-8") as f:
            analyzed = {p["id"]: p for p in json.load(f)}
    else:
        analyzed = {}

    # 找出未分析的
    pending = [p for p in raw_papers if p["id"] not in analyzed or not p.get("ai_analyzed")]
    print(f"[分析] 待处理 {len(pending)} 篇 / 共 {len(raw_papers)} 篇")

    new_count = 0
    for i, paper in enumerate(pending):
        print(f"  [{i+1}/{len(pending)}] {paper['title'][:45]}...")
        result = analyze_paper(paper)

        if result:
            # 合并分析结果到论文数据
            enriched = {**paper, **result, "ai_analyzed": True, "analyzed_at": datetime.now().isoformat()}
            analyzed[paper["id"]] = enriched
            new_count += 1
            print(f"    ✓ {result.get('paradigm_label','?')} | 价值:{result.get('value_score')} 创新:{result.get('innovation_score')}")
        else:
            # 分析失败，保留原始数据
            analyzed[paper["id"]] = {**paper, "ai_analyzed": False}

        time.sleep(API_DELAY)

    # 保存
    sorted_analyzed = sorted(analyzed.values(), key=lambda p: (p.get("year", 0), p.get("issue_num", 0)), reverse=True)
    with open(ANALYZED_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted_analyzed, f, ensure_ascii=False, indent=2)

    print(f"\n[保存] {len(sorted_analyzed)} 篇 → {ANALYZED_FILE}")
    return sorted_analyzed


# ── 每日报告生成 ───────────────────────────────────────────────────────────────

REPORT_SYSTEM = """你是德语学术研究分析师。基于今日新收论文数据，生成一份简洁的每日学术动态报告。
输出为 JSON，结构如下：
{
  "date": "YYYY-MM-DD",
  "headline": "一句话，15字以内，概括今日最显著的学术趋势",
  "summary": "3-5句话的趋势分析，要有实质性判断，说明哪些范式在上升、哪些议题在聚合、有无新的跨学科节点出现",
  "rising_paradigms": ["上升中的范式1", "范式2"],
  "stable_paradigms": ["稳定主流范式"],
  "emerging_topics": ["新兴议题或尚未命名的研究方向"],
  "field_intro": {
    "topic": "今日推荐了解的研究领域或范式名称",
    "tag": "新兴 | 主流 | 经典重读",
    "description": "100字左右介绍这个领域：是什么、代表人物、在国内德语研究中的现状、为什么现在值得关注"
  }
}"""


def generate_daily_report(papers: list) -> dict:
    """基于今日新增论文生成每日报告"""
    today = datetime.now().strftime("%Y-%m-%d")
    new_today = [p for p in papers if p.get("is_new") and p.get("ai_analyzed")]

    if not new_today:
        print("[报告] 今日无新论文，使用近期数据生成报告")
        new_today = [p for p in papers if p.get("ai_analyzed")][:10]

    # 整理给 Claude 的输入数据
    summaries = []
    for p in new_today[:15]:
        summaries.append({
            "journal": p.get("journal"),
            "title": p.get("title"),
            "paradigm": p.get("paradigm_label"),
            "domain": p.get("discipline_position", {}).get("domain"),
            "status": p.get("discipline_position", {}).get("status"),
            "research_question": p.get("research_question"),
            "value_score": p.get("value_score"),
        })

    user_msg = f"今日新收论文数据：\n{json.dumps(summaries, ensure_ascii=False, indent=2)}"

    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=REPORT_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        report = json.loads(raw.strip())
        report["date"] = today
        report["paper_count"] = len(new_today)

    except Exception as e:
        print(f"[报告生成失败] {e}")
        report = {
            "date": today,
            "headline": "数据更新中",
            "summary": "",
            "rising_paradigms": [],
            "stable_paradigms": [],
            "emerging_topics": [],
            "field_intro": {"topic": "", "tag": "", "description": ""},
            "paper_count": len(new_today),
        }

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"[报告] 已生成 → {REPORT_FILE}")
    return report


# ── 范式统计 ──────────────────────────────────────────────────────────────────

def compute_paradigm_stats(papers: list) -> list:
    """统计近30天各范式出现频率"""
    from collections import Counter

    recent = [p for p in papers if p.get("ai_analyzed")][:60]  # 近期约30天
    all_tags = []
    for p in recent:
        all_tags.extend(p.get("paradigm_tags", []))

    counts = Counter(all_tags)
    total = max(sum(counts.values()), 1)

    stats = [
        {"name": name, "count": cnt, "pct": round(cnt / total * 100)}
        for name, cnt in counts.most_common(8)
    ]

    stats_file = DATA_DIR / "paradigm_stats.json"
    with open(stats_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    return stats


# ── 主入口 ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print(f"AI 分析启动 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    analyzed_papers = run_analysis()
    if analyzed_papers:
        generate_daily_report(analyzed_papers)
        stats = compute_paradigm_stats(analyzed_papers)
        print(f"[统计] 范式分布已更新，共 {len(stats)} 个范式")

    print("=" * 60)


if __name__ == "__main__":
    main()
