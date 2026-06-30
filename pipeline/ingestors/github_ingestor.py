"""
Unstructured source: GitHub profile URL.
Uses the public GitHub REST API — no auth required for public profiles.
"""

import logging
import re
from typing import Optional
from urllib.parse import urlparse

import requests

from models.canonical import RawRecord, Links
from .base import BaseIngestor

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_REQUEST_TIMEOUT = 10  # seconds


class GitHubIngestor(BaseIngestor):
    def __init__(self, profile_url: str):
        self.profile_url = profile_url
        self.username = self._extract_username(profile_url)

    def extract(self) -> RawRecord:
        if not self.username:
            logger.warning("Could not parse GitHub username from: %s", self.profile_url)
            return RawRecord(source="github")

        try:
            return self._fetch_and_parse()
        except Exception as exc:
            logger.error("GitHub ingestion failed for %s: %s", self.username, exc)
            return RawRecord(source="github")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_and_parse(self) -> RawRecord:
        user = self._get(f"/users/{self.username}")
        if user is None:
            return RawRecord(source="github")

        repos = self._get(f"/users/{self.username}/repos", params={"per_page": 100}) or []

        languages = self._collect_languages(repos)
        top_topics = self._collect_topics(repos)

        # "name" is the display name (e.g. "John Smith").
        # "login" is the username ("johnsmith42") — NOT a person name.
        display_name: Optional[str] = user.get("name") or None

        location_raw = user.get("location")
        emails = [user["email"]] if user.get("email") else []

        bio = user.get("bio") or None
        blog = user.get("blog") or None

        skills = languages + top_topics

        return RawRecord(
            source="github",
            full_name=display_name,
            emails=emails,
            location=self._parse_location(location_raw),
            links=Links(
                github=f"https://github.com/{self.username}",
                portfolio=blog if blog and blog.startswith("http") else None,
            ),
            headline=bio,
            skills=skills,
        )

    def _get(self, path: str, params: dict | None = None):
        url = _GITHUB_API + path
        try:
            resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT,
                                headers={"Accept": "application/vnd.github+json"})
            if resp.status_code == 404:
                logger.warning("GitHub 404 for %s", url)
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning("GitHub request failed (%s): %s", url, exc)
            return None

    @staticmethod
    def _extract_username(url: str) -> Optional[str]:
        """Extract username from https://github.com/username or bare 'username'."""
        url = url.strip()
        if url.startswith("http"):
            parts = urlparse(url).path.strip("/").split("/")
            return parts[0] if parts else None
        # Could be a bare username
        if re.fullmatch(r"[\w\-]+", url):
            return url
        return None

    @staticmethod
    def _collect_languages(repos: list) -> list[str]:
        """Return top languages by frequency across repos."""
        from collections import Counter
        counts = Counter(
            r["language"] for r in repos
            if isinstance(r, dict) and r.get("language")
        )
        return [lang for lang, _ in counts.most_common(5)]

    @staticmethod
    def _collect_topics(repos: list) -> list[str]:
        """Flatten topics from all repos, deduplicated."""
        seen: set[str] = set()
        topics: list[str] = []
        for repo in repos:
            if not isinstance(repo, dict):
                continue
            for topic in repo.get("topics", []):
                if topic not in seen:
                    seen.add(topic)
                    topics.append(topic)
        return topics[:10]

    @staticmethod
    def _parse_location(raw: Optional[str]):
        """Best-effort parse of GitHub's free-text location field."""
        if not raw:
            return None
        from models.canonical import Location
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) >= 2:
            return Location(city=parts[0], country=parts[-1])
        return Location(city=parts[0])