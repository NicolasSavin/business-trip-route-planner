from __future__ import annotations
import asyncio, hashlib, json, logging, os, re, time
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from .models import AvailabilityCheckRequest, AvailabilityCheckResponse, AvailabilityStatus, Diagnostics, JourneyAvailabilityResponse
from .settings import settings

logger = logging.getLogger(__name__)
LOCATION_AUTOCOMPLETE_TIMEOUT_MS = 12_000


def normalize_location_text(value: str) -> str:
    value = (value or "").split(",", 1)[0].lower().replace("ё", "е").strip()
    return re.sub(r"[\s\-]+", " ", value).strip()


def location_matches(candidate: str, city_name: str) -> tuple[int, bool]:
    candidate_norm = normalize_location_text(candidate)
    city_norm = normalize_location_text(city_name)
    if not candidate_norm or not city_norm:
        return (99, False)
    if candidate_norm == city_norm:
        return (0, True)
    if candidate_norm.startswith(city_norm) or city_norm.startswith(candidate_norm):
        return (1, True)
    if city_norm in candidate_norm or candidate_norm in city_norm:
        return (2, True)
    return (99, False)


async def _locator_count(locator) -> int:
    try:
        return await locator.count()
    except Exception:
        return 0


async def _visible_locator_count(locator) -> int:
    total = await _locator_count(locator)
    visible = 0
    for index in range(total):
        item = locator.nth(index)
        try:
            if await item.is_visible(timeout=200):
                visible += 1
        except Exception:
            continue
    return visible


async def _candidate_options(page):
    locators = [
        page.get_by_role("listbox").get_by_role("option"),
        page.get_by_role("option"),
        page.locator('[role="combobox"][aria-expanded="true"] [role="option"]'),
        page.locator('[role="listbox"] [role="option"]'),
        page.locator('[data-testid*="suggest" i], [class*="suggest" i], [class*="autocomplete" i], [class*="popup" i]').locator('text=/\\S/'),
    ]
    for locator in locators:
        if await _visible_locator_count(locator):
            return locator
    return locators[-1]


async def _autocomplete_is_closed(page) -> bool:
    options = await _candidate_options(page)
    return await _visible_locator_count(options) == 0


async def _capture_location_artifacts(page, field_name: str, city_name: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    safe_field = re.sub(r"[^a-zA-Z0-9_.-]+", "-", field_name).strip("-") or "location"
    base = f"location-{safe_field}-{stamp}"
    sp = os.path.join(settings.artifact_dir, f"{base}.png")
    hp = os.path.join(settings.artifact_dir, f"{base}.html")
    try:
        await page.screenshot(path=sp, full_page=True)
        Path(hp).write_text(await page.content(), encoding="utf-8")
        logger.info("location autocomplete artifacts saved", extra={"field_name": field_name, "city_name": city_name, "screenshot": sp, "html_artifact": hp})
    except Exception:
        logger.exception("location autocomplete artifact capture caught exception", extra={"field_name": field_name, "city_name": city_name})


async def select_location(page, textbox, city_name, field_name):
    await textbox.fill(city_name)
    deadline = time.monotonic() + LOCATION_AUTOCOMPLETE_TIMEOUT_MS / 1000
    options = None
    while time.monotonic() < deadline:
        options = await _candidate_options(page)
        count = await _visible_locator_count(options)
        if count:
            logger.info("autocomplete opened", extra={"field_name": field_name, "city_name": city_name})
            logger.info("autocomplete options counted", extra={"field_name": field_name, "city_name": city_name, "options_count": count})
            break
        await asyncio.sleep(0.2)
    else:
        count = 0
        logger.info("autocomplete options counted", extra={"field_name": field_name, "city_name": city_name, "options_count": 0})

    candidates = []
    if options is not None:
        total = await _locator_count(options)
        for index in range(total):
            option = options.nth(index)
            try:
                if not await option.is_visible(timeout=200):
                    continue
                text = (await option.inner_text(timeout=1000)).strip()
            except Exception:
                continue
            if text:
                rank, matched = location_matches(text, city_name)
                candidates.append((rank, index, text, option, matched))
    logger.info("autocomplete candidate texts", extra={"field_name": field_name, "city_name": city_name, "candidate_texts": [c[2] for c in candidates]})

    matches = sorted((c for c in candidates if c[4]), key=lambda c: (c[0], c[1]))
    if matches:
        rank, _index, text, option, _matched = matches[0]
        await option.click(timeout=LOCATION_AUTOCOMPLETE_TIMEOUT_MS)
        logger.info("autocomplete candidate selected", extra={"field_name": field_name, "city_name": city_name, "selected_candidate": text, "match_rank": rank})
    else:
        logger.info("autocomplete fallback used", extra={"field_name": field_name, "city_name": city_name, "fallback": "ArrowDown+Enter"})
        try:
            await textbox.press("ArrowDown")
            await textbox.press("Enter")
            await asyncio.sleep(0.2)
        except Exception:
            logger.exception("autocomplete fallback caught exception", extra={"field_name": field_name, "city_name": city_name})
        final_after_fallback = (await textbox.input_value()).strip()
        if normalize_location_text(final_after_fallback) == normalize_location_text(city_name) and await _autocomplete_is_closed(page):
            logger.info("autocomplete fallback accepted", extra={"field_name": field_name, "city_name": city_name})
        else:
            await _capture_location_artifacts(page, field_name, city_name)
            raise ValueError(f"Location suggestion not found: {city_name}")

    final_value = (await textbox.input_value()).strip()
    logger.info("final textbox value", extra={"field_name": field_name, "city_name": city_name, "final_textbox_value": final_value})
    if normalize_location_text(city_name) not in normalize_location_text(final_value) and normalize_location_text(final_value) not in normalize_location_text(city_name):
        raise ValueError(f"Location suggestion not found: {city_name}")
    return final_value

class TTLCache:
    def __init__(self, ttl:int): self.ttl=ttl; self.items={}
    def get(self,k):
        v=self.items.get(k)
        if not v: return None
        t,r=v
        if time.time()-t>self.ttl: self.items.pop(k,None); return None
        return r
    def set(self,k,v): self.items[k]=(time.time(),v)

class TutuAvailabilityService:
    def __init__(self):
        self.sem=asyncio.Semaphore(max(1, settings.concurrency)); self.cache=TTLCache(settings.cache_ttl_seconds); self._browser=None; self._pw=None
        Path(settings.artifact_dir).mkdir(parents=True, exist_ok=True)
    def key(self, req): return hashlib.sha256(req.model_dump_json().encode()).hexdigest()
    async def check(self, req: AvailabilityCheckRequest) -> AvailabilityCheckResponse:
        k=self.key(req); cached=self.cache.get(k)
        if cached:
            logger.info("response returned", extra={"source": "cache", "status": cached.status.value, "matched_train": cached.matched_train, "train_number": cached.train_number})
            return cached
        if not req.train_number:
            logger.info("early exit condition observed", extra={"reason": "missing train number", "will_exit_early": False})
        logger.info("configuration", extra={"enabled": settings.enabled, "mock_mode": settings.mock_mode, "timeout_seconds": settings.timeout_seconds, "concurrency": settings.concurrency})
        if settings.mock_mode or not settings.enabled:
            logger.info("early exit condition observed", extra={"reason": "disabled enrichment" if settings.mock_mode else "configuration", "mock_mode": settings.mock_mode, "enabled": settings.enabled})
        async with self.sem:
            try:
                res= await asyncio.wait_for(self._mock(req) if settings.mock_mode or not settings.enabled else self._playwright(req), timeout=settings.timeout_seconds)
            except asyncio.TimeoutError:
                logger.exception("availability check caught exception", extra={"reason": "timeout", "timeout_seconds": settings.timeout_seconds})
                logger.info("early exit condition observed", extra={"reason": "timeout"})
                res=AvailabilityCheckResponse(status=AvailabilityStatus.PROVIDER_ERROR, train_number=req.train_number, message="Tutu availability check timed out")
            except Exception as exc:
                logger.exception("availability check caught exception", extra={"reason": "provider_error"})
                res=AvailabilityCheckResponse(status=AvailabilityStatus.PROVIDER_ERROR, train_number=req.train_number, message="Tutu provider error", warnings=[str(exc)])
            self.cache.set(k,res); return res
    async def check_journey(self, segments):
        results=[await self.check(s) for s in segments]
        statuses={r.status for r in results}
        status=AvailabilityStatus.CONFIRMED if results and all(r.status==AvailabilityStatus.CONFIRMED for r in results) else (AvailabilityStatus.UNAVAILABLE if AvailabilityStatus.UNAVAILABLE in statuses else (AvailabilityStatus.PROVIDER_ERROR if AvailabilityStatus.PROVIDER_ERROR in statuses else AvailabilityStatus.PARTIALLY_CONFIRMED))
        return JourneyAvailabilityResponse(status=status, segments=results)
    async def _mock(self, req):
        if req.train_number and req.train_number.upper().startswith("NO"):
            logger.info("early exit condition observed", extra={"reason": "unsupported request", "train_number": req.train_number})
            return AvailabilityCheckResponse(status=AvailabilityStatus.UNKNOWN, matched_train=False, train_number=req.train_number, message="Mock: train was not found")
        places=[str(i*2+1) for i in range(req.passengers)] if req.berth_preference=="lower_only" else [str(i+1) for i in range(req.passengers)]
        return AvailabilityCheckResponse(status=AvailabilityStatus.CONFIRMED, matched_train=True, train_number=req.train_number, available_seats=max(req.passengers,4), selected_places=places, selected_carriages=["5"], selected_compartments=["1"], transport_class=(req.preferred_classes[0] if req.preferred_classes else "coupe"), same_carriage=True, same_compartment=req.require_same_compartment, lower_berths_confirmed=req.berth_preference=="lower_only", message="Mock: availability confirmed", diagnostics=Diagnostics(matched_by="train_number+departure_time", page_url="https://www.tutu.ru/poezda/"))
    async def _browser_instance(self):
        try:
            if not self._pw: self._pw=await async_playwright().start()
            if not self._browser:
                logger.info("browser launch started", extra={"headless": settings.headless})
                self._browser=await self._pw.chromium.launch(headless=settings.headless)
                logger.info("browser launched")
            return self._browser
        except Exception:
            logger.exception("browser startup failure")
            logger.info("early exit condition observed", extra={"reason": "browser startup failure"})
            raise
    async def restart(self):
        if self._browser: await self._browser.close(); self._browser=None
    async def _playwright(self, req):
        browser=await self._browser_instance(); context=await browser.new_context(locale="ru-RU"); page=await context.new_page(); logger.info("page opened", extra={"locale": "ru-RU"}); page.set_default_timeout(settings.timeout_seconds*1000)
        shots=[]; htmls=[]
        try:
            logger.info("navigating to tutu.ru", extra={"url": "https://www.tutu.ru/poezda/"})
            await page.goto("https://www.tutu.ru/poezda/", wait_until="domcontentloaded")
            # Public UI only. Locators are intentionally semantic, but Tutu markup may change.
            await select_location(page, page.get_by_role("textbox").first, req.origin, "origin")
            await select_location(page, page.get_by_role("textbox").nth(1), req.destination, "destination")
            logger.info("search form filled", extra={"origin": req.origin, "destination": req.destination, "departure_date": req.departure_date.isoformat()})
            await page.get_by_role("button", name="Найти", exact=False).click()
            logger.info("search submitted")
            await page.get_by_text(req.train_number or "", exact=False).first.wait_for(timeout=15000)
            logger.info("search results received", extra={"page_url": page.url})
            text=await page.locator("body").inner_text()
            matched=bool(req.train_number and req.train_number in text)
            logger.info("journey matched", extra={"matched_train": matched, "train_number": req.train_number})
            logger.info("seat availability extraction started")
            logger.info("seat availability extracted", extra={"available_seats": None})
            return AvailabilityCheckResponse(status=AvailabilityStatus.UNKNOWN if matched else AvailabilityStatus.UNKNOWN, matched_train=matched, train_number=req.train_number, message="Tutu UI parsed; detailed seat extraction requires current markup", diagnostics=Diagnostics(matched_by="train_number" if matched else None, page_url=page.url))
        except Exception as exc:
            stamp=datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            sp=os.path.join(settings.artifact_dir,f"error-{stamp}.png"); hp=os.path.join(settings.artifact_dir,f"error-{stamp}.html")
            try: await page.screenshot(path=sp, full_page=True); Path(hp).write_text(await page.content(), encoding="utf-8"); shots.append(sp); htmls.append(hp)
            except Exception:
                logger.exception("artifact capture caught exception")
            logger.exception("playwright availability caught exception", extra={"screenshots": shots, "html_artifacts": htmls})
            raise exc
        finally:
            await context.close()
service=TutuAvailabilityService()
