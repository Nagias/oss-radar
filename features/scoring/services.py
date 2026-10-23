"""Nghiệp vụ chấm điểm: gom dữ kiện từ kho → gọi công thức ở `rules.py`; lấy hồ sơ chủ repo.

Tính năng khác chỉ gọi các hàm ở đây. `scoring` không import `rising` hay `discovery`: số tăng star
do bên gọi truyền vào dưới dạng `GrowthFacts` (thiết kế F-006 mục 9). Điểm tính lúc hiển thị,
không lưu; chấm điểm chỉ đọc CSDL, không gọi mạng — gọi GitHub chỉ có ở `fetch_owner_profiles`.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.utils import timezone

from features.catalog import services as catalog
from features.catalog.models import OwnerProfile, Repository
from features.scoring import rules
from features.scoring.rules import GrowthFacts, OwnerFacts, RepoFacts, Score, Suspicion
from integrations.github.client import GitHubClient
from integrations.github.errors import GitHubNotFoundError, GitHubResponseError

logger = logging.getLogger(__name__)

# Hồ sơ chủ repo ít đổi (tuổi tài khoản không đổi; người theo dõi, số repo đổi chậm).
OWNER_PROFILE_MAX_AGE = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class RepoScores:
    quality: Score
    potential: Score | None  # None = chưa có số tăng star
    suspicion: Suspicion


@dataclass(slots=True)
class OwnerFetchOutcome:
    fetched: int = 0
    missing: int = 0
    unreadable: list[tuple[str, str]] = field(default_factory=list)  # (login, lý do)


def repo_facts(repo: Repository) -> RepoFacts:
    return RepoFacts(
        stars=repo.stars,
        forks=repo.forks,
        open_issues=repo.open_issues,
        is_organization=repo.is_organization,
        license_spdx=repo.license_spdx,
        description=repo.description,
        topic_count=len(repo.topics),
        is_archived=repo.is_archived,
        created_at=repo.gh_created_at,
        pushed_at=repo.gh_pushed_at,
    )


def score_repositories(
    repos: Sequence[Repository],
    *,
    growth: Mapping[int, GrowthFacts] | None = None,
    now: datetime | None = None,
) -> dict[int, RepoScores]:
    """Ba điểm của từng repo, khoá là `Repository.pk`. `growth` cũng khoá theo `Repository.pk`.

    Hồ sơ chủ đọc từ kho một lần cho cả lô; chủ chưa có hồ sơ thì điểm nghi star giả ghi rõ "chưa
    tính phần hồ sơ chủ".
    """
    moment = now if now is not None else timezone.now()
    growth = growth or {}
    profiles = catalog.owner_profiles_for(repo.owner_login for repo in repos)
    scores: dict[int, RepoScores] = {}
    for repo in repos:
        facts = repo_facts(repo)
        repo_growth = growth.get(repo.pk)
        profile = profiles.get(repo.owner_login.lower())
        scores[repo.pk] = RepoScores(
            quality=rules.quality_score(facts, now=moment),
            potential=None if repo_growth is None else rules.potential_score(repo_growth),
            suspicion=rules.suspicion_score(
                facts,
                growth=repo_growth,
                owner=_owner_facts(profile),
                owner_missing=profile is not None and profile.is_missing,
                now=moment,
            ),
        )
    return scores


def owners_to_fetch(logins: Sequence[str], *, now: datetime) -> list[str]:
    """Các chủ chưa có hồ sơ hoặc hồ sơ cũ hơn 30 ngày — giữ thứ tự, mỗi chủ một lần."""
    return catalog.logins_needing_profile(logins, fresh_after=now - OWNER_PROFILE_MAX_AGE)


def fetch_owner_profiles(
    github: GitHubClient,
    logins: Sequence[str],
    *,
    before_each: Callable[[], None],
    after_call: Callable[[], None],
) -> OwnerFetchOutcome:
    """Lấy hồ sơ từng chủ (1 lượt gọi mỗi chủ), lưu ngay sau mỗi lượt để chạy tiếp không gọi lại.

    - `before_each()` chạy trước mỗi chủ (bên gọi ghi nhịp sống, ném lỗi khi người dùng bấm Dừng).
    - `after_call()` chạy sau mỗi lượt gọi kể cả khi lỗi (bên gọi ghi số lượt đã dùng); không được
      ném lỗi.
    - Tài khoản không còn (404) → ghi "không còn tồn tại", đi tiếp. Dữ liệu lạ hoặc login không hợp
      lệ → ghi vào `unreadable`, đi tiếp.
    - Hết lượt, mất mạng, token sai, hết ngân sách → ném ra cho bên gọi; hồ sơ đã lưu vẫn giữ.
    """
    outcome = OwnerFetchOutcome()
    for login in logins:
        before_each()
        try:
            try:
                user = github.get_user(login)
            finally:
                after_call()
        except GitHubNotFoundError:
            logger.info("Chủ repo %s không còn trên GitHub (404)", login)
            catalog.mark_owner_missing(login, fetched_at=timezone.now())
            outcome.missing += 1
        except (GitHubResponseError, ValueError) as exc:
            logger.warning("Không đọc được hồ sơ chủ repo %s: %r", login, exc)
            outcome.unreadable.append((login, str(exc)))
        else:
            catalog.save_owner_profile(user, fetched_at=timezone.now())
            outcome.fetched += 1
    return outcome


def _owner_facts(profile: OwnerProfile | None) -> OwnerFacts | None:
    if profile is None or profile.is_missing:
        return None
    if profile.gh_created_at is None or profile.followers is None or profile.public_repos is None:
        return None
    return OwnerFacts(
        created_at=profile.gh_created_at,
        followers=profile.followers,
        public_repos=profile.public_repos,
    )
