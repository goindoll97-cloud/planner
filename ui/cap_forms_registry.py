"""화면이 남아 있는 화학사고예방관리계획서 별지 번호. 나머지 별지는 회사 파일에서 프로그램이 채우므로 입력 화면이 없습니다."""

FORM_NUMBERS = (2,)


def label(number: int) -> str:
    return f"별지 제{number}호"
