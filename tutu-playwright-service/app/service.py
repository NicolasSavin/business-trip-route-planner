from __future__ import annotations
import asyncio, hashlib, json, os, time
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from .models import AvailabilityCheckRequest, AvailabilityCheckResponse, AvailabilityStatus, Diagnostics, JourneyAvailabilityResponse
from .settings import settings

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
        if cached: return cached
        async with self.sem:
            try:
                res= await asyncio.wait_for(self._mock(req) if settings.mock_mode or not settings.enabled else self._playwright(req), timeout=settings.timeout_seconds)
            except asyncio.TimeoutError:
                res=AvailabilityCheckResponse(status=AvailabilityStatus.PROVIDER_ERROR, train_number=req.train_number, message="Tutu availability check timed out")
            except Exception as exc:
                res=AvailabilityCheckResponse(status=AvailabilityStatus.PROVIDER_ERROR, train_number=req.train_number, message="Tutu provider error", warnings=[str(exc)])
            self.cache.set(k,res); return res
    async def check_journey(self, segments):
        results=[await self.check(s) for s in segments]
        statuses={r.status for r in results}
        status=AvailabilityStatus.CONFIRMED if results and all(r.status==AvailabilityStatus.CONFIRMED for r in results) else (AvailabilityStatus.UNAVAILABLE if AvailabilityStatus.UNAVAILABLE in statuses else (AvailabilityStatus.PROVIDER_ERROR if AvailabilityStatus.PROVIDER_ERROR in statuses else AvailabilityStatus.PARTIALLY_CONFIRMED))
        return JourneyAvailabilityResponse(status=status, segments=results)
    async def _mock(self, req):
        if req.train_number and req.train_number.upper().startswith("NO"):
            return AvailabilityCheckResponse(status=AvailabilityStatus.UNKNOWN, matched_train=False, train_number=req.train_number, message="Mock: train was not found")
        places=[str(i*2+1) for i in range(req.passengers)] if req.berth_preference=="lower_only" else [str(i+1) for i in range(req.passengers)]
        return AvailabilityCheckResponse(status=AvailabilityStatus.CONFIRMED, matched_train=True, train_number=req.train_number, available_seats=max(req.passengers,4), selected_places=places, selected_carriages=["5"], selected_compartments=["1"], transport_class=(req.preferred_classes[0] if req.preferred_classes else "coupe"), same_carriage=True, same_compartment=req.require_same_compartment, lower_berths_confirmed=req.berth_preference=="lower_only", message="Mock: availability confirmed", diagnostics=Diagnostics(matched_by="train_number+departure_time", page_url="https://www.tutu.ru/poezda/"))
    async def _browser_instance(self):
        if not self._pw: self._pw=await async_playwright().start()
        if not self._browser: self._browser=await self._pw.chromium.launch(headless=settings.headless)
        return self._browser
    async def restart(self):
        if self._browser: await self._browser.close(); self._browser=None
    async def _playwright(self, req):
        browser=await self._browser_instance(); context=await browser.new_context(locale="ru-RU"); page=await context.new_page(); page.set_default_timeout(settings.timeout_seconds*1000)
        shots=[]; htmls=[]
        try:
            await page.goto("https://www.tutu.ru/poezda/", wait_until="domcontentloaded")
            # Public UI only. Locators are intentionally semantic, but Tutu markup may change.
            await page.get_by_role("textbox").first.fill(req.origin)
            await page.get_by_text(req.origin, exact=False).first.click(timeout=5000)
            await page.get_by_role("textbox").nth(1).fill(req.destination)
            await page.get_by_text(req.destination, exact=False).first.click(timeout=5000)
            await page.get_by_role("button", name="Найти", exact=False).click()
            await page.get_by_text(req.train_number or "", exact=False).first.wait_for(timeout=15000)
            text=await page.locator("body").inner_text()
            matched=bool(req.train_number and req.train_number in text)
            return AvailabilityCheckResponse(status=AvailabilityStatus.UNKNOWN if matched else AvailabilityStatus.UNKNOWN, matched_train=matched, train_number=req.train_number, message="Tutu UI parsed; detailed seat extraction requires current markup", diagnostics=Diagnostics(matched_by="train_number" if matched else None, page_url=page.url))
        except Exception as exc:
            stamp=datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            sp=os.path.join(settings.artifact_dir,f"error-{stamp}.png"); hp=os.path.join(settings.artifact_dir,f"error-{stamp}.html")
            try: await page.screenshot(path=sp, full_page=True); Path(hp).write_text(await page.content(), encoding="utf-8"); shots.append(sp); htmls.append(hp)
            except Exception: pass
            raise exc
        finally:
            await context.close()
service=TutuAvailabilityService()
