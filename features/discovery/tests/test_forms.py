"""Form quét: kiểm tra dữ liệu nhập TRƯỚC khi tốn một lượt gọi GitHub."""

from datetime import date, timedelta
from typing import Any

import pytest
from django import forms
from django.utils import timezone

from features.discovery import services
from features.discovery.forms import ResumeForm, ScanForm
from features.discovery.services import ScanRequest

VALID: dict[str, Any] = {"query": "topic:ai-agent", "min_stars": "10", "budget": "50"}


def make_form(**changes: Any) -> ScanForm:
    return ScanForm(data={**VALID, **changes})


def test_query_is_trimmed() -> None:
    form = make_form(query="   topic:ai-agent  ")

    assert form.is_valid(), form.errors
    assert form.cleaned_data["query"] == "topic:ai-agent"


@pytest.mark.parametrize("query", ["", "    "])
def test_blank_query_is_rejected_with_vietnamese_message(query: str) -> None:
    form = make_form(query=query)

    assert not form.is_valid()
    assert form.errors["query"] == ["Hãy nhập truy vấn tìm kiếm GitHub."]


def test_query_longer_than_github_limit_is_rejected() -> None:
    form = make_form(query="a" * 257)

    assert not form.is_valid()
    assert "256" in form.errors["query"][0]


@pytest.mark.parametrize(
    ("query", "hint"),
    [
        ("topic:ai-agent Stars:>5", "Star tối thiểu"),
        ("topic:ai-agent created:>2025-01-01", "ngày"),
        ("topic:ai-agent SORT:updated", "sắp theo star"),
    ],
)
def test_forbidden_qualifier_rejected_any_case(query: str, hint: str) -> None:
    form = make_form(query=query)

    assert not form.is_valid()
    assert hint in form.errors["query"][0]


def test_max_below_min_rejected() -> None:
    form = make_form(min_stars="100", max_stars="50")

    assert not form.is_valid()
    assert "Star tối đa" in form.errors["max_stars"][0]


def test_dates_in_wrong_order_rejected() -> None:
    form = make_form(created_from="2026-02-01", created_to="2026-01-01")

    assert not form.is_valid()
    assert "sau" in form.errors["created_to"][0]


def test_future_end_date_rejected() -> None:
    tomorrow = timezone.localdate() + timedelta(days=1)

    form = make_form(created_to=tomorrow.isoformat())

    assert not form.is_valid()
    assert "tương lai" in form.errors["created_to"][0]


def test_future_start_date_rejected_even_without_end_date() -> None:
    tomorrow = timezone.localdate() + timedelta(days=1)

    form = make_form(created_from=tomorrow.isoformat())

    assert not form.is_valid()
    assert "tương lai" in form.errors["created_from"][0]


def test_end_date_before_2008_rejected_even_without_start_date() -> None:
    form = make_form(created_to="2007-12-31")

    assert not form.is_valid()
    assert "2008" in form.errors["created_to"][0]


def test_date_before_2008_rejected() -> None:
    form = make_form(created_from="2007-12-31")

    assert not form.is_valid()
    assert "2008" in form.errors["created_from"][0]


def test_defaults_are_min_10_stars_and_medium_budget() -> None:
    form = ScanForm()

    assert form.fields["min_stars"].initial == 10
    assert form.fields["budget"].initial == 50


def test_budget_must_be_one_of_the_levels() -> None:
    assert not make_form(budget="77").is_valid()


def test_to_request_maps_fields() -> None:
    form = make_form(max_stars="999", created_from="2025-01-01", created_to="2025-06-30")
    assert form.is_valid(), form.errors

    assert form.to_request() == ScanRequest(
        query="topic:ai-agent",
        min_stars=10,
        max_stars=999,
        created_from=date(2025, 1, 1),
        created_to=date(2025, 6, 30),
        budget=50,
    )


def test_budget_levels_come_from_services() -> None:
    budget = make_form().fields["budget"]

    assert isinstance(budget, forms.TypedChoiceField)
    assert budget.choices == list(services.BUDGET_CHOICES)


def test_resume_form_offers_same_levels() -> None:
    assert ResumeForm(data={"extra_budget": "300"}).is_valid()
    assert not ResumeForm(data={"extra_budget": "5"}).is_valid()
