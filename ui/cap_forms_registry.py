"""화학사고예방관리계획서 작성 화면이 다루는 별지 번호(별지 제13호는 제12호 화면에서 함께 작성)."""

FORM_NUMBERS = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16)
COMBINED_LABELS = {12: "별지 제12·13호"}


def label(number: int) -> str:
    return COMBINED_LABELS.get(number, f"별지 제{number}호")
