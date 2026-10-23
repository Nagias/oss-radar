"""Form của tính năng Quét: kiểm tra dữ liệu nhập TRƯỚC khi tốn lượt gọi GitHub.

Dùng chung cho trang web và lệnh `manage.py scan` — một chỗ kiểm tra duy nhất.
"""

from datetime import date
from typing import Any

from django import forms
from django.utils import timezone

from features.discovery.services import BUDGET_CHOICES, ScanRequest, forbidden_qualifier_hint
from features.discovery.slicing import EARLIEST_DATE

QUERY_MAX_LENGTH = 256  # Giới hạn độ dài truy vấn của GitHub Search.
DEFAULT_MIN_STARS = 10  # chủ dự án chốt 2026-10-22 (lọc ≥10 star bỏ ~88% repo gần như rỗng)
DEFAULT_BUDGET = 50
_DATE_WIDGET = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class ScanForm(forms.Form):
    query = forms.CharField(
        label="Truy vấn GitHub",
        max_length=QUERY_MAX_LENGTH,
        strip=True,
        help_text="Cú pháp tìm kiếm của GitHub, ví dụ: topic:ai-agent language:python",
        error_messages={
            "required": "Hãy nhập truy vấn tìm kiếm GitHub.",
            "max_length": "Truy vấn dài tối đa %(limit_value)d ký tự (giới hạn của GitHub).",
        },
        widget=forms.TextInput(attrs={"placeholder": "topic:ai-agent", "autofocus": True}),
    )
    min_stars = forms.IntegerField(label="Star tối thiểu", min_value=0, initial=DEFAULT_MIN_STARS)
    max_stars = forms.IntegerField(
        label="Star tối đa", min_value=0, required=False, help_text="Để trống = không giới hạn"
    )
    created_from = forms.DateField(label="Tạo từ ngày", required=False, widget=_DATE_WIDGET)
    created_to = forms.DateField(label="Tạo đến ngày", required=False, widget=_DATE_WIDGET)
    budget = forms.TypedChoiceField(
        label="Mức quét", choices=BUDGET_CHOICES, coerce=int, initial=DEFAULT_BUDGET
    )

    def clean_query(self) -> str:
        query: str = self.cleaned_data["query"]
        hint = forbidden_qualifier_hint(query)
        if hint is not None:
            raise forms.ValidationError(hint)
        return query

    def clean_created_from(self) -> date | None:
        value: date | None = self.cleaned_data["created_from"]
        if value is not None and value < EARLIEST_DATE:
            raise forms.ValidationError("GitHub ra đời năm 2008 — chọn ngày từ 2008-01-01 trở đi.")
        if value is not None and value > timezone.localdate():
            raise forms.ValidationError("Ngày 'từ' không được ở tương lai.")
        return value

    def clean_created_to(self) -> date | None:
        value: date | None = self.cleaned_data["created_to"]
        if value is not None and value > timezone.localdate():
            raise forms.ValidationError("Ngày 'đến' không được ở tương lai.")
        if value is not None and value < EARLIEST_DATE:
            raise forms.ValidationError("GitHub ra đời năm 2008 — ngày 'đến' phải từ 2008-01-01.")
        return value

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        min_stars, max_stars = data.get("min_stars"), data.get("max_stars")
        if min_stars is not None and max_stars is not None and max_stars < min_stars:
            self.add_error("max_stars", "Star tối đa phải lớn hơn hoặc bằng Star tối thiểu.")
        created_from, created_to = data.get("created_from"), data.get("created_to")
        if created_from and created_to and created_to < created_from:
            self.add_error("created_to", "Ngày 'đến' phải bằng hoặc sau ngày 'từ'.")
        return data

    def to_request(self) -> ScanRequest:
        data = self.cleaned_data
        return ScanRequest(
            query=data["query"],
            min_stars=data["min_stars"],
            max_stars=data["max_stars"],
            created_from=data["created_from"],
            created_to=data["created_to"],
            budget=data["budget"],
        )


class ResumeForm(forms.Form):
    extra_budget = forms.TypedChoiceField(
        label="Thêm ngân sách", choices=BUDGET_CHOICES, coerce=int, initial=DEFAULT_BUDGET
    )
