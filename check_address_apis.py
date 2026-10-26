#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""planner 실제 주소 조회 진단. app.py / engine / .env가 있는 폴더에서 실행.

    python check_address_apis.py
    python check_address_apis.py --address "도로명주소" --provider kakao
    python check_address_apis.py --address "도로명주소" --provider ngii --keyword "인근 학교의 정확한 이름"

프로젝트의 기존 조회 함수를 호출합니다. 프로젝트 자료와 .env를 수정하지 않습니다.
키 자체, 인증 헤더, 원시 API 응답과 예외 메시지는 출력하지 않습니다.
LAW_OC / KOSHA_MSDS_SERVICE_KEY는 설정 유무만 확인하며 API 호출은 하지 않습니다.
결과 JSON은 별도 파일로 저장합니다. 주소점 주변 참고 후보이며 법정 조사 완료를 뜻하지 않습니다.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import importlib
import json
import math
import os
from pathlib import Path
import sys
from urllib.parse import quote, quote_plus


KEY_GROUPS = {
    "LAW_OC (설정만 확인)": ("LAW_OC",),
    "KOSHA_MSDS_SERVICE_KEY (설정만 확인)": ("KOSHA_MSDS_SERVICE_KEY",),
    "KAKAO_REST_API_KEY": ("KAKAO_REST_API_KEY",),
    "브이월드 키": ("VWORLD_API_KEY", "v_world_key", "VWORLD_KEY"),
    "VWORLD_DOMAIN (등록한 서비스 URL)": ("VWORLD_DOMAIN",),
    "NGII_API_KEY": ("NGII_API_KEY",),
    "NGII_REFERRER_URL": ("NGII_REFERRER_URL",),
}


def redact(text: str) -> str:
    # 오류와 저장자료에 키가 섞여 나오는 경우도 마스킹합니다.
    secrets = {
        os.environ.get(key, "").strip()
        for keys in KEY_GROUPS.values() for key in keys
        if key not in ("NGII_REFERRER_URL", "VWORLD_DOMAIN")
    } - {""}
    for secret in sorted(secrets, key=len, reverse=True):
        for form in {secret, quote(secret, safe=""), quote_plus(secret)}:
            text = text.replace(form, "[KEY_REDACTED]")
    return text


def say(text: str) -> None:
    print(redact(text), flush=True)


def vworld_trace_getter(module, lat: float, lon: float, domain: str, traces: list):
    """기존 조회조건은 유지하며 레이어별 응답/제외 건수를 기록합니다."""
    def get(params):
        request_params = dict(params)
        if domain:
            request_params["domain"] = domain
        layer = str(params.get("data", ""))
        trace = {"layer": layer, "page": params.get("page"),
                 "api_status": "NOT_RECEIVED", "raw_feature_count": 0,
                 "within_radius_count": 0, "unnamed_within_radius_count": 0,
                 "outside_radius_count": 0, "unreadable_geometry_count": 0}
        traces.append(trace)
        try:
            payload = module._default_get(request_params)
        except Exception as exc:
            trace["exception_type"] = type(exc).__name__
            # 키가 담길 수 있는 요청 URL과 예외 원문은 저장하지 않습니다.
            raise
        body = payload.get("response", {}) if isinstance(payload, dict) else {}
        if not isinstance(body, dict):
            trace["api_status"] = "UNEXPECTED_RESPONSE"
            return payload
        trace["api_status"] = str(body.get("status", "UNKNOWN"))[:80]
        error = body.get("error") or {}
        if isinstance(error, dict):
            trace["error_code"] = str(error.get("code", ""))[:80]
            # 공식 오류문은 잘못된 파라미터명과 유효범위를 포함합니다.
            trace["error_text"] = redact(str(error.get("text", "")))[:1200]
        record = body.get("record")
        if isinstance(record, dict):
            trace["server_total"] = str(record.get("total", ""))[:40]
            trace["server_current"] = str(record.get("current", ""))[:40]
        data_result = body.get("result") or {}
        collection = (data_result.get("featureCollection") or {}) if isinstance(data_result, dict) else {}
        features = collection.get("features") if isinstance(collection, dict) else None
        if not isinstance(features, list):
            return payload
        trace["raw_feature_count"] = len(features)
        fields = next((entry[2] for entry in module.LAYERS if entry[0] == layer), ())
        trace["name_fields_used_by_planner"] = list(fields)
        trace["sample_property_keys"] = []
        trace["geometry_types"] = []
        for feature in features:
            if not isinstance(feature, dict):
                trace["unreadable_geometry_count"] += 1
                continue
            properties = feature.get("properties") or {}
            geometry = feature.get("geometry") or {}
            if not isinstance(properties, dict):
                properties = {}
            if len(trace["sample_property_keys"]) < 3:
                trace["sample_property_keys"].append(sorted(str(key) for key in properties))
            geometry_type = str(geometry.get("type", "missing")) if isinstance(geometry, dict) else "invalid"
            if geometry_type not in trace["geometry_types"]:
                trace["geometry_types"].append(geometry_type)
            try:
                distance = module._geometry_distance(lat, lon, geometry)
                if not math.isfinite(distance):
                    trace["unreadable_geometry_count"] += 1
                elif distance > module.SEARCH_RADIUS_M:
                    trace["outside_radius_count"] += 1
                else:
                    trace["within_radius_count"] += 1
                    if not any(properties.get(field) and str(properties[field]).strip() for field in fields):
                        trace["unnamed_within_radius_count"] += 1
            except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError):
                trace["unreadable_geometry_count"] += 1
        return payload
    return get


def load_backend(root: Path):
    if not (root / "app.py").is_file() or not (root / "engine" / "stage2").is_dir():
        raise FileNotFoundError
    # 파일 위치 또는 --project-root를 기준으로 다른 폴더의 .env를 읽지 않도록 합니다.
    os.chdir(root)
    sys.path.insert(0, str(root))
    msds = importlib.import_module("engine.kosha_msds")
    msds._load_local_env()
    return {
        name: importlib.import_module("engine.stage2." + module)
        for name, module in {
            "kakao": "cap_site_lookup",
            "vworld": "cap_vworld_lookup",
            "ngii": "cap_ngii_lookup",
        }.items()
    }


def show_result(result: dict) -> None:
    say(f"  상태: {result['status']} / 후보 {len(result.get('candidates', []))}건")
    if result.get("coordinate"):
        point = result["coordinate"]
        say(f"  주소 좌표: 경도 {point['lon']}, 위도 {point['lat']} ({point['source']})")
    for note in result.get("notices", []):
        say("  안내: " + str(note))
    for trace in result.get("vworld_trace", [])[:30]:
        say(f"  레이어 {trace['layer']} / 페이지 {trace['page']}: {trace['api_status']} / "
            f"API 원자료 {trace['raw_feature_count']}건 / 반경 내 {trace['within_radius_count']}건 / "
            f"그중 이름 미인식 {trace['unnamed_within_radius_count']}건 / "
            f"도형 해석 불가 {trace['unreadable_geometry_count']}건")
        if trace.get("error_code"):
            say(f"    오류 {trace['error_code']}: {trace.get('error_text', '')}")
    if len(result.get("vworld_trace", [])) > 30:
        say("  나머지 레이어 요청 기록은 결과 JSON에서 확인하세요.")
    for row in result.get("candidates", [])[:10]:
        distance = row.get("distance_m")
        say(f"  - {row.get('name', '')} | {distance if distance is not None else '미확인'} m | {row.get('address', '')}")
    if len(result.get("candidates", [])) > 10:
        say("  나머지 후보는 결과 JSON에 저장합니다.")


def run_provider(name: str, backend: dict, address: str, keywords: list[str]) -> dict:
    result = {"provider": name, "status": "NOT_RUN", "notices": [], "candidates": []}
    module = backend[name]
    try:
        if name == "ngii":
            if not all(module.config()):
                result.update(status="NOT_CONFIGURED", notices=[
                    "NGII_API_KEY와 발급 시 등록한 NGII_REFERRER_URL이 모두 필요합니다."])
                return result
            if not keywords:
                result.update(status="SKIPPED", notices=[
                    "--keyword로 인근 시설의 정확한 이름을 지정하세요. 전국 키워드 검색이므로 일반적인 '학교' 검색은 근처 시설을 놓칠 수 있습니다."])
                return result
            rows, notes = module.search(address, keywords)
        else:
            if not module.api_key():
                result.update(status="NOT_CONFIGURED", notices=["이 서비스의 키가 설정되지 않았습니다."])
                return result
            point = module.geocode(address)
            if point is not None:
                lon, lat = map(float, point)
                result["coordinate"] = {"lon": lon, "lat": lat, "source": name}
            if name == "kakao":
                # 기존 함수가 자체 주소 조회와 각 카테고리/키워드의 페이지 조회를 수행합니다.
                rows, note = module.find_candidates(address)
                notes = [note]
            else:
                if point is None:
                    # 브이월드 주소 변환과 레이어 조회의 실패를 구분할 수 있게 합니다.
                    result["notices"].append("브이월드 주소 변환 결과가 없습니다. 카카오 좌표로 레이어 조회를 시도합니다.")
                    point = backend["kakao"].geocode(address)
                    if point is None:
                        result.update(status="NO_COORDINATE")
                        return result
                    lon, lat = map(float, point)
                    result["coordinate"] = {"lon": lon, "lat": lat, "source": "kakao fallback"}
                domain = os.environ.get("VWORLD_DOMAIN", "").strip()
                result["domain_parameter_applied"] = bool(domain)
                result["vworld_trace"] = []
                traced_get = vworld_trace_getter(module, lat, lon, domain, result["vworld_trace"])
                rows, notes = module.search(lat, lon, get=traced_get)
                if domain:
                    result["notices"].append("브이월드 2D 데이터 요청에 VWORLD_DOMAIN 설정값을 전달했습니다 (.env 또는 현재 프로세스 환경변수).")
                else:
                    result["notices"].append("VWORLD_DOMAIN이 없습니다. 등록한 서비스 URL과 도메인 파라미터를 확인하세요.")
        result["candidates"] = [asdict(row) for row in rows]
        result["notices"].extend(notes)
        # 일부 레이어 실패나 조회 한도가 있어도 후보가 있을 수 있습니다.
        # 통신/인증 성공 또는 전체 조사 완료라는 의미의 PASS를 부여하지 않습니다.
        result["status"] = "CANDIDATES_RETURNED_REVIEW_NOTICES" if rows else "NO_CANDIDATES_REVIEW_NOTICES"
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        response = getattr(exc, "response", None)
        result["status"] = "ERROR"
        result["notices"].append("예외 유형: " + type(exc).__name__)
        if response is not None:
            result["notices"].append("HTTP 상태: " + str(response.status_code))
        result["notices"].append("키/등록 주소/승인된 API/네트워크와 로컬 코드 버전을 확인하세요. 원시 오류는 키 보호를 위해 표시하지 않습니다.")
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="planner의 카카오/브이월드/NGII 실제 주소 조회 진단")
    parser.add_argument("--address", help="시험할 실제 도로명주소")
    parser.add_argument("--keyword", action="append", default=[], help="NGII에서 검색할 정확한 인근 시설명. 반복 지정 가능")
    parser.add_argument("--provider", choices=["all", "kakao", "vworld", "ngii"], default="all")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, help="결과 JSON 경로. 기본값은 실행시각을 붙인 새 파일")
    args = parser.parse_args()
    root = args.project_root.expanduser().resolve()
    try:
        backend = load_backend(root)
    except FileNotFoundError:
        say("이 파일을 planner의 app.py와 같은 폴더에 놓으세요. 또는 --project-root로 planner 폴더를 지정하세요.")
        return 2
    except Exception as exc:
        say("프로젝트 모듈을 불러오지 못했습니다. 오류 유형: " + type(exc).__name__)
        say("planner 폴더에서 python -m pip install -r requirements.txt 실행 후 다시 시도하세요.")
        return 2
    say("주소 조회 진단 v3: 키 값은 표시하지 않습니다. 브이월드 레이어별 원자료/필터 제외 건수를 기록합니다.")
    say(".env 존재: " + ("예" if (root / ".env").is_file() else "아니오 (.env.txt인지도 확인하세요)"))
    present = {}
    for label, aliases in KEY_GROUPS.items():
        present[label] = any(os.environ.get(k, "").strip() for k in aliases)
        say(f"  {label}: {'설정됨' if present[label] else '미설정'}")
    address = (args.address or input("\n시험할 도로명주소: ")).strip()
    if not address:
        say("주소가 비어 있습니다.")
        return 2
    keywords = [item.strip() for item in args.keyword if item.strip()]
    if args.address is None and args.provider in ("all", "ngii") and not keywords:
        item = input("인근 시설의 정확한 이름 (NGII 시험용, 모르면 Enter): ").strip()
        if item:
            keywords = [item]
    selected = ["kakao", "vworld", "ngii"] if args.provider == "all" else [args.provider]
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "diagnostic_version": 3,
        "address": address, "ngii_keywords": keywords, "key_presence_only": present,
        "scope": "기존 코드의 주소점 800m 주변 후보 조회. 사업장 경계/사고 영향범위 분석이나 논·밭 전수조사 검증이 아님.",
        "results": [],
    }
    say("\n후보가 검색되어도 모든 레이어/API의 성공을 뜻하지 않습니다. 안내문을 함께 확인하세요.")
    try:
        for name in selected:
            say(f"\n[{name}] 실제 조회 중입니다. 여러 요청으로 수 분 걸릴 수 있습니다 (중단: Ctrl+C).")
            result = run_provider(name, backend, address, keywords)
            report["results"].append(result)
            show_result(result)
    except KeyboardInterrupt:
        say("\n조회 중단. 완료된 서비스의 결과만 저장합니다.")
        report["interrupted"] = True
    output = args.output or Path("address_api_results_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + ".json")
    try:
        with output.open("x", encoding="utf-8") as stream:
            stream.write(redact(json.dumps(report, ensure_ascii=False, indent=2)))
        say("\n결과 파일: " + str(output.resolve()))
    except OSError as exc:
        say("결과 파일 저장 실패: " + type(exc).__name__ + " (기존 파일을 덮어쓰지 않습니다)")
        return 2
    say("LAW/KOSHA는 설정 유무만 확인했습니다. 실제 지도와 시설명·주소·좌표를 대조하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
