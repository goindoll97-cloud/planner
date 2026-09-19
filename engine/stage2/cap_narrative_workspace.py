from __future__ import annotations

"""화학사고예방관리계획서 서술형 항목(사전관리방침·내부 비상대응계획·외부 비상대응계획).

공정안전보고서와 같은 방식이다: 사람은 회사만 아는 결정 사항을 적고(예시에서 고를 수 있다), 글은 확정된 사실로 AI가 초안을 쓰며,
담당자가 확인·승인해야 보고서에 들어간다. 외부 비상대응계획은 1군 사업장만 작성하므로 그 항목과 사실은 2군에는 나타나지 않는다.
"""

from .intake import selected_requirement_specs
from .psm_narrative_workspace import BASIC_FACTS, Fact, Profile

SYSTEM = "CAP"
CONTACT_ITEM = "cap.prevention.emergency_contact"  # 연락처 표라서 AI 초안 대상이 아니다
SECTIONS = ("3.4", "3.5", "3.6")
EXTERNAL_SECTION = "3.6"


def _fact(key: str, label: str, help_text: str, *fields: tuple[str, str, str]) -> Fact:
    return Fact(f"cap.facts.{key}", label, help_text, fields=tuple(fields))


DECISION_FACTS = (
    _fact("safety_management", "안전관리 운영", "화학사고를 예방하기 위해 회사가 안전관리를 어떻게 운영하는지입니다.",
          ("책임자", "안전관리 책임자", "안전관리를 책임지는 직책입니다."),
          ("조직", "안전관리 조직", "안전을 맡는 부서와 역할 분담입니다."),
          ("회의", "안전 점검 회의", "안전을 논의하는 회의와 그 주기입니다.")),
    _fact("training", "화학사고 대비 교육·훈련", "화학사고에 대비해 하는 교육과 훈련입니다.",
          ("대상", "교육 대상", "교육을 받는 사람입니다."), ("주기", "교육 주기", "얼마나 자주 하는지입니다."),
          ("방법", "교육 방법", "어떻게 교육하는지입니다.")),
    _fact("self_inspection", "자체점검", "회사가 스스로 하는 점검입니다.",
          ("대상", "점검 대상", "점검하는 설비와 시설입니다."), ("주기", "점검 주기", "얼마나 자주 점검하는지입니다."),
          ("방법", "점검 방법", "점검하고 기록하는 방법입니다.")),
    _fact("change_management", "변경관리", "설비, 물질, 절차가 바뀔 때 어떻게 관리하는지입니다.",
          ("절차", "변경 절차", "변경을 요청하고 검토·승인하는 순서입니다."), ("담당", "변경 담당", "변경을 검토하고 승인하는 사람입니다."),
          ("기록", "변경 기록", "변경 내용을 어떻게 기록·보관하는지입니다.")),
    _fact("emergency_org", "비상대응조직", "사고가 났을 때 움직이는 조직입니다.",
          ("총괄", "비상 총괄", "비상 상황을 지휘하는 직책입니다."), ("대응반", "대응반 구성", "대응반과 각 반의 역할입니다."),
          ("교대", "야간·휴일 대응", "야간이나 휴일에는 누가 맡는지 적습니다.")),
    _fact("command_center", "비상통제실", "사고가 났을 때 지휘하는 장소와 운영 방법입니다.",
          ("위치", "위치", "비상통제실이 있는 곳입니다."), ("운영", "운영 방법", "어떻게 운영하는지입니다."),
          ("담당", "담당자", "운영을 맡는 사람입니다.")),
    _fact("shutdown", "가동중지 권한과 방법", "사고나 이상이 있을 때 설비를 멈추는 권한과 방법입니다.",
          ("권한자", "정지 권한자", "설비를 정지할 수 있는 사람입니다."), ("판단기준", "정지 판단 기준", "어떤 상황에서 정지하는지입니다."),
          ("방법", "정지 방법", "어떻게 정지하는지입니다.")),
    _fact("communication", "사내 정보전달", "사고 사실을 사업장 안에서 알리는 방법입니다.",
          ("수단", "전달 수단", "쓰는 설비나 수단입니다."), ("방법", "전달 방법", "누가 누구에게 어떻게 알리는지입니다."),
          ("담당", "담당자", "전파를 맡는 사람입니다.")),
    _fact("recovery", "사고복구", "사고가 난 뒤 복구하는 방법입니다.",
          ("책임", "복구 책임", "복구를 맡는 사람이나 부서입니다."), ("순서", "복구 순서", "복구하는 순서입니다."),
          ("환경조치", "환경 조치", "누출 물질 처리 등 환경 관련 조치입니다.")),
    _fact("investigation", "사고원인 조사와 재발방지", "사고 원인을 조사하고 재발을 막는 방법입니다.",
          ("책임", "조사 책임", "조사를 맡는 사람이나 부서입니다."), ("방법", "조사 방법", "원인을 찾는 방법입니다."),
          ("재발방지", "재발방지 조치", "재발을 막기 위한 조치입니다.")),
    _fact("community", "지역사회 소통(1군)", "지역사회와 소통하는 방법입니다.",
          ("대상", "소통 대상", "소통하는 대상입니다."), ("방법", "소통 방법", "어떻게 소통하는지입니다."),
          ("주기", "소통 주기", "얼마나 자주 하는지입니다.")),
    _fact("mutual_aid", "지역 기관·인근 사업장 공조(1군)", "사고 때 도움을 주고받는 기관과 사업장입니다.",
          ("기관", "협력 기관", "협력하는 기관이나 사업장입니다."), ("협력내용", "협력 내용", "서로 어떤 도움을 주는지입니다."),
          ("합동훈련", "합동 훈련", "함께 하는 훈련입니다.")),
    _fact("evacuation", "주민 보호·대피(1군)", "사고가 났을 때 주민을 보호하고 대피시키는 방법입니다.",
          ("경보", "경보 방법", "주민에게 위험을 알리는 방법입니다."), ("경로", "대피 경로", "어느 방향으로 대피하는지입니다."),
          ("장소", "대피 장소", "대피하는 장소입니다.")),
    _fact("public_notice", "지역사회 고지(1군)", "사고가 났을 때 주민에게 알리는 방법입니다.",
          ("대상", "고지 대상", "알리는 대상입니다."), ("방법", "고지 방법", "어떻게 알리는지입니다."),
          ("내용", "고지 내용", "무엇을 알리는지입니다.")),
)
EXTERNAL_FACT_KEYS = {"cap.facts.community", "cap.facts.mutual_aid", "cap.facts.evacuation", "cap.facts.public_notice"}


def items(project) -> tuple[str, ...]:
    """이 사업장(1군/2군)에서 작성하는 서술형 항목 키. 연락처 표 항목은 제외한다."""
    return tuple(spec.key for spec in selected_requirement_specs(project)
                 if spec.system == SYSTEM and spec.section.startswith(SECTIONS) and spec.key != CONTACT_ITEM)


def includes_external(project) -> bool:
    return any(spec.section.startswith(EXTERNAL_SECTION) for spec in selected_requirement_specs(project)
               if spec.system == SYSTEM)


def visible_facts(project) -> tuple[Fact, ...]:
    external = includes_external(project)
    return tuple(f for f in DECISION_FACTS if external or f.key not in EXTERNAL_FACT_KEYS)


CAP_PROFILE = Profile(SYSTEM, BASIC_FACTS, DECISION_FACTS, items)
