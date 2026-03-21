from dataclasses import asdict, dataclass
import mimetypes
from urllib.parse import urljoin

from scrapling.fetchers import Fetcher, DynamicFetcher, StealthyFetcher
from scrapling.engines.toolbelt.custom import Response as ScraplingResponse
from scrapling.core._types import Optional, Literal

FetchStrategy = Literal["get", "fetch", "stealthy_fetch"]


@dataclass(slots=True)
class ImageCandidate:
    index: int
    src: str
    absolute_url: str
    alt: Optional[str] = None
    title: Optional[str] = None
    width: Optional[str] = None
    height: Optional[str] = None

    def to_dict(self):
        return asdict(self)


@dataclass(slots=True)
class ImageCandidatesResult:
    page_url: str
    strategy: str
    css_selector: str
    count: int
    images: list[ImageCandidate]

    def to_dict(self):
        return {
            "page_url": self.page_url,
            "strategy": self.strategy,
            "css_selector": self.css_selector,
            "count": self.count,
            "images": [image.to_dict() for image in self.images],
        }


@dataclass(slots=True)
class ImageFetchResult:
    page_url: str
    strategy: str
    image_index: int
    image_url: str
    mime_type: str
    bytes_count: int
    candidate: ImageCandidate
    data: bytes

    def metadata_dict(self):
        return {
            "page_url": self.page_url,
            "image_url": self.image_url,
            "strategy": self.strategy,
            "mime_type": self.mime_type,
            "bytes": self.bytes_count,
            "image_index": self.image_index,
            "candidate": self.candidate.to_dict(),
        }


def _extract_image_candidates(
    page: ScraplingResponse,
    page_url: str,
    css_selector: str,
    src_contains: Optional[str],
    max_results: int,
) -> list[ImageCandidate]:
    results: list[ImageCandidate] = []
    for element in page.css(css_selector):
        if len(results) >= max_results:
            break

        src = (
            element.attrib.get("src")
            or element.attrib.get("data-src")
            or element.attrib.get("data-original")
        )
        if not src:
            continue

        absolute_url = urljoin(page_url, src)
        if src_contains and src_contains not in src and src_contains not in absolute_url:
            continue

        results.append(
            ImageCandidate(
                index=len(results),
                src=src,
                absolute_url=absolute_url,
                alt=element.attrib.get("alt"),
                title=element.attrib.get("title"),
                width=element.attrib.get("width"),
                height=element.attrib.get("height"),
            )
        )
    return results


def _detect_image_mimetype(asset_url: str, response: ScraplingResponse) -> str:
    header_value = (response.headers or {}).get("content-type", "")
    mime_type = header_value.split(";", 1)[0].strip().lower()
    if mime_type:
        return mime_type
    guessed_type, _ = mimetypes.guess_type(asset_url)
    return guessed_type or "application/octet-stream"


async def _fetch_with_strategy(url: str, strategy: FetchStrategy) -> ScraplingResponse:
    if strategy == "get":
        return Fetcher.get(url)
    if strategy == "fetch":
        return await DynamicFetcher.async_fetch(url)
    if strategy == "stealthy_fetch":
        return await StealthyFetcher.async_fetch(url)
    raise ValueError("Unsupported strategy. Use one of: get, fetch, stealthy_fetch")


async def list_page_images(
    page_url: str,
    strategy: FetchStrategy = "fetch",
    css_selector: str = "img",
    src_contains: Optional[str] = None,
    max_results: int = 20,
) -> ImageCandidatesResult:
    page = await _fetch_with_strategy(page_url, strategy)
    candidates = _extract_image_candidates(page, page_url, css_selector, src_contains, max_results)
    return ImageCandidatesResult(
        page_url=page_url,
        strategy=strategy,
        css_selector=css_selector,
        count=len(candidates),
        images=candidates,
    )


async def fetch_page_image(
    page_url: str,
    strategy: FetchStrategy = "fetch",
    css_selector: str = "img",
    image_index: int = 0,
    src_contains: Optional[str] = None,
    max_results: int = 20,
) -> ImageFetchResult:
    candidates_result = await list_page_images(
        page_url=page_url,
        strategy=strategy,
        css_selector=css_selector,
        src_contains=src_contains,
        max_results=max_results,
    )

    if not candidates_result.images:
        raise ValueError(f"No images matched css_selector={css_selector!r} on {page_url}")

    if image_index < 0 or image_index >= len(candidates_result.images):
        raise ValueError(
            f"Requested image_index={image_index}, but only {len(candidates_result.images)} candidates matched."
        )

    selected = candidates_result.images[image_index]
    asset = await _fetch_with_strategy(selected.absolute_url, strategy)
    body = asset.body or b""

    if not isinstance(body, bytes):
        raise TypeError("Scrapling did not return a raw byte payload for the selected asset.")
    if not body:
        raise ValueError("The selected image returned an empty body.")

    mime_type = _detect_image_mimetype(selected.absolute_url, asset)
    if not mime_type.startswith("image/"):
        raise ValueError(f"Selected asset resolved to MIME type {mime_type!r}, not an image.")

    return ImageFetchResult(
        page_url=page_url,
        strategy=strategy,
        image_index=image_index,
        image_url=selected.absolute_url,
        mime_type=mime_type,
        bytes_count=len(body),
        candidate=selected,
        data=body,
    )
