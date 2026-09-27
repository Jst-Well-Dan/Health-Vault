"""一次性体检 Markdown 解析脚本（美兆/瑞慈 MinerU 表格 -> lab 行）.

只读 incoming 下的两份 .md,输出 JSON 到 stdout,不写库。
状态判定原则:数值超出参考范围或带↑↓标记 -> high/low;
阴性/未见/未闻及等且与参考一致 -> normal;无法判定 -> unknown。
"""
import json
import re
import sys

ARROW_HIGH = "↑"
ARROW_LOW = "↓"


def clean_cell(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    text = text.replace("★", "").strip()
    return re.sub(r"\s+", " ", text)


def split_row(line: str) -> list[str]:
    cells = [clean_cell(c) for c in line.strip().strip("|").split("|")]
    return cells


def split_html_row(seg: str) -> list[str]:
    parts = re.findall(r"<td[^>]*>(.*?)</td>", seg, flags=re.S)
    return [clean_cell(p) for p in parts]


def is_header_row(cells: list[str]) -> bool:
    first = cells[0] if cells else ""
    return first in {"项目", "名称", "血管名称"} or (
        len(cells) > 1 and cells[1] in {"本次", "检查结果", "测量值"}
    )


def parse_number(text: str):
    m = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    return float(m.group(0)) if m else None


def parse_ref(ref: str, sex: str):
    """返回 (low, high)，无法解析返回 (None, None)。sex: '男'/'女'。"""
    ref = ref.strip()
    if not ref or ref in {"-", "–", "/", "~", "--"}:
        return None, None
    # 性别特异参考：取对应性别段
    if "男" in ref and "女" in ref and (";" in ref or ";" in ref):
        parts = re.split(r"[;；]", ref)
        picked = next((p for p in parts if sex in p), "")
        ref = picked
    # 非孕妇人群段（取首段数值对）
    m_seg = re.search(r"[^:：]*[:：]\s*(-?\d+(?:\.\d+)?\s*[~～\-–]\s*-?\d+(?:\.\d+)?)", ref)
    if m_seg and ("孕妇" in ref or "人群" in ref):
        ref = m_seg.group(1)
    ref = ref.replace("～", "~").replace("–", "~").replace("—", "~").replace("--", "~")
    ref = re.sub(r"(?<=\d)\s*-\s*(?=\d)", "~", ref)
    # 先拆范围再取数，避免 "3.50--9.50" 的后半被当成负数
    nums: list[float] = []
    if "~" in ref:
        for part in ref.split("~"):
            m = re.search(r"-?\d+(?:\.\d+)?", part)
            if m:
                nums.append(float(m.group(0)))
    else:
        nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", ref)]
    if not nums:
        return None, None
    has_lt = bool(re.search(r"[<＜≤]", ref))
    has_gt = bool(re.search(r"[>＞≥]", ref))
    if "~" in ref or ("-" in ref and len(nums) >= 2):
        return nums[0], nums[1]
    if has_lt:
        return None, nums[0]
    if has_gt:
        return nums[0], None
    if len(nums) == 1:
        return None, None
    return nums[0], nums[1]


NEGATIVE_WORDS = ("阴性", "未见", "未闻及", "无", "正常", "透明", "齐", "(-)", "(~)")


def split_value_unit(value: str):
    """'8.23 *10^9/L' -> ('8.23', '*10^9/L'); '104 mmHg' -> ('104','mmHg')。
    剥离残留的↑↓（箭头只由前端按 status 统一渲染）。"""
    value = value.strip()
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)\s+(.+)$", value)
    if m:
        unit = m.group(2).strip().replace("↑", "").replace("↓", "").strip()
        return m.group(1), unit or ""
    return value.replace("↑", "").replace("↓", "").strip(), ""


def decide_status(value: str, unit: str, ref: str, sex: str):
    v = value.strip()
    arrows = ARROW_HIGH in v or "↑" in v
    arrows_low = ARROW_LOW in v or "↓" in v
    v = v.replace("↑", "").replace("↓", "").strip()
    num = parse_number(v)
    low, high = parse_ref(ref, sex)
    if num is not None and (low is not None or high is not None):
        if high is not None and num > high:
            return "high"
        if low is not None and num < low:
            return "low"
        return "normal"
    if arrows:
        return "high"
    if arrows_low:
        return "low"
    # 非数值：与参考一致或典型阴性表述 -> normal
    r = ref.strip()
    if v == r or (r and (v in r or r in v)):
        return "normal"
    if any(w in v for w in NEGATIVE_WORDS):
        return "normal"
    if not r or r in {"-", "–", "/", "~"}:
        return "normal" if num is not None else "unknown"
    return "unknown"


SECTION_PANEL = [
    (r"血常规|血液常规", "血常规"),
    (r"血脂|脂蛋白|载脂蛋白|动脉.*硬化指数|动脉粥样", "血脂"),
    (r"肝功能|肝胆功能", "肝功能"),
    (r"肾功能|肾功|尿酸", "肾功能"),
    (r"肿瘤标志|癌胚|甲胎蛋白|糖类抗原", "肿瘤标志物"),
    (r"血糖|糖化|糖尿病|淀粉酶", "血糖代谢"),
    (r"尿常规|尿液检测", "尿常规"),
    (r"白带", "白带常规"),
    (r"甲状腺功能", "甲状腺功能"),
    (r"免疫球蛋白", "免疫"),
    (r"幽门螺杆菌", "幽门螺杆菌抗体"),
    (r"HPV|TCT|人乳头瘤", "HPV/TCT"),
    (r"血粘度|血沉|红细胞.*指数", "血粘度"),
    (r"一般检查", "一般检查"),
    (r"心电图", "心电图"),
    (r"骨密度", "骨密度"),
    (r"心脏彩超|心超", "心脏彩超"),
    (r"心肌酶", "心肌酶"),
]


def panel_for(section: str) -> str | None:
    for pattern, panel in SECTION_PANEL:
        if re.search(pattern, section):
            return panel
    return None


SKIP_SECTIONS = re.compile(r"阅读说明|警示灯|科普|免责|目录|温馨提示|宣教|注解|首页|封面|经颅多普勒|TCD|外周动脉")

SKIP_ROW_WORDS = ("检测机构", "检验者", "审核者", "采样", "报告时间", "备注", "咨询", "检测时间", "样本类型", "样本性状")


def parse_file(path: str, sex: str):
    text = open(path, encoding="utf-8").read()
    labs: list[dict] = []
    summaries: list[str] = []
    current_section = ""
    current_panel = None
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("## ") or "【" in line:
            lines.append(line)
        elif len(line) < 30 and "<" not in line and "|" not in line and not line.startswith(("!", "[", "(")):
            # 无标记短行：可能是小节标题（如“超声经颅多普勒报告单”），留给主循环判定
            lines.append(line)
        else:
            # 表格常为单行 <table><tr>...</tr>...</table>，按 <tr> 切开
            for seg in re.split(r"(?=<tr>)", line):
                if "<tr>" in seg:
                    lines.append(seg)
    for line in lines:
        if line.startswith("## "):
            current_section = re.sub(r"<[^>]+>", "", line[3:]).strip()
            current_panel = None if SKIP_SECTIONS.search(current_section) else panel_for(current_section)
            continue
        # 无 ## 的小节标题：【xxx】或与已知 panel 关键词完全匹配的短行
        stripped = re.sub(r"【|】", "", line).strip()
        if not line.startswith("<tr>") and len(stripped) < 24 and "<" not in stripped:
            panel = panel_for(stripped)
            if panel is not None:
                current_section, current_panel = stripped, panel
                continue
            if SKIP_SECTIONS.search(stripped):
                current_section, current_panel = stripped, None
                continue
        if not line.startswith("<tr>") or current_panel is None:
            # 小结行收集（任意段）
            if "<td" in line and "小结" in line:
                cells = split_html_row(line)
                summaries.append(f"[{current_section}] " + " ".join(c for c in cells if c))
            continue
        cells = split_html_row(line)
        if len(cells) < 2 or is_header_row(cells):
            continue
        if any("小结" in c for c in cells) or any(c.startswith("注") for c in cells if c):
            summaries.append(f"[{current_section}] " + " ".join(c for c in cells if c))
            continue
        name, raw_value = cells[0], cells[1]
        if not name or not raw_value or raw_value == "-":
            continue
        if len(name) > 30 or len(raw_value) > 40:
            continue  # 主检汇总/建议等长文本行，不是检验指标
        if name in {"一般健康问题:", "医师建议:"} or re.match(r"^\d+、", name):
            continue  # 主检异常汇总编号行，归入就诊 diagnosis，不做指标
        if any(w in name for w in SKIP_ROW_WORDS) or any(w in raw_value for w in SKIP_ROW_WORDS):
            continue
        if any(w in name for w in ("姓名", "性别", "年龄", "编号", "体检号", "住院号")):
            continue
        rest = cells[2:]
        unit, ref = "", ""
        if len(rest) >= 2:
            # 美兆：前次、前前次、单位、参考范围（列数不固定，从尾部取）
            ref = rest[-1]
            # 单位：含字母/斜杠/%/次/分的列
            for c in rest[:-1]:
                if re.search(r"[a-zA-Z/%次分]", c) and not re.search(r"^\d", c.replace(".", "")):
                    unit = c
                    break
            else:
                for c in rest[:-1]:
                    if c and c != "-":
                        unit = c
                        break
        elif len(rest) == 1:
            # 瑞慈：参考值（单位常嵌在值里）
            ref = rest[0]
        value, eu = split_value_unit(raw_value)
        if eu and not unit:
            unit = eu
        # 复合值（含多单位如 60次/分）保留原样
        status = decide_status(value, unit, ref, sex)
        if "↑" in raw_value:
            status = "high"
        elif "↓" in raw_value:
            status = "low"
        low, high = parse_ref(ref, sex)
        labs.append({
            "panel": current_panel,
            "test_name": name,
            "value": value,
            "unit": unit or None,
            "ref_low": str(low) if low is not None else None,
            "ref_high": str(high) if high is not None else None,
            "status": status,
        })
    return labs, summaries


def main():
    jobs = [
        ("dan", "男", "incoming/段东伟体检报告_1aec32/段东伟体检报告.md"),
        ("chun", "女", "incoming/杨昭春子_体检报告_2026-08-19_0301112608193204_1__047cf5/杨昭春子_体检报告_2026-08-19_0301112608193204(1).md"),
    ]
    out = {}
    for member, sex, path in jobs:
        labs, summaries = parse_file(path, sex)
        abn = [l for l in labs if l["status"] in {"high", "low"}]
        unk = [l for l in labs if l["status"] == "unknown"]
        out[member] = {
            "lab_total": len(labs),
            "abnormal": [(l["panel"], l["test_name"], l["value"], l["unit"], l["status"]) for l in abn],
            "unknown": [(l["panel"], l["test_name"], l["value"]) for l in unk],
            "labs": labs,
        }
        print(f"== {member} {sex}: 共 {len(labs)} 行，异常 {len(abn)}，unknown {len(unk)}", file=sys.stderr)
        for l in abn:
            print(f"  [{l['panel']}] {l['test_name']}={l['value']} {l['unit'] or ''} ({l['status']})", file=sys.stderr)
        for l in unk:
            print(f"  ?? [{l['panel']}] {l['test_name']}={l['value']}", file=sys.stderr)
    json.dump(out, open("tijian_labs.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("written tijian_labs.json", file=sys.stderr)


if __name__ == "__main__":
    main()
