"use client";

import { useState } from "react";
import { browserPing, browserScreenshotUrl } from "@/lib/api";
import type { BrowserPingResponse } from "@/lib/types";

export default function BrowserDiagnosticsPage() {
  const [result, setResult] = useState<BrowserPingResponse | null>(null);
  const [screenshotVersion, setScreenshotVersion] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function testBrowser() {
    setLoading(true);
    try {
      const ping = await browserPing();
      setResult(ping);
      setScreenshotVersion(Date.now());
      setError(null);
    } catch {
      setError("Browser diagnostics failed.");
    } finally {
      setLoading(false);
    }
  }

  return <main className="min-h-screen bg-cloud p-8 text-ink">
    <section className="mx-auto max-w-4xl rounded-[2rem] bg-white p-8 shadow-card">
      <p className="text-sm font-semibold uppercase tracking-[0.2em] text-brand">Browser Diagnostics</p>
      <h1 className="mt-2 text-3xl font-semibold">Browser Diagnostics</h1>
      <p className="mt-3 text-muted">Проверка запускает Playwright, открывает только https://example.com и показывает результат без scraping.</p>
      <button onClick={testBrowser} disabled={loading} className="mt-6 rounded-full bg-brand px-5 py-3 font-semibold text-white disabled:opacity-60">
        {loading ? "Testing..." : "Test Browser"}
      </button>
      {error && <p className="mt-4 rounded-2xl bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
      {result && <div className="mt-6 grid gap-4">
        <div className="rounded-2xl bg-emerald-50 p-4 font-semibold text-emerald-800">Browser OK</div>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-2xl bg-cloud p-4"><div className="text-xs uppercase text-muted">Version</div><div className="mt-1 font-semibold">{result.browser_version}</div></div>
          <div className="rounded-2xl bg-cloud p-4"><div className="text-xs uppercase text-muted">Page title</div><div className="mt-1 font-semibold">{result.title}</div></div>
          <div className="rounded-2xl bg-cloud p-4"><div className="text-xs uppercase text-muted">Load time</div><div className="mt-1 font-semibold">{result.elapsed_ms} ms</div></div>
          <div className="rounded-2xl bg-cloud p-4"><div className="text-xs uppercase text-muted">HTML length</div><div className="mt-1 font-semibold">{result.html_length}</div></div>
        </div>
        <div>
          <h2 className="mb-3 text-xl font-semibold">Screenshot Preview</h2>
          <img src={`${browserScreenshotUrl()}?v=${screenshotVersion}`} alt="Screenshot Preview" className="w-full rounded-2xl border border-cloud" />
        </div>
      </div>}
    </section>
  </main>;
}
