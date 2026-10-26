"""Form lọc của trang Kho repo (GET). Ô sai thì bỏ qua ô đó (vẫn báo lỗi), trang không hỏng."""

from typing import Any

from django import forms

from features.browse.services import SORT_STARS, SORTS, BrowseFilters
from features.taxonomy.services import load_taxonomy


def _choices(axis: str) -> list[tuple[str, str]]:
    taxonomy = load_taxonomy()
    categories = taxonomy.audience if axis == "audience" else taxonomy.aspects
    return [(category.code, category.name) for category in categories]


class BrowseForm(forms.Form):
    audience = forms.MultipleChoiceField(label="Dành cho ai", required=False, choices=())
    aspects = forms.MultipleChoiceField(label="Làm được gì", required=False, choices=())
    q = forms.CharField(label="Từ khoá", required=False, max_length=100)
    language = forms.CharField(label="Ngôn ngữ", required=False, max_length=100)
    # Giới hạn trên: số quá lớn làm tràn ngày tháng / số nguyên của SQLite (lỗi 500).
    min_stars = forms.IntegerField(
        label="Star tối thiểu", required=False, min_value=0, max_value=10**9
    )
    max_stars = forms.IntegerField(
        label="Star tối đa", required=False, min_value=0, max_value=10**9
    )
    created_days = forms.IntegerField(
        label="Tạo trong (ngày)", required=False, min_value=1, max_value=36500
    )
    rising_only = forms.BooleanField(label="Chỉ rising star (báo cáo mới nhất)", required=False)
    commercial = forms.BooleanField(label="Giấy phép cho phép dùng thương mại", required=False)
    unclassified = forms.BooleanField(label="Chỉ repo chưa phân loại", required=False)
    show_suspicious = forms.BooleanField(label="Hiện cả repo nghi star giả", required=False)
    scan = forms.IntegerField(
        required=False, min_value=1, max_value=10**9, widget=forms.HiddenInput
    )
    sort = forms.ChoiceField(label="Sắp theo", required=False, choices=list(SORTS.items()))
    page = forms.IntegerField(
        required=False, min_value=1, max_value=10**6, widget=forms.HiddenInput
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Đọc bộ nhóm lúc tạo form, không lúc import (bộ nhóm được nạp một lần mỗi lần mở app:
        # sửa categories.toml thì khởi động lại app).
        self.fields["audience"].choices = _choices("audience")  # type: ignore[attr-defined]
        self.fields["aspects"].choices = _choices("aspects")  # type: ignore[attr-defined]

    def filters(self) -> BrowseFilters:
        """Bộ lọc từ các ô hợp lệ; ô sai hoặc để trống thì không lọc theo ô đó."""
        if not self.is_bound:
            return BrowseFilters()
        self.is_valid()
        data = self.cleaned_data
        return BrowseFilters(
            audience=tuple(data.get("audience") or ()),
            aspects=tuple(data.get("aspects") or ()),
            q=(data.get("q") or "").strip(),
            language=(data.get("language") or "").strip(),
            min_stars=data.get("min_stars"),
            max_stars=data.get("max_stars"),
            created_days=data.get("created_days"),
            rising_only=bool(data.get("rising_only")),
            commercial=bool(data.get("commercial")),
            unclassified=bool(data.get("unclassified")),
            show_suspicious=bool(data.get("show_suspicious")),
            scan=data.get("scan"),
            sort=data.get("sort") or SORT_STARS,
            page=data.get("page") or 1,
        )
