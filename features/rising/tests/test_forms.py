"""Form của Rising star: kiểm truy vấn theo dõi cùng luật với ô Quét, và bộ lọc báo cáo."""

from datetime import date
from typing import Any

import pytest

from features.rising.forms import ReportFilterForm, WatchQueryForm
from features.rising.models import WatchQuery

pytestmark = pytest.mark.django_db

# Ô lọc nhóm (F-010) để trống.
NO_GROUPS: dict[str, list[str]] = {"audience": [], "aspects": []}
NO_PAGES: dict[str, None] = {"page": None, "upage": None}

VALID: dict[str, Any] = {
    "label": "Video AI",
    "query": "topic:ai-video",
    "min_stars": "10",
    "max_stars": "",
    "budget": "300",
    "enabled": "on",
    "position": "1",
}


def make_form(**changes: Any) -> WatchQueryForm:
    return WatchQueryForm(data={**VALID, **changes})


def test_valid_watch_query_is_saved_with_integer_budget() -> None:
    form = make_form(query="  topic:ai-video  ", max_stars="500")

    assert form.is_valid(), form.errors
    watch = form.save()

    assert (watch.label, watch.query, watch.min_stars, watch.max_stars) == (
        "Video AI",
        "topic:ai-video",
        10,
        500,
    )
    assert (watch.budget, watch.enabled, watch.position) == (300, True, 1)
    assert WatchQuery.objects.filter(pk=watch.pk).exists()


def test_unchecked_enabled_box_disables_the_query() -> None:
    data = {key: value for key, value in VALID.items() if key != "enabled"}

    form = WatchQueryForm(data=data)

    assert form.is_valid(), form.errors
    assert form.save().enabled is False


@pytest.mark.parametrize(
    ("query", "hint"),
    [
        ("topic:ai-agent Stars:>5", "Star tối thiểu"),
        ("topic:ai-agent created:>2025-01-01", "ngày"),
        ("topic:ai-agent SORT:updated", "sắp theo star"),
    ],
)
def test_forbidden_qualifier_rejected_same_rule_as_scan_box(query: str, hint: str) -> None:
    form = make_form(query=query)

    assert not form.is_valid()
    assert hint in form.errors["query"][0]


@pytest.mark.parametrize("field", ["label", "query"])
def test_blank_label_or_query_rejected(field: str) -> None:
    form = make_form(**{field: "   "})

    assert not form.is_valid()
    assert list(form.errors) == [field]


def test_max_below_min_rejected() -> None:
    form = make_form(min_stars="100", max_stars="50")

    assert not form.is_valid()
    assert form.errors["max_stars"] == ["Star tối đa phải lớn hơn hoặc bằng Star tối thiểu."]


def test_max_equal_to_min_is_allowed() -> None:
    assert make_form(min_stars="100", max_stars="100").is_valid()


def test_budget_must_be_one_of_the_scan_levels() -> None:
    form = make_form(budget="123")

    assert not form.is_valid()
    assert "budget" in form.errors


def test_new_form_starts_from_the_usual_defaults() -> None:
    form = WatchQueryForm(initial={"position": 17})

    assert form["budget"].value() == 300
    assert form["min_stars"].value() == 10
    assert form["enabled"].value() is True
    assert form["position"].value() == 17


def test_report_filter_defaults_when_empty() -> None:
    form = ReportFilterForm(data={"max_stars": "", "min_gain": "", "day": ""})

    assert form.is_valid(), form.errors
    expected = {
        "max_stars": 1000,
        "min_gain": 50,
        "day": None,
        "sort": "potential",
        **NO_GROUPS,
        **NO_PAGES,
    }
    assert form.cleaned_data == expected


def test_report_filter_reads_values_including_zero_gain() -> None:
    form = ReportFilterForm(data={"max_stars": "500", "min_gain": "0", "day": "2026-10-21"})

    assert form.is_valid(), form.errors
    assert form.cleaned_data == {
        "max_stars": 500,
        "min_gain": 0,
        "day": date(2026, 10, 21),
        "sort": "potential",
        **NO_GROUPS,
        **NO_PAGES,
    }


def test_report_filter_values_keep_the_valid_fields_when_another_is_wrong() -> None:
    wrong_gain = ReportFilterForm(data={"max_stars": "500", "min_gain": "-5", "day": "2026-10-21"})
    wrong_day = ReportFilterForm(data={"max_stars": "500", "min_gain": "70", "day": "hôm qua"})
    unbound = ReportFilterForm()

    assert wrong_gain.values() == (500, 50, date(2026, 10, 21))
    assert wrong_day.values() == (500, 70, None)
    assert unbound.values() == (1000, 50, None)


@pytest.mark.parametrize(
    ("data", "field"),
    [
        ({"max_stars": "0"}, "max_stars"),
        ({"max_stars": "nhiều"}, "max_stars"),
        ({"min_gain": "-1"}, "min_gain"),
        ({"day": "hôm qua"}, "day"),
    ],
)
def test_report_filter_rejects_bad_values(data: dict[str, str], field: str) -> None:
    form = ReportFilterForm(data=data)

    assert not form.is_valid()
    assert list(form.errors) == [field]


def test_report_sort_defaults_to_potential_and_rejects_unknown_values() -> None:
    gain = ReportFilterForm(data={"sort": "gain"})
    unknown = ReportFilterForm(data={"sort": "stars"})

    assert gain.sort_order() == "gain"
    assert unknown.sort_order() == "potential"
    assert "sort" in unknown.errors
    assert ReportFilterForm().sort_order() == "potential"


def test_report_filter_pages_default_to_first_and_reject_bad_numbers() -> None:
    assert ReportFilterForm().pages() == (1, 1)
    assert ReportFilterForm(data={"page": "3", "upage": "2"}).pages() == (3, 2)
    wrong = ReportFilterForm(data={"page": "0", "upage": "abc", "min_gain": "70"})

    assert wrong.pages() == (1, 1)
    assert set(wrong.errors) == {"page", "upage"}  # số trang sai vẫn báo, không im lặng
    assert wrong.values()[1] == 70  # ô lọc hợp lệ khác vẫn giữ
