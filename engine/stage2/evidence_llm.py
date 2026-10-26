"""로컬 LLM의 자유서술 제안을 원문 대조 가능한 후보로만 접수합니다."""
from __future__ import annotations

from hashlib import sha256
import json
import re

from . import evidence_workspace as ew


def propose(project, document_sha, client):
    data=ew.graph(project)
    document=next((d for d in data["documents"] if d["sha256"]==document_sha),None)
    if not document:raise ValueError("접수한 문서를 찾을 수 없습니다.")
    if not document.get("hint"):
        raise ValueError("서술형 문서는 먼저 대상 식별번호를 지정해 접수해야 합니다.")
    passages=[p for p in document.get("passages",[]) if p.get("text","").strip()]
    if not passages:raise ValueError("인식한 글자가 없습니다. 스캔 문서는 OCR을 먼저 수행하세요.")
    # 한 번에 보내는 원문 크기를 제한하되 각 위치를 그대로 제공.
    excerpt=[{"location":p["location"],"text":p["text"][:3000]} for p in passages[:30]]
    response=client.generate_json(
        instructions="당신은 자료 추출 보조자입니다. 문서에 문자 그대로 있는 연속 인용구만 추출하세요. 추론, 단위 환산, 법적 판정, 누락값 생성은 금지합니다. JSON {\"items\":[{\"field\":\"name|product|cas|capacity|pressure|design_pressure|temperature|inventory|concentration\",\"raw\":\"값 문자열\",\"header\":\"원문의 단위 포함 항목명\",\"quote\":\"원문에서 연속된 정확한 인용구\",\"location\":\"제공된 위치\"}]} 만 출력하세요.",
        prompt=json.dumps({"entity":document["kind"]+":"+document["hint"],"passages":excerpt},ensure_ascii=False))
    items=response.get("items") if isinstance(response,dict) else None
    if not isinstance(items,list):raise ValueError("모델이 후보 목록을 반환하지 않았습니다.")
    accepted=[];rejected=0
    locations={p["location"]:p["text"] for p in excerpt}
    for item in items[:100]:
        if not isinstance(item,dict):rejected+=1;continue
        field=item.get("field");raw=item.get("raw");header=item.get("header");quote=item.get("quote");location=item.get("location")
        if (field not in ew.LABELS or not isinstance(raw,str) or not raw.strip() or
            not isinstance(header,str) or not isinstance(quote,str) or not isinstance(location,str) or
            location not in locations or quote not in locations[location] or raw not in quote or
            ew.ALIASES.get(ew.norm(header))!=field):
            rejected+=1;continue
        if field in {"capacity","inventory","pressure","design_pressure","temperature","concentration"}:
            # 모델이 원문에 없는 단위를 붙여 해석하거나 숫자 일부를 인용하면 버립니다.
            units={"capacity":(r"m3|m³",r"\bL\b"),"inventory":(r"\bkg\b",r"\bton\b"),
                   "pressure":(r"\bkPa\b",r"\bMPa\b"),"design_pressure":(r"\bkPa\b",r"\bMPa\b"),
                   "temperature":(r"°C|\bC\b",),"concentration":(r"%",)}[field]
            if (not any(re.search(unit,header,re.I) and re.search(unit,quote,re.I) for unit in units) or
                not re.search(r"(?<![\d.,])"+re.escape(raw)+r"(?![\d.,])",quote)):
                rejected+=1;continue
        value=ew.normalize_value(field,raw,header)
        identifier=sha256(json.dumps([document_sha,document["kind"],document["hint"],field,location,raw,"llm"],ensure_ascii=False).encode()).hexdigest()[:24]
        accepted.append({"id":identifier,"entity":document["kind"]+":"+document["hint"],"kind":document["kind"],
                         "field":field,"value":value,"raw":raw,"header":header,"document":document["name"],
                         "sha256":document_sha,"location":location,"quote":quote,"method":"llm","confidence":0.55})
    known={f["id"] for f in data["facts"]}
    new=[fact for fact in accepted if fact["id"] not in known]
    if new:
        data["facts"].extend(new)
        ew._store(project,data)
        ew._invalidate(project)
        ew.auto_approve_safe(project)
    return {"accepted":len(new),"rejected":rejected}
