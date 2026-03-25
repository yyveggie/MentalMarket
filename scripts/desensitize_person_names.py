#!/usr/bin/env python3
"""
对 data/news.json 中的中文人名进行脱敏处理。
策略：基于高频姓氏 + 上下文模式检测人名，替换为 NAME。

用法:
  python scripts/desensitize_person_names.py             # 预览模式（只输出检测结果，不修改文件）
  python scripts/desensitize_person_names.py --apply      # 应用修改（会先备份原文件）
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from pathlib import Path

COMMON_SURNAMES = set(
    "王李张刘陈杨赵黄周吴徐孙马朱胡郭林何高梁郑罗宋谢唐韩曹许邓萧冯曾程蔡彭潘袁于董余苏叶吕魏蒋田杜丁沈姜范江傅钟卢汪戴崔任陆廖姚方金邱夏谭石贺白薛秦邹熊孟龚段郝孔邵史毛贾"
    "万欧温顾龙雷钱严覃武尹侯柏仇甘祝包宁阮桑闫"
)

COMPOUND_SURNAMES = {
    "欧阳", "司马", "上官", "诸葛", "令狐", "皇甫", "慕容", "独孤",
    "长孙", "宇文", "公孙", "南宫", "西门",
    # "东方" 故意排除：在新闻语境中几乎全是机构名（东方财富/东方石化/东方雨虹等）
}

BLACKLIST_WORDS = {
    "高质量", "高水平", "高端", "高新", "高速", "高效", "高峰", "高盛",
    "高考", "高管", "高度", "高铁", "高科", "高层", "高达", "高地",
    "高级", "高涨", "高位", "高增", "高企", "高标", "高额", "高于",
    "高光", "高歌", "高压", "高温", "高潮", "高频", "高昂", "高收",
    "林立", "林业",
    "金融", "金额", "金属", "金价", "金牌", "金刚", "金山", "金证券",
    "金股", "金都城", "金融界", "金在线",
    "余额", "余下", "余热",
    "方面", "方式", "方案", "方向", "方法", "方正", "方兴", "方之间",
    "方石化",
    "石油", "石化", "石门", "石墨", "石晓",
    "田间", "田野", "田园",
    "程度", "程序", "程碑",
    "段时", "段位",
    "任何", "任务", "任期", "任命", "任职", "任正",
    "史上", "史无", "史诗",
    "贾跃",
    "周期", "周末", "周边", "周围", "周转", "周年", "周报",
    "江苏", "江西", "江南", "江北", "江门", "江淮", "江浙",
    "江湖", "江街道", "江三峡", "江舟山",
    "陈述", "陈旧", "陈列",
    "杨浦",
    "黄金", "黄河", "黄山", "黄浦",
    "曹操",
    "许可", "许昌", "许诺",
    "魏建",
    "沈阳",
    "邱吉",
    "秦皇",
    "马克", "马来", "马德", "马斯", "马赛", "马尔", "马上",
    "马克龙", "马斯克", "马来西",
    "唐山", "唐代", "唐朝",
    "韩国", "韩元",
    "孙子", "孙洪水",
    "朱雀",
    "李克", "李嘉", "李宁",
    "曾经", "曾于",
    "蔡英",
    "彭博",
    "潘功",
    "常德", "常态", "常规", "常见",
    "崔东",
    "龚段",
    "卢布", "卢森",
    "汪洋",
    "白酒", "白皮", "白名", "白银",
    "薛定",
    "邹平",
    "郝鹏",
    "熊猫", "熊市",
    "孟加", "孟买",
    "段永",
    "王朝", "王者", "王牌", "王国",
    "张力", "张掖",
    "钟表", "钟情",
    "傅雷",
    "戴尔", "戴维",
    "董事", "董明",
    "于是",
    "邓小",
    "范围", "范畴",
    "苏州", "苏宁", "苏伊", "苏格",
    "叶片",
    "吕梁",
    "胡志", "胡锦",
    "郭台",
    "何时", "何以", "何处",
    "罗马", "罗斯", "罗伯",
    "冯仑",
    "袁隆", "袁一确",
    "夏季", "夏天", "夏普",
    "谭德",
    "贺岁", "贺词",
    "龙头", "龙腾", "龙湖",
    "雷达", "雷军",
    "钱学", "钱币", "钱公司",
    "温州", "温度", "温室",
    "欧洲", "欧盟", "欧元", "欧美", "欧佩", "欧委会", "欧委",
    "顾问", "顾客",
    "宁波", "宁夏", "宁德",
    "桑德", "桑拿",
    "甘肃", "甘南",
    "祝贺", "祝福",
    "包括", "包装", "包上新",
    "武汉", "武装", "武器", "武功",
    "郑州人", "郑州",
    "尹科技",
    "吴证券",
    "王滨一", "王滨受", "王滨被",
}

TITLES = (
    "董事长", "副董事长", "总裁", "副总裁", "总经理", "副总经理", "总工程师",
    "CEO", "CFO", "CTO", "COO", "CMO",
    "院士", "教授", "副教授", "研究员", "博士", "博导",
    "院长", "副院长", "所长", "副所长", "馆长",
    "主席", "副主席", "秘书长", "副秘书长",
    "行长", "副行长", "局长", "副局长", "厅长", "副厅长",
    "部长", "副部长", "司长", "副司长", "处长", "副处长",
    "市长", "副市长", "省长", "副省长", "县长",
    "书记", "副书记", "党委书记",
    "总监", "副总监", "主任", "副主任",
    "合伙人", "创始人", "联合创始人", "实控人",
    "总编", "副总编", "主编", "副主编",
    "经理", "客户经理", "项目经理",
    "分析师", "首席分析师",
    "高管",
)

VERB_SUFFIXES = ("：", ":", "说", "表示", "称", "指出", "透露", "认为", "建议", "预计", "坦言", "回应")

NON_NAME_TRAILING_CHARS = set(
    "受出一被到在于和与了的是有为不也都将把对让给从向往"
    "上下中大小新旧多少全各每某"
    "化业司厂店院局部处所站台港口县市省区镇乡村社"
    "行网报社台站馆所厅部委办"
)


def _is_chinese_char(ch: str) -> bool:
    cp = ord(ch)
    return 0x4E00 <= cp <= 0x9FFF


def _extract_name_candidate(text: str, start: int) -> str | None:
    """从 start 位置提取 2~3 个汉字作为候选人名。"""
    chars = []
    i = start
    while i < len(text) and len(chars) < 3:
        if _is_chinese_char(text[i]):
            chars.append(text[i])
            i += 1
        else:
            break
    if len(chars) < 2:
        return None
    if len(chars) == 3 and chars[2] in NON_NAME_TRAILING_CHARS:
        return "".join(chars[:2])
    return "".join(chars)


def _in_blacklist(name: str) -> bool:
    if name in BLACKLIST_WORDS:
        return True
    for bw in BLACKLIST_WORDS:
        if name.startswith(bw) or bw.startswith(name):
            return True
    return False


def _build_patterns() -> list[re.Pattern]:
    surname_class = "".join(sorted(COMMON_SURNAMES))
    s = f"[{surname_class}]"
    hz = r"[\u4e00-\u9fff]"
    name_2_3 = f"({s}{hz}{{1,2}})"

    verb_alts = "|".join(re.escape(v) for v in VERB_SUFFIXES)
    title_alts = "|".join(re.escape(t) for t in TITLES)

    patterns = [
        re.compile(name_2_3 + f"(?={verb_alts})"),
        re.compile(f"(?:{title_alts})[\"\"''「]*" + name_2_3),
        re.compile(f"(?:对话|专访|访谈|人物)[^\\u4e00-\\u9fff]*?" + name_2_3),
        re.compile(f"Stock [A-Z]{{1,3}}[^\\u4e00-\\u9fff]*?" + name_2_3 + f"(?={verb_alts})"),
    ]
    return patterns


def _trim_name(name: str) -> str:
    """对三字名进行尾字过滤：若第三个字是功能词/后缀词则截断为两字名。"""
    if len(name) == 3 and name[2] in NON_NAME_TRAILING_CHARS:
        return name[:2]
    return name


def detect_names_in_title(title: str, patterns: list[re.Pattern]) -> list[tuple[str, str]]:
    """返回 [(人名, 匹配模式说明), ...]"""
    found: list[tuple[str, str]] = []
    labels = ["verb_suffix", "title_prefix", "interview_prefix", "stock_prefix"]

    for pat, label in zip(patterns, labels):
        for m in pat.finditer(title):
            name = _trim_name(m.group(1))
            if not name or len(name) < 2:
                continue
            if _in_blacklist(name):
                continue
            surname = name[0]
            if surname not in COMMON_SURNAMES:
                continue
            found.append((name, label))

    for cs in COMPOUND_SURNAMES:
        if cs in title:
            idx = title.index(cs)
            candidate = _extract_name_candidate(title, idx)
            if candidate and len(candidate) >= 3 and not _in_blacklist(candidate):
                found.append((candidate, "compound_surname"))

    seen = set()
    unique = []
    for name, label in found:
        if name not in seen:
            seen.add(name)
            unique.append((name, label))
    return unique


def desensitize_title(title: str, names: list[tuple[str, str]]) -> str:
    result = title
    names_sorted = sorted(names, key=lambda x: len(x[0]), reverse=True)
    for name, _ in names_sorted:
        result = result.replace(name, "NAME")
    return result


def main():
    parser = argparse.ArgumentParser(description="对 news.json 中的中文人名脱敏")
    parser.add_argument("--apply", action="store_true", help="应用修改（默认只预览）")
    parser.add_argument("--input", default="data/news.json", help="输入文件路径")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"文件不存在: {input_path}")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    news_list = data.get("news", [])
    patterns = _build_patterns()

    all_names: Counter = Counter()
    modified_count = 0
    examples: list[tuple[str, str, list]] = []

    for item in news_list:
        title = item.get("title", "")
        if not title:
            continue
        names = detect_names_in_title(title, patterns)
        if names:
            for name, label in names:
                all_names[name] += 1
            new_title = desensitize_title(title, names)
            if new_title != title:
                modified_count += 1
                if len(examples) < 30:
                    examples.append((title, new_title, names))
                if args.apply:
                    item["title"] = new_title

    print(f"\n{'='*60}")
    print(f"检测到 {len(all_names)} 个不同的人名，涉及 {modified_count} 条新闻")
    print(f"{'='*60}")

    print(f"\n--- 检测到的人名（按频次排序，前 50）---")
    for name, count in all_names.most_common(50):
        print(f"  {name}: {count}次")

    print(f"\n--- 脱敏示例（前 {len(examples)} 条）---")
    for orig, new, names in examples:
        name_strs = [f"{n}({l})" for n, l in names]
        print(f"  原文: {orig[:100]}")
        print(f"  脱敏: {new[:100]}")
        print(f"  人名: {', '.join(name_strs)}")
        print()

    if args.apply:
        backup_path = input_path.with_suffix(".json.bak")
        if not backup_path.exists():
            shutil.copy2(input_path, backup_path)
            print(f"备份已保存: {backup_path}")

        with open(input_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n已修改 {modified_count} 条新闻标题，写入: {input_path}")
    else:
        print(f"\n[预览模式] 未修改文件。添加 --apply 参数以应用修改。")


if __name__ == "__main__":
    main()
