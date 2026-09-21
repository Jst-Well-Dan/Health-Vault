"""组装两份体检的 commit payload（labs 来自脚本解析 + 手工印象行 + 主检诊断）。"""
import json

labs_data = json.load(open("tijian_labs.json", encoding="utf-8"))

DAN_DIAGNOSIS = [
    "右肺多发结节，Lung-RADS 2（建议12个月复查胸部低剂量CT，呼吸科随诊）",
    "甲状腺双叶结节（多发）伴钙化（C-TIRADS 2类，建议年度复查）",
    "脂肪肝（轻度）",
    "肝囊肿（约9.7mm×7.0mm，建议每年复查肝脏超声）",
    "胰腺部分显示不清（肠气干扰，建议充分空腹后复查）",
    "前列腺囊肿（约4.8mm×3.8mm，建议年度复查超声及PSA）",
    "双眼屈光不正（矫正视力双眼1.5，正常；注意用眼卫生，年度检查）",
]

CHUN_DIAGNOSIS = [
    "CK值偏高1881U/L、CK-MB偏高35.00U/L（建议心内科就诊；已于2026-08-28门诊复查，见就诊记录）",
    "右侧乳腺结节BI-RADS 3类（约4.5mm，9点，首次发现，建议乳腺外科进一步检查）",
    "子宫内膜息肉可能（约4mm，需结合月经情况进一步明确）",
    "双侧乳腺小叶增生",
    "子宫颈黏膜外翻",
    "总胆固醇偏高5.55mmol/L",
    "动脉硬化指数(AI)偏高4.05",
    "血清碱性磷酸酶偏低33U/L",
    "血清尿酸偏高398μmol/L",
    "颈椎轻度骨质增生",
    "甲状腺回声欠均匀、双叶结节C-TIRADS 3类（左约3mm、右约4mm，定期复查）",
    "脂肪肝",
    "宫颈纳氏囊肿（多发）",
    "右肺中叶微小结节（约1mm，建议随诊复查）",
    "窦性心动过缓（HR 56次/分，报告建议如有不适心血管内科诊治）",
]

dan_labs = labs_data["dan"]["labs"] + [
    {"panel": "心电图", "test_name": "常规心电图检查", "value": "窦性心律，正常心电图",
     "unit": None, "ref_low": None, "ref_high": None, "status": "normal"},
]

chun_labs = labs_data["chun"]["labs"] + [
    {"panel": "心电图", "test_name": "静态心电图", "value": "窦性心动过缓（HR 56次/分）",
     "unit": None, "ref_low": None, "ref_high": None, "status": "abnormal"},
    {"panel": "心脏彩超", "test_name": "超声提示", "value": "静息状态下超声心动图未见明显异常",
     "unit": None, "ref_low": None, "ref_high": None, "status": "normal"},
    {"panel": "经颅多普勒", "test_name": "诊断提示", "value": "TCD大致正常",
     "unit": None, "ref_low": None, "ref_high": None, "status": "normal"},
    {"panel": "骨密度", "test_name": "T值", "value": "2.2",
     "unit": None, "ref_low": None, "ref_high": None, "status": "normal"},
    {"panel": "骨密度", "test_name": "Z值", "value": "2.4",
     "unit": None, "ref_low": None, "ref_high": None, "status": "normal"},
]

dan_payload = {
    "source_id": "5cb4cd35d22d4a85881968cb15a9db23",
    "member_key": "dan",
    "visit": {
        "date": "2026-08-06", "type": "体检",
        "hospital": "北京美兆健康体检中心",
        "chief_complaint": "年度健康体检",
        "diagnosis": DAN_DIAGNOSIS,
        "notes": "体检日期2026-08-06，建议下次体检2027-08-06；主检异常7项详见诊断；其余检验指标均在参考范围内。",
    },
    "labs": dan_labs,
}

chun_payload = {
    "source_id": "1edcd1e7037c417488ce29dddf98f595",
    "member_key": "chun",
    "visit": {
        "date": "2026-08-19", "type": "体检",
        "hospital": "北京瑞慈瑞泰综合门诊部",
        "chief_complaint": "年度健康体检",
        "diagnosis": CHUN_DIAGNOSIS,
        "notes": "体检日期2026-08-19，终检2026-08-21；主检异常15项详见诊断；其余检验指标均在参考范围内。",
    },
    "labs": chun_labs,
}

json.dump(dan_payload, open(".payload_dan_tijian.json", "w", encoding="utf-8"), ensure_ascii=False)
json.dump(chun_payload, open(".payload_chun_tijian.json", "w", encoding="utf-8"), ensure_ascii=False)
print(f"dan labs: {len(dan_labs)}, chun labs: {len(chun_labs)}")
