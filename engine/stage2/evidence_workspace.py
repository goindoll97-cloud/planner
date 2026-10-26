"""문서 중심 업무를 사업장 공통 사실과 확인 과제로 변환합니다."""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import csv
import json
import math
import re
from zipfile import ZipFile, ZIP_DEFLATED

from .project import Stage2Project

KEY = "workspace.evidence_graph"
LABELS = {"name":"명칭", "product":"취급제품", "cas":"CAS 번호", "capacity":"용량(m³)",
          "pressure":"운전압력(MPa)", "design_pressure":"설계압력(MPa)", "temperature":"운전온도(°C)",
          "inventory":"최대보유량(kg)", "concentration":"함량(%)"}
ALIASES = {"명칭":"name","물질명":"name","제품명":"name","설비명":"name","시설명":"name",
           "취급제품":"product","취급물질":"product","cas":"cas","casno":"cas","cas번호":"cas",
           "용량":"capacity","용량m3":"capacity","용량l":"capacity","용량m³":"capacity",
           "운전압력mpa":"pressure","운전압력kpa":"pressure","운전압력":"pressure",
           "설계압력mpa":"design_pressure","설계압력kpa":"design_pressure",
           "운전온도":"temperature","운전온도c":"temperature","운전온도°c":"temperature",
           "최대보유량kg":"inventory","최대보유량ton":"inventory","최대보유량":"inventory",
           "함량":"concentration","함량%":"concentration"}


def norm(value):
    return re.sub(r"[\s().·_-]", "", str(value)).lower()


def graph(project):
    record = project.get_field(KEY)
    return deepcopy(record.value) if record else {"documents":[],"facts":[],"decisions":{}}


def _store(project, data):
    project.set_field(KEY,"사업장 공통정보와 출처",data,"HOLD",note="추출 후보와 담당자 결정을 분리해 보존")


def normalize_value(field, raw, header):
    text=str(raw).strip()
    if field in {"name","product","cas"}: return text
    # 범위나 단위가 불명확한 값을 임의로 숫자로 확정하지 않습니다.
    if not re.fullmatch(r"[+-]?\d+(?:,\d{3})*(?:\.\d+)?",text): return text
    number=float(text.replace(",",""))
    if not math.isfinite(number): return text
    h=norm(header)
    if field in {"capacity","pressure","design_pressure","inventory"} and h in {"용량","운전압력","설계압력","최대보유량"}:
        return text
    if field=="capacity" and h.endswith("l"): number/=1000
    if field in {"pressure","design_pressure"} and h.endswith("kpa"): number/=1000
    if field=="inventory" and h.endswith("ton"): number*=1000
    return number


def read_document(name, content):
    suffix=name.rsplit(".",1)[-1].lower()
    tables=[]; passages=[]
    if len(content)>20*1024*1024: raise ValueError("파일은 20MB 이하로 올려 주세요.")
    if suffix=="csv":
        try: text=content.decode("utf-8-sig")
        except UnicodeDecodeError: text=content.decode("cp949")
        rows=list(csv.reader(text.splitlines()))
        if rows: tables.append(("CSV",rows))
    elif suffix=="xlsx":
        from openpyxl import load_workbook
        workbook=load_workbook(BytesIO(content),read_only=True,data_only=False)
        for sheet in workbook:
            tables.append((sheet.title,[["" if v is None else str(v) for v in row] for row in sheet.iter_rows(values_only=True)]))
        workbook.close()
    elif suffix=="docx":
        from docx import Document
        doc=Document(BytesIO(content))
        passages=[{"location":f"문단 {i}","text":p.text} for i,p in enumerate(doc.paragraphs,1) if p.text.strip()]
        tables=[(f"표 {i}",[[c.text for c in row.cells] for row in table.rows]) for i,table in enumerate(doc.tables,1)]
    elif suffix=="pdf":
        import pdfplumber
        with pdfplumber.open(BytesIO(content)) as pdf:
            for i,page in enumerate(pdf.pages,1):
                passages.append({"location":f"p.{i}","text":page.extract_text() or ""})
                for j,table in enumerate(page.extract_tables(),1): tables.append((f"p.{i} 표 {j}",table))
    elif suffix=="txt":
        passages=[{"location":f"줄 {i}","text":line} for i,line in enumerate(content.decode("utf-8-sig").splitlines(),1)]
    else: raise ValueError("CSV·XLSX·DOCX·텍스트 PDF·TXT를 지원합니다. 다른 형식은 변환 후 가져오세요.")
    return tables,passages


def ingest(project, name, content, kind="facility", entity_hint=""):
    if kind not in {"facility","material"}: raise ValueError("자료 종류를 확인하세요.")
    data=graph(project); digest=sha256(content).hexdigest()
    if any(d["sha256"]==digest and d["kind"]==kind and d.get("hint","")==entity_hint for d in data["documents"]): return 0
    tables,passages=read_document(name,content)
    added=[]; unmapped=[]
    def add(entity,field,raw,location,header,method="table",confidence=0.78):
        value=normalize_value(field,raw,header)
        identifier=sha256(json.dumps([digest,kind,entity,field,location,str(raw)],ensure_ascii=False).encode()).hexdigest()[:24]
        added.append({"id":identifier,"entity":kind+":"+str(entity).strip(),"kind":kind,"field":field,"value":value,
                      "raw":str(raw),"header":str(header),"document":name,"sha256":digest,"location":location,
                      "method":method,"confidence":confidence})
    for location,rows in tables:
        if not rows: continue
        if len(rows)>10001: raise ValueError("한 표에 10,000행 이하로 나눠 주세요.")
        headers=[str(h or "").strip() for h in rows[0]]
        fields=[ALIASES.get(norm(h)) for h in headers]
        id_col=next((i for i,h in enumerate(headers) if norm(h) in {"설비번호","시설번호","설비id","제품코드","물질코드"}),None)
        for r,row in enumerate(rows[1:],2):
            entity=str(row[id_col] or "").strip() if id_col is not None and id_col<len(row) else entity_hint.strip()
            if not entity:
                entity=next((str(row[i]).strip() for i,f in enumerate(fields) if f=="name" and i<len(row) and row[i]),"")
            if not entity: continue
            for i,field in enumerate(fields):
                if i>=len(row) or row[i] is None or not str(row[i]).strip(): continue
                if field: add(entity,field,row[i],f"{location} 행 {r} 열 {i+1}",headers[i],confidence=0.98 if id_col is not None and id_col<len(row) and str(row[id_col] or '').strip() else 0.78)
                elif headers[i] and i!=id_col: unmapped.append(headers[i])
    # 식별 대상을 지정한 명확한 '항목: 값' 문장만 후보로 추출합니다.
    for p in passages:
        if not entity_hint.strip(): continue
        for line in p["text"].splitlines():
            parts=re.split(r"[:：]",line,maxsplit=1)
            if len(parts)==2 and ALIASES.get(norm(parts[0])):
                add(entity_hint,ALIASES[norm(parts[0])],parts[1].strip(),p["location"],parts[0],"literal",0.88)
    data["documents"].append({"name":name,"sha256":digest,"kind":kind,"hint":entity_hint,"passages":passages,
                               "fact_count":len(added),"unmapped_columns":sorted(set(unmapped)),
                               "needs_reading":not added,"needs_ocr":bool(passages) and not any(p["text"].strip() for p in passages)})
    data["facts"].extend(added)
    _store(project,data)
    _invalidate(project)
    auto_approve_safe(project)
    return len(added)


def _invalidate(project):
    for record in project.fields.values():
        if record.note.startswith("공통정보 연결") or record.status=="AI_DRAFT": record.status="HOLD"


def slots(project):
    data=graph(project); groups={}
    for fact in data["facts"]: groups.setdefault(fact["entity"]+"|"+fact["field"],[]).append(fact)
    result=[]
    for key,facts in groups.items():
        values={json.dumps(f["value"],ensure_ascii=False,sort_keys=True) for f in facts}
        decision=data["decisions"].get(key)
        signature=sha256(json.dumps(sorted(f["id"] for f in facts)).encode()).hexdigest()
        confirmed=bool(decision and decision.get("signature")==signature and decision.get("fact_id") in {f["id"] for f in facts})
        chosen=next((f for f in facts if confirmed and f["id"]==decision["fact_id"]),None)
        result.append({"key":key,"entity":facts[0]["entity"],"field":facts[0]["field"],"facts":facts,"signature":signature,
                       "status":("자동 기입" if decision.get("method")=="AUTO" else "확인 완료") if confirmed else ("값 충돌" if len(values)>1 else "담당자 확인"),"chosen":chosen})
    return result


def review_gate(slot):
    """규칙이 자동 기입 허용 여부를 결정하며 모델 신뢰도 자체는 승인 근거가 아닙니다."""
    facts=slot["facts"]
    if len({json.dumps(f["value"],ensure_ascii=False,sort_keys=True) for f in facts})>1:
        return ["자료 간 값 충돌"]
    if any(f.get("confidence",0)<0.95 for f in facts):
        return ["출처 또는 추출 신뢰도 부족"]
    if any(f.get("method")!="table" for f in facts):
        return ["문장 또는 AI 추출값"]
    if slot["field"]!="name" or not slot["entity"].startswith("facility:"):
        return ["운전·물질·법적 판단에 영향 가능한 항목"]
    if any(not str(f["value"]).strip() for f in facts):
        return ["빈 명칭"]
    return []


def auto_approve_safe(project):
    data=graph(project); count=0
    for slot in slots(project):
        if slot["chosen"] or review_gate(slot):continue
        data["decisions"][slot["key"]]={"fact_id":slot["facts"][0]["id"],"signature":slot["signature"],"method":"AUTO"}
        count+=1
    if count:_store(project,data)
    return count


def approve(project,key,fact_id):
    slot=next(s for s in slots(project) if s["key"]==key)
    fact=next(f for f in slot["facts"] if f["id"]==fact_id)
    value=fact["value"]
    if slot["field"] not in {"name","product","cas"}:
        if not isinstance(value,(int,float)) or not math.isfinite(value): raise ValueError("범위·단위·수식을 먼저 확인하고 명확한 값을 추가하세요.")
        if slot["field"]!="temperature" and value<0: raise ValueError("음수 값을 확인하세요.")
        if slot["field"]=="concentration" and value>100: raise ValueError("함량은 0~100%로 확인하세요.")
    if slot["field"]=="cas":
        digits=re.sub(r"\D","",str(value))
        if not re.fullmatch(r"\d{2,7}-\d{2}-\d",str(value)) or sum(int(n)*(i+1) for i,n in enumerate(digits[-2::-1]))%10!=int(digits[-1]):
            raise ValueError("CAS 형식 또는 검산값이 맞지 않습니다.")
    data=graph(project); data["decisions"][key]={"fact_id":fact_id,"signature":slot["signature"],"method":"PERSON"}
    _invalidate(project); _store(project,data)


def confirmed_entities(project):
    entities={}
    for slot in slots(project):
        if slot["chosen"]: entities.setdefault(slot["entity"],{})[slot["field"]]=slot["chosen"]["value"]
    return entities


def add_manual(project,entity,field,value,reason):
    if not entity.startswith(("facility:","material:")) or field not in LABELS or not reason.strip():
        raise ValueError("대상 식별번호·항목·확인 근거를 입력하세요.")
    data=graph(project)
    header=LABELS[field]
    fact={"entity":entity,"kind":entity.split(":",1)[0],"field":field,"value":normalize_value(field,value,header),
          "raw":str(value),"header":header,"document":"담당자 입력","sha256":sha256(reason.encode()).hexdigest(),"location":reason.strip(),"method":"manual","confidence":0.9}
    fact["id"]=sha256(json.dumps(fact,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24]
    if fact["id"] not in {f["id"] for f in data["facts"]}:data["facts"].append(fact)
    _invalidate(project);_store(project,data)


def tasks(project):
    result=[{"entity":s["entity"],"task":s["status"]+": "+LABELS[s["field"]],"key":s["key"]} for s in slots(project) if not s["chosen"]]
    data=graph(project)
    for doc in data["documents"]:
        if doc["needs_reading"]: result.append({"entity":doc["name"],"task":"OCR 또는 문서 구조 확인 필요" if doc["needs_ocr"] else "문서를 읽었지만 사실을 연결하지 못했습니다. 표·항목 또는 식별 대상을 확인하세요.","key":""})
    all_ids={f["entity"] for f in data["facts"]}
    entities=confirmed_entities(project)
    for identifier in sorted(all_ids):
        if not identifier.startswith("facility:"): continue
        values=entities.get(identifier,{})
        present={s["field"] for s in slots(project) if s["entity"]==identifier}
        for field in ("product","inventory","pressure","temperature"):
            if field not in present: result.append({"entity":identifier,"task":"기본 운전조건 미확인: "+LABELS[field],"key":""})
        if "product" in values:
            matches=[key for key,v in entities.items() if key.startswith("material:") and (v.get("name")==values["product"] or key.split(":",1)[1]==values["product"])]
            if len(matches)!=1: result.append({"entity":identifier,"task":"취급제품과 물질자료를 하나로 연결할 수 없습니다. 제품코드·이름을 확인하세요.","key":""})
    return result


def publishing_plan(project):
    mapping={"name":"물질명","cas":"CAS 번호","concentration":"함량(%)"}
    facilities={"name":"설비명","product":"취급물질","capacity":"용량","pressure":"운전압력(MPa)",
                "design_pressure":"설계압력(MPa)","temperature":"운전온도(℃)","inventory":"최대보유량(kg)"}
    plans={}
    for kind,target,columns in [("material","inventory.chemicals",mapping),("facility","inventory.facilities",facilities)]:
        rows=[]
        for identifier,values in confirmed_entities(project).items():
            if identifier.startswith(kind+":"):
                row={columns[k]:v for k,v in values.items() if k in columns}
                row["물질코드" if kind=="material" else "시설번호"]=identifier.split(":",1)[1]
                if kind=="facility":
                    row["설비번호"]=identifier.split(":",1)[1]
                    if 'capacity' in values:row['용량단위']='m3'
                    if 'name' in values:row['시설명']=values['name']
                    matches=[v for k,v in confirmed_entities(project).items() if k.startswith('material:') and (v.get('name')==values.get('product') or k.split(':',1)[1]==values.get('product'))]
                    if len(matches)==1:
                        row['취급물질']=matches[0].get('name',values.get('product',''))
                        row['제품명']=row['취급물질']
                        if 'cas' in matches[0]:row['CAS 번호']=matches[0]['cas']
                rows.append(row)
        if rows: plans[target]=rows
    return plans


def publish(project, *, replace_existing=False):
    plans=publishing_plan(project)
    if not plans: raise ValueError("연결할 확인 완료 사실이 없습니다.")
    for key,rows in plans.items():
        existing=project.get_field(key)
        if existing and existing.value!=rows and not replace_existing:
            raise ValueError("기존 작성자료와 다릅니다. 비교 후 교체 항목을 확인하세요.")
    for key,rows in plans.items():
        project.set_field(key,"공통정보에서 연결한 "+key,rows,"USER_CONFIRMED",note="공통정보 연결: 출처와 필드별 결정은 workspace.evidence_graph에 보존")
    return list(plans)


def report(project):
    lines=["# 사업장 공통정보 검토", "", project.company_name, "", "## 확인한 사실"]
    for slot in slots(project):
        if slot["chosen"]:
            f=slot["chosen"]; lines.append(f"- {slot['entity']} / {LABELS[slot['field']]}: {f['value']} ({f['document']} · {f['location']} · SHA256 {f['sha256']})")
    lines += ["", "## 남은 확인 과제"]+[f"- {t['entity']}: {t['task']}" for t in tasks(project)]
    from .scenario_triage import evaluate
    triage=evaluate(project)
    lines += ["", "## 물질×설비 예비 검토 순서", "",triage["method"]]
    for row in triage["rows"]:
        lines.append(f"- {row['facility']} × {row['material']}: 순위 {row['rank'] if row['rank'] is not None else '취급 관계 미확인'}, 지표 {row['score']:g}, 상태 {row['state']}, 가정 {', '.join(row['assumptions']) or '없음'}, 보류 {', '.join(row['blockers']) or '없음'}")
    lines += ["", "## 순위를 바꾸는 결측 질문"]+[f"- {q['facility']} × {q['material']}: {q['question']}" for q in triage["questions"]]
    lines += ["", "이 문서는 자료 검토용입니다. 기본 운전조건 외의 시나리오 선정조건·안전설비·누출조건·물성·계산모델은 기존 계산 화면에서 별도로 검토합니다."]
    return "\n".join(lines)


def scenario_packets(project):
    packets=[]
    for entity,values in confirmed_entities(project).items():
        if not entity.startswith('facility:'):continue
        packets.append({'설비':entity,'확인한 기본조건':values,
                        '연결된 출처':[{'항목':LABELS[s['field']],'문서':s['chosen']['document'],'위치':s['chosen']['location']} for s in slots(project) if s['entity']==entity and s['chosen']],
                        '자료 확인 과제':[t['task'] for t in tasks(project) if t['entity']==entity],
                        '별도 시나리오 검토':['설비·배관 연결관계와 누출 위치','물성·상태와 적용 모델','누출 크기·지속시간','안전설비·차단 조건','사고유형과 선정 근거'],
                        '상태':'입력 검토용 — 시나리오 선정·계산 미수행'})
    return packets


def demo_zip():
    files={"01_materials.csv":"제품코드,제품명,CAS 번호,함량(%)\nP-01,가상 에탄올 제품,64-17-5,99\n",
           "02_equipment.csv":"설비번호,설비명,취급제품,용량(L),최대보유량(kg),운전압력(kPa),운전온도(C)\nTK-01,가상 저장탱크,가상 에탄올 제품,10000,7000,100,25\n",
           "03_old_equipment.csv":"설비번호,용량(m3)\nTK-01,12\n"}
    buffer=BytesIO()
    with ZipFile(buffer,"w",ZIP_DEFLATED) as z:
        for name,text in files.items(): z.writestr(name,text.encode("utf-8-sig"))
        z.writestr("README.txt","모든 회사·설비·운전값은 가상 시험자료입니다. 물질자료는 material, 설비자료는 facility로 가져오세요. 용량 10m3와 12m3의 충돌을 의도적으로 넣었습니다.")
    return buffer.getvalue()
