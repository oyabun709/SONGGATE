import base64
import csv
import io
import json
import uuid
import zipfile
from datetime import date
from xml.etree import ElementTree as ET

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.release import Release
from schemas.release import ReleaseCreate


class ReleaseService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_org(self, org_id: uuid.UUID) -> list[Release]:
        result = await self.db.execute(
            select(Release)
            .where(Release.org_id == org_id)
            .order_by(Release.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_for_org(self, release_id: str, org_id: uuid.UUID) -> Release | None:
        result = await self.db.execute(
            select(Release).where(
                Release.id == release_id,
                Release.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, payload: ReleaseCreate, org_id: uuid.UUID) -> Release:
        release = Release(
            org_id=org_id,
            title=payload.title,
            artist=payload.artist,
            upc=payload.upc,
            release_date=payload.release_date,
            submission_format=payload.submission_format,
            external_id=payload.external_id,
        )
        self.db.add(release)
        await self.db.commit()
        await self.db.refresh(release)
        return release

    async def attach_artifact(self, release_id: str, file: UploadFile) -> dict:
        content = await file.read()
        mime = file.content_type or "application/octet-stream"
        data_uri = f"data:{mime};base64,{base64.b64encode(content).decode()}"

        result = await self.db.execute(
            select(Release).where(Release.id == release_id)
        )
        release = result.scalar_one_or_none()
        if release is None:
            return {"detail": "release not found"}

        release.raw_package_url = data_uri

        # Parse file to backfill release fields (best-effort)
        fname = (file.filename or "").lower()
        if fname.endswith(".xml"):
            _apply_ddex_fields(release, content)
        elif fname.endswith(".zip"):
            _apply_zip_fields(release, content)
        elif fname.endswith(".csv"):
            _apply_csv_fields(release, content)
        elif fname.endswith(".json"):
            _apply_json_fields(release, content)

        await self.db.commit()
        await self.db.refresh(release)

        return {
            "id": str(release.id),
            "title": release.title,
            "artist": release.artist,
            "upc": release.upc,
            "release_date": release.release_date.isoformat() if release.release_date else None,
        }

    async def delete(self, release_id: str) -> None:
        result = await self.db.execute(
            select(Release).where(Release.id == release_id)
        )
        release = result.scalar_one_or_none()
        if release:
            await self.db.delete(release)
            await self.db.commit()


# ─── Field extractors ─────────────────────────────────────────────────────────

def _local(el: ET.Element) -> str:
    """Strip XML namespace from a tag name."""
    return el.tag.split("}")[-1] if "}" in el.tag else el.tag


def _children_by_local(parent: ET.Element, local: str) -> list[ET.Element]:
    return [e for e in parent if _local(e) == local]


def _find_by_local(parent: ET.Element, local: str) -> ET.Element | None:
    for el in parent.iter():
        if _local(el) == local:
            return el
    return None


def _find_all_by_local(parent: ET.Element, local: str) -> list[ET.Element]:
    return [el for el in parent.iter() if _local(el) == local]


def _parse_date(raw: str) -> date | None:
    raw = raw.strip()
    try:
        if len(raw) == 4:
            return date(int(raw), 1, 1)
        return date.fromisoformat(raw[:10])
    except (ValueError, IndexError):
        return None


def _apply_ddex_fields(release: Release, content: bytes) -> None:
    """
    Parse DDEX ERN XML and update release fields in-place (best-effort).
    Scopes to ReleaseList > Release (IsMainRelease or first) to avoid
    picking track-level TitleText elements.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return

    # Find the main Release element
    release_node: ET.Element | None = None
    release_list = _find_by_local(root, "ReleaseList")
    if release_list is not None:
        releases = _children_by_local(release_list, "Release")
        # Prefer IsMainRelease="true", fall back to first
        for r in releases:
            if r.attrib.get("IsMainRelease", "").lower() == "true":
                release_node = r
                break
        if release_node is None and releases:
            release_node = releases[0]

    if release_node is None:
        # No ReleaseList — try whole doc (bare/minimal DDEX)
        release_node = root

    # ── UPC / ICPN ────────────────────────────────────────────────────────
    for local in ("ICPN", "UPC"):
        el = _find_by_local(release_node, local)
        if el is not None and el.text:
            release.upc = el.text.strip()
            break

    # ── Title ──────────────────────────────────────────────────────────────
    # Priority: ReferenceTitle/TitleText → FormalTitle TitleText → first TitleText
    title: str | None = None
    ref_title = _find_by_local(release_node, "ReferenceTitle")
    if ref_title is not None:
        tt = _find_by_local(ref_title, "TitleText")
        if tt is not None and tt.text:
            title = tt.text.strip()
    if not title:
        # Look for <Title TitleType="FormalTitle"><TitleText>
        for title_el in _find_all_by_local(release_node, "Title"):
            if title_el.attrib.get("TitleType") == "FormalTitle":
                tt = _find_by_local(title_el, "TitleText")
                if tt is not None and tt.text:
                    title = tt.text.strip()
                    break
    if not title:
        tt = _find_by_local(release_node, "TitleText")
        if tt is not None and tt.text:
            title = tt.text.strip()
    if title:
        release.title = title

    # ── Artist ────────────────────────────────────────────────────────────
    # Priority: DisplayArtistName → DisplayArtist/PartyName/FullName
    artist: str | None = None
    dan = _find_by_local(release_node, "DisplayArtistName")
    if dan is not None and dan.text:
        artist = dan.text.strip()
    if not artist:
        for da in _find_all_by_local(release_node, "DisplayArtist"):
            pn = _find_by_local(da, "PartyName")
            fn = _find_by_local(pn, "FullName") if pn is not None else None
            if fn is not None and fn.text:
                artist = fn.text.strip()
                break
    if artist:
        release.artist = artist

    # ── Release date ──────────────────────────────────────────────────────
    for local in ("OriginalReleaseDate", "ReleaseDate"):
        el = _find_by_local(release_node, local)
        if el is not None and el.text:
            d = _parse_date(el.text)
            if d:
                release.release_date = d
                break


def _apply_zip_fields(release: Release, content: bytes) -> None:
    """Extract DDEX XML from ZIP and apply fields."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            # Find the first .xml file (prefer NewReleaseMessage / ern filenames)
            xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
            if not xml_names:
                return
            # Prefer files named after common DDEX conventions
            preferred = next(
                (n for n in xml_names if "release" in n.lower() or "ern" in n.lower()),
                xml_names[0],
            )
            xml_bytes = zf.read(preferred)
            _apply_ddex_fields(release, xml_bytes)
    except (zipfile.BadZipFile, KeyError, Exception):
        return


def _apply_csv_fields(release: Release, content: bytes) -> None:
    """Parse CSV metadata and apply release fields."""
    _CSV_ALIASES: dict[str, str] = {
        "title": "title",
        "release_title": "title",
        "album": "title",
        "album_title": "title",
        "artist": "artist",
        "artist_name": "artist",
        "primary_artist": "artist",
        "display_artist": "artist",
        "upc": "upc",
        "barcode": "upc",
        "ean": "upc",
        "icpn": "upc",
        "release_date": "release_date",
        "date": "release_date",
        "original_release_date": "release_date",
    }
    try:
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        row = next(iter(reader), None)
        if row is None:
            return
        mapped: dict[str, str] = {}
        for col, val in row.items():
            key = _CSV_ALIASES.get(col.strip().lower().replace(" ", "_"))
            if key and val.strip():
                mapped[key] = val.strip()
        if mapped.get("title"):
            release.title = mapped["title"]
        if mapped.get("artist"):
            release.artist = mapped["artist"]
        if mapped.get("upc"):
            release.upc = mapped["upc"]
        if mapped.get("release_date"):
            d = _parse_date(mapped["release_date"])
            if d:
                release.release_date = d
    except Exception:
        return


def _apply_json_fields(release: Release, content: bytes) -> None:
    """Parse JSON metadata and apply release fields."""
    _JSON_ALIASES: dict[str, str] = {
        "title": "title",
        "release_title": "title",
        "album": "title",
        "artist": "artist",
        "artist_name": "artist",
        "primary_artist": "artist",
        "upc": "upc",
        "barcode": "upc",
        "icpn": "upc",
        "ean": "upc",
        "release_date": "release_date",
        "releasedate": "release_date",
        "date": "release_date",
        "original_release_date": "release_date",
    }
    try:
        data = json.loads(content.decode("utf-8", errors="replace"))
        if not isinstance(data, dict):
            # Handle array — take first element
            if isinstance(data, list) and data and isinstance(data[0], dict):
                data = data[0]
            else:
                return
        mapped: dict[str, str] = {}
        for key, val in data.items():
            canonical = _JSON_ALIASES.get(key.strip().lower().replace(" ", "_").replace("-", "_"))
            if canonical and isinstance(val, str) and val.strip():
                mapped[canonical] = val.strip()
        if mapped.get("title"):
            release.title = mapped["title"]
        if mapped.get("artist"):
            release.artist = mapped["artist"]
        if mapped.get("upc"):
            release.upc = mapped["upc"]
        if mapped.get("release_date"):
            d = _parse_date(mapped["release_date"])
            if d:
                release.release_date = d
    except Exception:
        return
