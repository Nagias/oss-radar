"""Form của Rising star: kiểm tra dữ liệu nhập TRƯỚC khi lưu truy vấn theo dõi hay lọc báo cáo.

Truy vấn theo dõi được kiểm bằng cùng luật với ô Quét (không tự ghi `stars:`, `created:`, `sort:`).
"""

from datetime import date
from typing import TYPE_CHECKING, Any, ClassVar

from django import forms

from features.discovery.services import BUDGET_CHOICES, forbidden_qualifier_hint
from features.rising.growth import RISING_MAX_STARS, RISING_MIN_GAIN_7D
from features.rising.models import WatchQuery
from features.rising.services import SORT_GAIN, SORT_POTENTIAL
from features.taxonomy.services import load_taxonomy

DEFAULT_WATCH_BUDGET = 300  # mức "Sâu": đủ quét trọn một truy vấn cỡ vài nghìn repo


if TYPE_CHECKING:
    _WatchQueryFormBase = forms.ModelForm[WatchQuery]
else:
    # Lúc chạy `ModelForm[WatchQuery]` không subscript được; chỉ mypy cần biết kiểu.
    _WatchQueryFormBase = forms.ModelForm


class WatchQueryForm(_WatchQueryFormBase):
    budget = forms.TypedChoiceField(
        label="Mức quét",
        choices=BUDGET_CHOICES,
        coerce=int,
        initial=DEFAULT_WATCH_BUDGET,
        help_text="Số lượt gọi GitHub tối đa cho truy vấn này mỗi ngày.",
    )

    class Meta:
        model = WatchQuery
        fields = ("label", "query", "min_stars", "max_stars", "budget", "enabled", "position")
        labels: ClassVar[dict[str, str]] = {"enabled": "Đang bật (quét mỗi ngày)"}
        help_texts: ClassVar[dict[str, str]] = {
            "label": "Mảng của truy vấn, ví dụ: Video AI.",
            "query": "Cú pháp tìm kiếm của GitHub, ví dụ: topic:ai-agent language:python",
            "max_stars": "Để trống = không giới hạn",
            "position": "Truy vấn nhỏ hơn được quét trước.",
        }
        error_messages: ClassVar[dict[str, dict[str, str]]] = {
            "label": {"required": "Hãy nhập nhãn mảng, ví dụ: Video AI."},
            "query": {
                "required": "Hãy nhập truy vấn tìm kiếm GitHub.",
                "max_length": "Truy vấn dài tối đa %(limit_value)d ký tự (giới hạn của GitHub).",
            },
        }

    def clean_query(self) -> str:
        query: str = self.cleaned_data["query"]
        hint = forbidden_qualifier_hint(query)
        if hint is not None:
            raise forms.ValidationError(hint)
        return query

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        min_stars, max_stars = data.get("min_stars"), data.get("max_stars")
        if min_stars is not None and max_stars is not None and max_stars < min_stars:
            self.add_error("max_stars", "Star tối đa phải lớn hơn hoặc bằng Star tối thiểu.")
        return data


class ReportFilterForm(forms.Form):
    """Bộ lọc của trang báo cáo (GET). Ô để trống thì dùng ngưỡng mặc định của rising star."""

    max_stars = forms.IntegerField(
        label="Star tối đa", min_value=1, required=False, initial=RISING_MAX_STARS
    )
    min_gain = forms.IntegerField(
        label="Tăng tối thiểu trong 7 ngày", min_value=0, required=False, initial=RISING_MIN_GAIN_7D
    )
    day = forms.DateField(label="Ngày báo cáo", required=False)
    audience = forms.MultipleChoiceField(label="Dành cho ai", required=False, choices=())
    aspects = forms.MultipleChoiceField(label="Làm được gì", required=False, choices=())
    sort = forms.ChoiceField(
        label="Sắp theo",
        choices=[(SORT_POTENTIAL, "Điểm Tiềm năng"), (SORT_GAIN, "Tăng 7 ngày")],
        required=False,
        initial=SORT_POTENTIAL,
    )

    def values(self) -> tuple[int, int, date | None]:
        """(star tối đa, tăng tối thiểu, ngày) dùng để lọc.

        Ô nào để trống hoặc nhập sai thì dùng mặc định (ô sai vẫn báo lỗi), không làm mất giá trị
        hợp lệ của ô khác — vd ngày đã chọn.
        """
        cleaned: dict[str, Any] = {}
        if self.is_bound:
            self.is_valid()  # chạy kiểm tra: `cleaned_data` chỉ còn các ô hợp lệ
            cleaned = self.cleaned_data
        return (
            cleaned.get("max_stars", RISING_MAX_STARS),
            cleaned.get("min_gain", RISING_MIN_GAIN_7D),
            cleaned.get("day"),
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        taxonomy = load_taxonomy()  # nạp một lần mỗi lần mở app (sửa file → khởi động lại app)
        self.fields["audience"].choices = [(c.code, c.name) for c in taxonomy.audience]  # type: ignore[attr-defined]
        self.fields["aspects"].choices = [(c.code, c.name) for c in taxonomy.aspects]  # type: ignore[attr-defined]

    def groups(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """(nhóm "Dành cho ai", nhóm "Làm được gì") đã chọn; ô có mã lạ thì coi như không chọn."""
        if not self.is_bound:
            return (), ()
        self.is_valid()
        data = self.cleaned_data
        return tuple(data.get("audience") or ()), tuple(data.get("aspects") or ())

    def sort_order(self) -> str:
        """Thứ tự bảng rising star; để trống hoặc giá trị lạ thì theo điểm Tiềm năng."""
        if not self.is_bound:
            return SORT_POTENTIAL
        self.is_valid()
        sort: str = self.cleaned_data.get("sort", SORT_POTENTIAL)
        return sort

    def clean_sort(self) -> str:
        value: str = self.cleaned_data["sort"]
        return value or SORT_POTENTIAL

    def clean_max_stars(self) -> int:
        value: int | None = self.cleaned_data["max_stars"]
        return RISING_MAX_STARS if value is None else value

    def clean_min_gain(self) -> int:
        value: int | None = self.cleaned_data["min_gain"]
        return RISING_MIN_GAIN_7D if value is None else value
