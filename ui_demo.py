"""Zero-dependency browser demo for the K4-L3B retrieval lab."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bench import make_chunker
from ingest import build_knowledge_base, resolve_embedding_from_env
from src.agent import KnowledgeBaseAgent
from src.llm import resolve_llm_from_env


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "ecommerce" / "shopee"
SLIDES_PATH = ROOT / "slides.html"


def watched_files() -> list[Path]:
    """Return the small set of files that can change the local demo behavior."""
    files = [ROOT / ".env", ROOT / "ui_demo.py", SLIDES_PATH, ROOT / "ingest.py", ROOT / "bench.py"]
    files.extend((ROOT / "src").glob("*.py"))
    files.extend(DATA_DIR.glob("*.md"))
    return files


def watch_snapshot() -> dict[Path, int | None]:
    return {path: path.stat().st_mtime_ns if path.exists() else None for path in watched_files()}


def demo_llm(prompt: str) -> str:
    """Deterministic stand-in so the UI works without an API key."""
    matches = re.findall(r"Content:\n(.*?)(?=\n\n\[\d+\]|\Z)", prompt, flags=re.DOTALL)
    if not matches:
        return "Không tìm thấy nội dung đủ liên quan để tạo câu trả lời."
    answer = " ".join(matches[0].split())
    if len(answer) > 480:
        answer = answer[:477].rstrip() + "..."
    return f"Theo đoạn trích [1], {answer}"


demo_llm._backend_name = "demo mock LLM"


class DemoService:
    strategies = ("fixed", "sentence", "recursive", "heading")

    def __init__(self) -> None:
        self.embedding = resolve_embedding_from_env()
        self.llm = resolve_llm_from_env(demo_llm)
        self.stores = {}

    def store_for(self, strategy: str):
        if strategy not in {"fixed", "sentence", "recursive", "heading"}:
            raise ValueError("strategy must be fixed, sentence, recursive, or heading")
        if strategy not in self.stores:
            self.stores[strategy] = build_knowledge_base(
                DATA_DIR,
                embedding_fn=self.embedding,
                chunker=make_chunker(strategy),
            )
        return self.stores[strategy]

    def retrieve(self, question: str, strategy: str, audience: str, top_k: int) -> dict:
        store = self.store_for(strategy)
        metadata_filter = {"audience": audience} if audience in {"buyer", "seller", "both"} else None
        results = store.search_with_filter(question, top_k=top_k, metadata_filter=metadata_filter)
        return {
            "question": question,
            "strategy": strategy,
            "audience": audience,
            "embedding_backend": getattr(self.embedding, "_backend_name", "mock"),
            "llm_backend": getattr(self.llm, "_backend_name", "fallback"),
            "collection_size": store.get_collection_size(),
            "results": results,
        }

    def answer_from_results(self, question: str, strategy: str, results: list[dict]) -> str:
        """Generate one grounded answer from the already retrieved evidence."""
        agent = KnowledgeBaseAgent(store=self.store_for(strategy), llm_fn=self.llm)
        return agent._answer_from_results(question, results)

    def search(self, question: str, strategy: str, audience: str, top_k: int) -> dict:
        payload = self.retrieve(question, strategy, audience, top_k)
        payload["answer"] = self.answer_from_results(question, strategy, payload["results"])
        return payload

    @staticmethod
    def _friendly_retrieval_error(error: Exception) -> str:
        """Keep provider failures useful in the demo trace without dumping API payloads."""
        message = str(error)
        if "RESOURCE_EXHAUSTED" in message or "quota" in message.lower():
            return "Embedding provider đã hết quota; strategy này chưa chạy được."
        return "Không thể tạo index hoặc embedding cho strategy này."

    def retrieve_candidates(self, question: str, audience: str, top_k: int) -> tuple[list[dict], list[dict]]:
        """Retrieve per strategy independently so one provider failure does not hide the trace."""
        candidates: list[dict] = []
        trace: list[dict] = []
        for strategy in self.strategies:
            try:
                item = self.retrieve(question, strategy, audience, top_k)
                candidates.append(item)
                top = item["results"][0] if item["results"] else None
                trace.append(
                    {
                        "strategy": strategy,
                        "collection_size": item["collection_size"],
                        "result_count": len(item["results"]),
                        "top_score": top["score"] if top else None,
                        "top_doc": top.get("metadata", {}).get("doc_id") if top else None,
                        "top_chunk": top.get("metadata", {}).get("chunk_index") if top else None,
                        "selected": False,
                    }
                )
            except Exception as error:
                trace.append(
                    {
                        "strategy": strategy,
                        "collection_size": None,
                        "result_count": 0,
                        "top_score": None,
                        "top_doc": None,
                        "top_chunk": None,
                        "selected": False,
                        "error": self._friendly_retrieval_error(error),
                    }
                )
        return candidates, trace

    def search_auto(self, question: str, audience: str, top_k: int) -> dict:
        """Choose the strongest retrieval strategy for this query, then answer once."""
        candidates, trace = self.retrieve_candidates(question, audience, top_k)
        if not candidates:
            raise RuntimeError("Không strategy nào hoàn tất vì embedding provider hiện không sẵn sàng.")
        winner = max(
            candidates,
            key=lambda item: float(item["results"][0]["score"]) if item["results"] else float("-inf"),
        )
        top = winner["results"][0] if winner["results"] else None
        for item in trace:
            item["selected"] = item["strategy"] == winner["strategy"]
        winner["answer"] = self.answer_from_results(question, winner["strategy"], winner["results"])
        winner["selection"] = {
            "mode": "auto",
            "selected_strategy": winner["strategy"],
            "reason": (
                f"{winner['strategy']} có top cosine score cao nhất cho query và filter hiện tại"
                + (f" ({float(top['score']):.3f})" if top else "; không có evidence phù hợp")
                + "."
            ),
            "candidates": trace,
        }
        return winner

    def compare(self, question: str, audience: str, top_k: int) -> list[dict]:
        """Return every strategy, including a visible status when one cannot run."""
        candidates, trace = self.retrieve_candidates(question, audience, top_k)
        by_strategy = {item["strategy"]: item for item in candidates}
        return [
            by_strategy.get(
                item["strategy"],
                {
                    "question": question,
                    "strategy": item["strategy"],
                    "audience": audience,
                    "embedding_backend": getattr(self.embedding, "_backend_name", "mock"),
                    "collection_size": 0,
                    "results": [],
                    "error": item["error"],
                },
            )
            for item in trace
        ]


SERVICE = DemoService()


PAGE = r"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PolicyLens · Không gian bằng chứng</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@400;500;600;700&display=swap');
    :root { --canvas:#f8fafc; --surface:#fff; --surface-soft:#f1f5f9; --ink:#172033; --muted:#475569; --line:#dbeafe; --navy:#1e3a8a; --blue:#1e40af; --blue-soft:#eff6ff; --green:#047857; --green-soft:#ecfdf5; --amber:#b45309; --amber-soft:#fff7ed; --red:#b91c1c; --shadow:0 18px 50px rgba(30,58,95,.08); --shadow-sm:0 8px 24px rgba(30,58,95,.07); --radius:16px; --header:76px; }
    * { box-sizing:border-box; }
    html { scroll-behavior:smooth; scroll-padding-top:calc(var(--header) + 16px); }
    body { margin:0; background:var(--canvas); color:var(--ink); font-family:"Fira Sans",system-ui,sans-serif; font-size:16px; line-height:1.55; }
    button,input,select { font:inherit; }
    button { cursor:pointer; }
    button:disabled { cursor:wait; opacity:.72; }
    button:focus-visible,input:focus-visible,select:focus-visible { outline:3px solid rgba(37,99,235,.32); outline-offset:3px; }
    .skip-link { position:fixed; top:10px; left:10px; z-index:20; transform:translateY(-150%); background:var(--navy); color:#fff; padding:10px 14px; border-radius:10px; font-weight:700; }
    .skip-link:focus { transform:translateY(0); }
    .shell { width:min(1220px,calc(100% - 40px)); margin:0 auto; }
    header { min-height:var(--header); border-bottom:1px solid rgba(223,230,239,.9); background:rgba(255,255,255,.94); backdrop-filter:blur(16px); position:sticky; top:0; z-index:5; }
    .nav { min-height:var(--header); display:flex; align-items:center; justify-content:space-between; gap:24px; }
    .brand { display:flex; align-items:center; gap:12px; min-width:0; }
    .mark { width:38px; height:38px; display:grid; place-items:center; background:var(--navy); color:#fff; border-radius:12px; box-shadow:0 8px 18px rgba(30,58,95,.16); }
    .brand-name { font-family:"Fira Code",monospace; font-size:15px; font-weight:700; letter-spacing:-.04em; }
    .brand small { display:block; color:var(--muted); font-size:11px; font-weight:700; letter-spacing:.1em; text-transform:uppercase; }
    .nav-right { display:flex; align-items:center; gap:18px; }
    .nav-link { color:var(--blue); font-size:13px; font-weight:800; text-decoration:none; white-space:nowrap; }
    .nav-link:hover { text-decoration:underline; text-underline-offset:3px; }
    .nav-status { display:flex; align-items:center; gap:7px; color:var(--muted); font-size:13px; font-weight:600; }
    .status-dot { width:8px; height:8px; border-radius:50%; background:#10b981; box-shadow:0 0 0 4px #d1fae5; }
    main { padding:54px 0 72px; }
    .hero { margin:0 0 24px; }
    .eyebrow { display:inline-flex; align-items:center; gap:8px; color:var(--blue); font-size:12px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }
    .eyebrow::before { content:""; width:24px; height:2px; background:var(--blue); }
    h1,h2,h3 { font-family:"Fira Sans",system-ui,sans-serif; }
    h1 { max-width:none; margin:13px 0 13px; font-size:clamp(34px,5vw,58px); line-height:1.04; letter-spacing:-.065em; text-wrap:balance; }
    .lede { color:var(--muted); max-width:700px; font-size:18px; margin:0; }
    .panel { background:var(--surface); border:1px solid var(--line); border-radius:var(--radius); box-shadow:var(--shadow-sm); }
    .search-panel { padding:23px; margin-bottom:22px; }
    .explain-panel { padding:22px; margin-bottom:22px; }
    .explain-head { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; }
    .explain-head > div { flex:1; min-width:0; }
    .explain-head h2 { margin-top:5px; font-size:21px; }
    .explain-copy { max-width:none; margin:5px 0 0; color:var(--muted); font-size:13px; }
    .pipeline { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:10px; margin-top:18px; }
    .flow-step { position:relative; min-width:0; padding:13px 12px; border:1px solid var(--line); border-radius:13px; background:var(--surface-soft); transition:border-color .2s ease,background .2s ease,box-shadow .2s ease; }
    .flow-step:not(:last-child)::after { content:"→"; position:absolute; top:50%; right:-15px; z-index:1; color:#94a3b8; font-size:18px; transform:translateY(-50%); }
    .flow-step.done { border-color:#9ed9c7; background:var(--green-soft); box-shadow:0 7px 16px rgba(4,120,87,.08); }
    .flow-step.running { border-color:#9bbcf5; background:var(--blue-soft); box-shadow:0 7px 16px rgba(37,99,235,.1); }
    .flow-index { display:block; margin-bottom:8px; color:var(--blue); font-family:"Fira Code",monospace; font-size:10px; font-weight:800; }
    .flow-step strong { display:block; color:var(--ink); font-size:13px; line-height:1.25; }
    .flow-step small { display:block; margin-top:5px; color:var(--muted); font-size:11px; line-height:1.35; }
    .explain-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:14px; }
    .method-card { min-width:0; padding:16px; border:1px solid var(--line); border-radius:14px; background:linear-gradient(145deg,#fff,#f7faff); }
    .method-label { color:var(--blue); font-size:10px; font-weight:800; letter-spacing:.1em; text-transform:uppercase; }
    .method-card h3 { margin:5px 0 5px; font-size:16px; }
    .method-card p { margin:0; color:var(--muted); font-size:13px; line-height:1.5; }
    .method-card:nth-child(2) p,.method-points,.embedding-chain { display:none; }
    .method-points { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:13px; }
    .method-point { padding:9px 10px; border-radius:10px; background:var(--surface-soft); }
    .method-point span { display:block; color:var(--muted); font-size:11px; }
    .method-point strong { display:block; margin-top:3px; color:var(--ink); font-size:12px; line-height:1.3; }
    .embedding-chain { display:flex; align-items:center; flex-wrap:wrap; gap:6px; margin-top:13px; color:var(--blue); font-family:"Fira Code",monospace; font-size:11px; font-weight:700; }
    .embedding-chain span { padding:6px 8px; border:1px solid #bfd2ef; border-radius:8px; background:var(--blue-soft); }
    .embedding-chain b { color:#94a3b8; }
    .method-points,.embedding-chain,.method-card:nth-child(2) p { display:none; }
    .decision-log { margin-top:14px; padding:14px; border:1px solid var(--line); border-radius:14px; background:#fbfdff; }
    .decision-log.empty { color:var(--muted); font-size:13px; }
    .decision-head { display:flex; align-items:flex-start; justify-content:space-between; gap:14px; }
    .decision-head strong { color:var(--navy); font-size:14px; }
    .decision-head p { margin:3px 0 0; color:var(--muted); font-size:12px; }
    .trace-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin-top:11px; }
    .trace-item { min-width:0; padding:10px; border:1px solid var(--line); border-radius:10px; background:#fff; }
    .trace-item.selected { border-color:#86cbb5; background:var(--green-soft); box-shadow:inset 0 0 0 1px rgba(4,120,87,.08); }
    .trace-item.failed { border-color:#f4c7b2; background:var(--amber-soft); }
    .trace-item strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--ink); font-size:12px; }
    .trace-item span { display:block; margin-top:4px; color:var(--muted); font-size:11px; line-height:1.3; }
    .trace-item.selected span:first-of-type { color:var(--green); font-weight:800; }
    .panel-kicker { color:var(--blue); font-size:11px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }
    .query-label { display:block; margin:7px 0 10px; color:var(--ink); font-family:"Fira Sans",system-ui,sans-serif; font-size:17px; font-weight:600; }
    .query-row { display:flex; gap:10px; }
    .query-row input { flex:1; min-width:0; min-height:54px; border:1px solid #cbd5e1; border-radius:12px; padding:13px 16px; color:var(--ink); background:#fff; box-shadow:inset 0 1px 2px rgba(15,23,42,.03); }
    .query-row input::placeholder { color:#94a3b8; }
    .sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
    .primary { min-height:54px; border:0; border-radius:12px; background:var(--blue); color:#fff; padding:0 20px; font-weight:800; box-shadow:0 8px 18px rgba(37,99,235,.2); transition:transform .2s ease,background .2s ease,box-shadow .2s ease; }
    .primary:hover:not(:disabled) { background:#1d4ed8; transform:translateY(-1px); box-shadow:0 10px 22px rgba(37,99,235,.25); }
    .button-content { display:inline-flex; align-items:center; gap:8px; }
    .button-content svg { width:17px; height:17px; }
    .suggestions { margin-top:17px; }
    .suggestions p { margin:0 0 8px; color:var(--muted); font-size:13px; font-weight:700; }
    .suggestion-list { display:flex; flex-wrap:wrap; gap:8px; }
    .suggestion { min-height:42px; border:1px solid #cbd5e1; border-radius:10px; padding:7px 11px; background:#fff; color:var(--navy); font-size:13px; font-weight:700; text-align:left; transition:border-color .2s ease,background .2s ease,color .2s ease; }
    .suggestion:hover { border-color:var(--blue); background:var(--blue-soft); color:var(--blue); }
    .suggestion:active,.primary:active:not(:disabled) { transform:translateY(1px); }
    .advanced { margin-top:18px; border-top:1px solid var(--line); }
    .advanced summary { display:flex; align-items:center; justify-content:space-between; min-height:48px; color:var(--navy); cursor:pointer; font-size:14px; font-weight:800; list-style:none; }
    .advanced summary::-webkit-details-marker { display:none; }
    .advanced summary::after { content:"⌄"; color:var(--muted); font-size:18px; transition:transform .2s ease; }
    .advanced[open] summary::after { transform:rotate(180deg); }
    .advanced-help { margin:0 0 12px; color:var(--muted); font-size:13px; }
    .controls { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }
    .field { display:grid; gap:6px; }
    .field > span { color:var(--muted); font-size:13px; font-weight:700; }
    select { width:100%; min-height:44px; border:1px solid var(--line); border-radius:10px; padding:9px 11px; color:var(--ink); background:#fff; }
    .search-hint { display:none; }
    kbd { border:1px solid var(--line); border-bottom-width:2px; border-radius:5px; padding:1px 5px; background:var(--surface-soft); color:var(--ink); font-family:inherit; font-size:11px; }
    .status { min-height:24px; margin-top:13px; color:var(--muted); font-size:13px; }
    .status.error { color:var(--red); }
    .status.loading { color:var(--blue); }
    .grid { display:grid; grid-template-columns:minmax(0,1.03fr) minmax(0,.97fr); gap:22px; align-items:start; }
    .grid.initial { align-items:stretch; }
    .section-head { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; padding:22px 22px 0; }
    h2 { margin:0; font-size:18px; letter-spacing:-.03em; }
    .subtle { color:var(--muted); font-size:13px; margin:4px 0 0; }
    .backend-stack { display:none; }
    .badge { display:inline-flex; align-items:center; border-radius:999px; padding:5px 9px; background:var(--blue-soft); color:var(--blue); font-size:11px; font-weight:800; white-space:nowrap; }
    .badge.green { background:var(--green-soft); color:var(--green); }
    .answer { min-height:210px; padding:22px; font-size:18px; line-height:1.65; white-space:pre-wrap; }
    .answer.empty,.empty { color:var(--muted); }
    .answer::first-line { font-weight:500; }
    .answer-footer { display:flex; align-items:center; gap:8px; padding:0 22px 20px; color:var(--muted); font-size:12px; }
    .answer-footer svg { width:15px; height:15px; color:var(--green); }
    .answer-query { margin:13px 22px 0; color:var(--muted); font-size:13px; }
    .evidence { padding:17px 22px 22px; display:grid; gap:11px; }
    .result { padding:15px; background:#fff; border:1px solid var(--line); border-radius:14px; transition:border-color .2s ease,box-shadow .2s ease,transform .2s ease; }
    .result:hover { border-color:#b9c9df; box-shadow:0 8px 18px rgba(30,58,95,.06); transform:translateY(-1px); }
    .result-top { display:flex; align-items:center; justify-content:space-between; gap:12px; color:var(--muted); font-size:12px; }
    .result-id { display:flex; align-items:center; min-width:0; gap:8px; }
    .rank { display:grid; flex:0 0 24px; place-items:center; width:24px; height:24px; border-radius:8px; background:var(--navy); color:#fff; font-size:11px; font-weight:800; }
    .result-id strong { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--ink); font-size:13px; }
    .score { color:var(--green); font-weight:800; white-space:nowrap; }
    .score-line { display:flex; justify-content:space-between; gap:10px; margin-top:10px; color:var(--muted); font-size:11px; }
    .score-track { height:5px; margin-top:5px; overflow:hidden; border-radius:999px; background:#e8eef5; }
    .score-track span { display:block; height:100%; border-radius:inherit; background:var(--green); }
    .result p { margin:11px 0 0; font-size:14px; line-height:1.55; }
    .meta { display:flex; flex-wrap:wrap; gap:6px; margin-top:11px; }
    .chip { max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; border:1px solid var(--line); border-radius:999px; color:var(--muted); padding:4px 8px; font-size:11px; }
    .source-link { display:block; max-width:100%; margin-top:10px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--blue); font-size:12px; text-decoration:none; }
    .source-link:hover { text-decoration:underline; }
    .empty-state { padding:18px; border:1px dashed #b9c9df; border-radius:14px; background:var(--blue-soft); }
    .empty-state h3 { margin:0; font-size:15px; }
    .empty-state p { margin:6px 0 12px; color:var(--muted); font-size:13px; }
    .text-button { min-height:38px; border:0; border-radius:9px; padding:7px 10px; background:#fff; color:var(--blue); font-weight:800; cursor:pointer; }
    .advanced > .text-button { margin-top:12px; }
    .benchmark { margin-top:22px; }
    .benchmark summary { display:flex; align-items:center; justify-content:space-between; min-height:58px; padding:0 20px; color:var(--navy); cursor:pointer; font-family:"Fira Sans",system-ui,sans-serif; font-size:16px; font-weight:700; list-style:none; }
    .benchmark summary .summary-note { margin-left:auto; margin-right:12px; color:var(--muted); font-size:12px; font-weight:600; }
    .benchmark summary::-webkit-details-marker { display:none; }
    .benchmark summary::after { content:"⌄"; color:var(--muted); font-size:20px; transition:transform .2s ease; }
    .benchmark[open] summary::after { transform:rotate(180deg); }
    .benchmark-body { padding:0 20px 20px; border-top:1px solid var(--line); }
    .benchmark-copy { margin:14px 0; color:var(--muted); font-size:13px; }
    .benchmark-action { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:14px; border:1px solid var(--line); border-radius:14px; background:var(--surface-soft); }
    .benchmark-action p { margin:0; color:var(--muted); font-size:13px; }
    .compare-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }
    .strategy-card { min-width:0; padding:18px; }
    .strategy-head { display:flex; align-items:flex-start; justify-content:space-between; gap:10px; }
    .strategy-head h3 { margin:0; font-size:16px; letter-spacing:-.03em; }
    .strategy-index { display:grid; place-items:center; width:28px; height:28px; border-radius:9px; background:var(--blue-soft); color:var(--blue); font-size:12px; font-weight:800; }
    .strategy-description { min-height:42px; margin:8px 0 0; color:var(--muted); font-size:13px; }
    .metric { display:flex; align-items:baseline; gap:7px; margin:17px 0 4px; color:var(--navy); font-family:"Fira Sans",system-ui,sans-serif; }
    .metric strong { font-size:30px; line-height:1; }
    .metric span { color:var(--muted); font-family:"Fira Sans",system-ui,sans-serif; font-size:12px; font-weight:700; }
    .strategy-meta { color:var(--muted); font-size:12px; }
    .mini-result { margin-top:15px; padding-top:13px; border-top:1px solid var(--line); font-size:13px; }
    .mini-result strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .compare-summary { display:none; margin:14px 0; padding:13px 15px; border-left:3px solid var(--blue); border-radius:10px; background:var(--blue-soft); color:var(--muted); font-size:13px; }
    .compare-summary.visible { display:block; }
    .compare-summary strong { color:var(--navy); }
    .comparison-stats { display:grid; grid-template-columns:repeat(3,1fr); gap:7px; margin-top:13px; }
    .comparison-stat { padding:8px; border-radius:9px; background:var(--surface-soft); }
    .comparison-stat strong { display:block; color:var(--navy); font-size:17px; line-height:1; }
    .comparison-stat span { display:block; margin-top:4px; color:var(--muted); font-size:10px; line-height:1.2; }
    .mini-evidence { display:grid; gap:7px; margin-top:12px; }
    .mini-evidence-item { padding:8px 9px; border:1px solid var(--line); border-radius:9px; background:#fff; }
    .mini-evidence-item strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--ink); font-size:11px; }
    .mini-evidence-item span { display:block; margin-top:3px; overflow:hidden; color:var(--muted); font-size:11px; line-height:1.35; text-overflow:ellipsis; white-space:nowrap; }
    .footer-note { display:flex; align-items:flex-start; gap:8px; margin-top:30px; color:var(--muted); font-size:13px; }
    .footer-note svg { flex:0 0 16px; margin-top:3px; color:var(--blue); }
    code { border-radius:5px; padding:2px 5px; background:var(--surface-soft); color:var(--navy); font-size:12px; }
    @media (min-width:981px) { h1,.explain-copy { white-space:nowrap; } }
    @media (max-width:980px) { .compare-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .pipeline { grid-template-columns:repeat(3,minmax(0,1fr)); } .trace-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .flow-step:not(:last-child)::after { display:none; } }
    @media (max-width:820px) { .grid,.explain-grid { grid-template-columns:1fr; } .controls { grid-template-columns:1fr; } }
    @media (max-width:620px) { .shell { width:min(100% - 28px,1220px); } .nav { min-height:64px; padding:10px 0; flex-direction:row; gap:8px; } .brand small,.nav-status { display:none; } .nav-right { width:auto; gap:0; } main { padding-top:34px; } h1 { font-size:38px; } .lede { font-size:17px; } .query-row,.benchmark-action { flex-direction:column; align-items:stretch; } .primary { width:100%; } .compare-grid,.trace-grid { grid-template-columns:1fr; } .pipeline { grid-template-columns:repeat(2,minmax(0,1fr)); } .method-points { grid-template-columns:1fr; } .benchmark summary .summary-note { display:none; } .section-head { padding:18px 18px 0; } .answer { padding:18px; } .answer-footer { padding:0 18px 18px; } .evidence { padding:15px 18px 18px; } }
    @media (prefers-reduced-motion:reduce) { *,*::before,*::after { scroll-behavior:auto!important; transition:none!important; } }
  </style>
</head>
<body>
  <a class="skip-link" href="#main-content">Bỏ qua đến nội dung chính</a>
  <header><div class="shell nav"><a class="brand" href="#main-content" aria-label="PolicyLens về nội dung chính"><span class="mark" aria-hidden="true"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5z"/><path d="M4 5.5v16M8 7h8M8 11h8"/></svg></span><span><span class="brand-name">PolicyLens / Lab</span><small>Data Foundations · Embedding &amp; Vector Store</small></span></a><div class="nav-right"><a class="nav-link" href="/slides.html" target="_top">Mở slides</a><span class="nav-status"><i class="status-dot" aria-hidden="true"></i>Knowledge base sẵn sàng</span></div></div></header>
  <main id="main-content" class="shell">
    <section class="hero" aria-labelledby="page-title"><h1 id="page-title">Tra cứu chính sách có nguồn kiểm chứng.</h1></section>
    <section id="search-view">
      <div class="panel search-panel"><div class="panel-kicker">01 · Retrieval workspace</div><label class="query-label" for="question">Query bạn muốn kiểm tra</label><div class="query-row"><input id="question" value="Người bán phải phản hồi yêu cầu trả hàng trong bao lâu?" placeholder="Ví dụ: Ai chịu phí vận chuyển khi trả hàng?" autocomplete="off"><button type="button" class="primary" id="search"><span class="button-content"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg><span>Chạy retrieval</span></span></button></div><div class="suggestions" aria-label="Benchmark queries gợi ý"><p>Hoặc chọn benchmark query:</p><div class="suggestion-list"><button type="button" class="suggestion" data-question="Trong bao lâu người mua có thể yêu cầu trả hàng hoặc hoàn tiền?">Thời hạn trả hàng/hoàn tiền?</button><button type="button" class="suggestion" data-question="Các điều kiện cơ bản để được bảo hành là gì?">Điều kiện bảo hành?</button><button type="button" class="suggestion" data-question="Ai chịu chi phí vận chuyển chiều hoàn trả?">Ai chịu phí vận chuyển?</button></div></div><details class="advanced" open><summary>Retrieval configuration</summary><p class="advanced-help">Thay đổi cấu hình để quan sát chất lượng retrieval và metadata utility.</p><div class="controls"><label class="field" for="strategy"><span>Chunking strategy</span><select id="strategy"><option value="sentence">Sentence</option><option value="fixed">Fixed-size</option><option value="recursive">Recursive</option><option value="heading">Heading-aware</option></select></label><label class="field" for="audience"><span>Metadata filter · audience</span><select id="audience"><option value="all">Tất cả đối tượng</option><option value="buyer">Người mua</option><option value="seller">Người bán</option><option value="both">Cả hai</option></select></label><label class="field" for="top-k"><span>Evidence returned (top-k)</span><select id="top-k"><option value="3">3 chunks</option><option value="5">5 chunks</option></select></label></div></details><div class="search-hint"><span>Nhấn</span><kbd>Enter</kbd><span>để chạy retrieval</span></div><div id="status" class="status" role="status" aria-live="polite"></div></div>
      <section class="panel explain-panel" aria-labelledby="pipeline-title"><div class="explain-head"><div><div class="panel-kicker">How one query is answered</div><h2 id="pipeline-title">Retrieval pipeline: từ Query đến grounded answer</h2><p class="explain-copy">Theo dõi pipeline, lý do chọn strategy và ảnh hưởng của metadata filter.</p></div><span id="pipeline-status" class="badge">Chưa chạy query</span></div><div class="pipeline" aria-label="Retrieval pipeline"><div class="flow-step"><span class="flow-index">01</span><strong>Query</strong><small>Câu hỏi người dùng</small></div><div class="flow-step"><span class="flow-index">02</span><strong>Chunking</strong><small>Tách document thành chunks</small></div><div class="flow-step"><span class="flow-index">03</span><strong>Embedding</strong><small id="flow-embedding">Text → vector</small></div><div class="flow-step"><span class="flow-index">04</span><strong>Vector store</strong><small>Cosine similarity</small></div><div class="flow-step"><span class="flow-index">05</span><strong>Top-k evidence</strong><small>Chọn chunks liên quan</small></div><div class="flow-step"><span class="flow-index">06</span><strong>RAG Agent</strong><small>Answer có grounding</small></div></div><div class="explain-grid"><article class="method-card"><div class="method-label">Selected chunking strategy</div><h3 id="selected-strategy">Sentence</h3><p id="strategy-rule">Chia document theo ranh giới câu để mỗi evidence dễ đọc và giữ trọn ý.</p><div class="method-points"><div class="method-point"><span>Phù hợp khi</span><strong id="strategy-fit">Policy text có câu/điều khoản rõ</strong></div><div class="method-point"><span>Trade-off</span><strong id="strategy-tradeoff">Có thể tạo nhiều chunk hơn</strong></div></div></article><article class="method-card"><div class="method-label">Embedding &amp; ranking</div><h3 id="embedding-model">Embedding model đang cấu hình</h3><p>Document chunk và Query được biến thành vector trong cùng không gian. Hệ thống so sánh bằng cosine similarity, rồi lấy top-k chunks làm context cho Agent.</p><div class="embedding-chain"><span>chunk / query</span><b>→</b><span>vector</span><b>→</b><span>cosine score</span><b>→</b><span>top-k</span></div></article></div></section>
      <div class="grid initial"><section class="panel" aria-labelledby="answer-title"><div class="section-head"><div><h2 id="answer-title">02 · Grounded Agent answer</h2><p class="subtle">Câu trả lời phải được kiểm chứng bằng retrieved evidence</p></div><div class="backend-stack"><span id="embedding-backend" class="badge">mock embedding</span><span id="llm-backend" class="badge green">mock LLM</span></div></div><p id="answer-query" class="answer-query">Agent answer sẽ xuất hiện ở đây.</p><div id="answer" class="answer empty" aria-live="polite">Chọn benchmark query hoặc nhập query của bạn để bắt đầu.</div><div class="answer-footer"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 4.5 6v5c0 4.4 3.2 8.5 7.5 10 4.3-1.5 7.5-5.6 7.5-10V6z"/><path d="m8.5 12 2.2 2.2 4.8-5"/></svg><span>Đối chiếu Agent answer với evidence ở cột bên phải.</span></div></section><section class="panel" aria-labelledby="evidence-title"><div class="section-head"><div><h2 id="evidence-title">03 · Retrieved evidence</h2><p class="subtle">Kiểm tra relevance, score, metadata và source traceability</p></div><span id="count" class="badge">Đang chờ query</span></div><div id="evidence" class="evidence"><div class="empty-state"><h3>Chưa có retrieved evidence</h3><p>Sau khi chạy retrieval, top-k chunks và source tham chiếu sẽ xuất hiện ở đây.</p></div></div></section></div>
      <details class="panel benchmark"><summary><span>So sánh chunking strategies</span><span class="summary-note">Cùng Query · filter · top-k</span><span class="sr-only">— mở để chạy benchmark</span></summary><div class="benchmark-body"><p class="benchmark-copy" id="benchmark-question">Query hiện tại sẽ được dùng cho benchmark.</p><div class="benchmark-action"><p>Chạy cùng query và cùng metadata filter trên Fixed-size, Sentence, Recursive và Heading-aware để so sánh công bằng.</p><button type="button" class="primary" id="compare"><span class="button-content"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/></svg><span>Chạy benchmark</span></span></button></div><div id="compare-status" class="status" role="status" aria-live="polite"></div><div id="compare-summary" class="compare-summary" role="status"></div><div id="compare-results" class="compare-grid" aria-live="polite"></div></div></details>
    </section>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
    async function loadBackendStatus() { try { const response = await fetch('/api/health', { cache: 'no-store' }); const data = await response.json(); setEmbeddingBackend(data.embedding_backend); $('llm-backend').textContent = data.llm_backend || 'mock LLM'; } catch (_) { setEmbeddingBackend('mock embedding'); } }
    const strategyLabels = { auto: 'Auto · chọn strategy tốt nhất', fixed: 'Fixed-size', sentence: 'Sentence', recursive: 'Recursive', heading: 'Heading-aware' };
    const audienceLabels = { all: 'tất cả đối tượng', buyer: 'người mua', seller: 'người bán', both: 'cả hai' };
    const strategyInfo = {
      auto: { summary: 'Chạy 4 strategy và chọn theo score', rule: 'Lý do: top cosine score cao nhất với Query và metadata filter hiện tại.', fit: '', tradeoff: '' },
      fixed: { summary: 'Giữ overlap tại ranh giới', rule: 'Cắt theo kích thước cố định và giữ một phần overlap giữa các chunk.', fit: 'Baseline dễ kiểm soát kích thước', tradeoff: 'Có thể cắt giữa câu hoặc điều khoản' },
      sentence: { summary: 'Chia theo câu', rule: 'Chia document theo ranh giới câu để mỗi evidence dễ đọc và giữ trọn ý.', fit: 'Policy text có câu/điều khoản rõ', tradeoff: 'Có thể tạo nhiều chunk hơn' },
      recursive: { summary: 'Ưu tiên cấu trúc văn bản', rule: 'Thử các separator theo thứ tự, từ đoạn đến câu, để giữ cấu trúc trước khi cắt nhỏ hơn.', fit: 'Văn bản có paragraph lồng nhau', tradeoff: 'Phụ thuộc chunk size và separator' },
      heading: { summary: 'Giữ heading làm ngữ cảnh', rule: 'Đưa heading/section đi cùng nội dung để evidence biết mình thuộc điều khoản nào.', fit: 'Policy có heading/section rõ', tradeoff: 'Section dài cần fallback' },
    };
    const strategyDetails = Object.fromEntries(Object.entries(strategyInfo).map(([key, value]) => [key, value.summary]));
    const setStatus = (message, error = false, loading = false) => { $('status').textContent = message; $('status').className = `status${error ? ' error' : ''}${loading ? ' loading' : ''}`; };
    const decisionLog = document.createElement('div'); decisionLog.id = 'decision-log'; decisionLog.className = 'decision-log empty'; decisionLog.textContent = 'Pipeline trace sẽ hiển thị ở đây. Chọn Auto để chạy cả 4 strategy và xem lý do hệ thống chọn strategy nào.'; document.querySelector('.explain-grid').after(decisionLog);
    const flowSteps = [...document.querySelectorAll('.flow-step')];
    const setPipelineState = (state) => { flowSteps.forEach((step, index) => { step.classList.toggle('done', state === 'done'); step.classList.toggle('running', state === 'running' && index === 2); }); $('pipeline-status').textContent = state === 'done' ? 'Đã hoàn tất retrieval' : state === 'running' ? 'Đang chạy pipeline…' : state === 'error' ? 'Pipeline gặp lỗi' : 'Chưa chạy query'; $('pipeline-status').className = `badge${state === 'done' ? ' green' : ''}`; };
    const setEmbeddingBackend = (backend) => { const label = backend || 'mock embedding'; $('embedding-backend').textContent = label; const dimension = label.includes('gemini-embedding-001') ? ' · 3,072 chiều' : ''; $('embedding-model').textContent = `${label}${dimension}`; $('flow-embedding').textContent = label.includes('mock') ? 'Mock vector' : 'Model → vector'; };
    const updateStrategyExplanation = () => { const key = $('strategy').value; const info = strategyInfo[key] || strategyInfo.sentence; $('selected-strategy').textContent = strategyLabels[key] || key; $('strategy-rule').textContent = info.rule; $('strategy-fit').textContent = info.fit; $('strategy-tradeoff').textContent = info.tradeoff; };
    const strategySelect = $('strategy'); strategySelect.insertAdjacentHTML('afterbegin', '<option value="auto">Auto · chọn strategy tốt nhất</option>'); strategySelect.value = 'auto';
    const topK = $('top-k'); topK.innerHTML = '<option value="1">1 chunk</option><option value="3">3 chunks</option><option value="5">5 chunks</option>'; topK.value = '3';
    const advanced = document.querySelector('.advanced'); const resetButton = document.createElement('button'); resetButton.type = 'button'; resetButton.className = 'text-button'; resetButton.textContent = 'Đặt lại cấu hình'; resetButton.addEventListener('click', () => { $('strategy').value = 'auto'; $('audience').value = 'all'; topK.value = '3'; updateStrategyExplanation(); decisionLog.className = 'decision-log empty'; decisionLog.textContent = 'Pipeline trace sẽ hiển thị ở đây. Chọn Auto để chạy cả 4 strategy và xem lý do hệ thống chọn strategy nào.'; setStatus('Đã đặt lại retrieval configuration.'); }); advanced.appendChild(resetButton);
    const renderEvidence = (results) => { const evidence = $('evidence'); if (!results.length) { evidence.innerHTML = '<div class="empty-state"><h3>Chưa tìm thấy thông tin phù hợp</h3><p>Thử xem tất cả đối tượng hoặc diễn đạt câu hỏi ngắn gọn hơn.</p><button type="button" class="text-button" id="clear-filter">Xem tất cả đối tượng</button></div>'; $('clear-filter').addEventListener('click', () => { $('audience').value = 'all'; document.querySelector('.advanced').open = true; search(); }); return; } evidence.innerHTML = results.map((item, index) => { const metadata = item.metadata || {}; const source = metadata.source_url || metadata.source || ''; const score = Number(item.score); const scoreWidth = Math.max(4, Math.min(100, (score + 1) * 50)); return `<article class="result"><div class="result-top"><div class="result-id"><span class="rank">${index + 1}</span><strong>${escapeHtml(metadata.doc_id || 'không rõ')} · chunk ${escapeHtml(metadata.chunk_index || '?')}</strong></div><span class="score">${score.toFixed(3)}</span></div><div class="score-line"><span>điểm tương đồng</span><span>${escapeHtml(metadata.category || 'chính sách')}</span></div><div class="score-track" aria-hidden="true"><span style="width:${scoreWidth}%"></span></div><p>${escapeHtml(item.content)}</p><div class="meta"><span class="chip">đối tượng: ${escapeHtml(audienceLabels[metadata.audience] || metadata.audience || 'không rõ')}</span><span class="chip">ngôn ngữ: ${escapeHtml(metadata.language || 'không rõ')}</span><span class="chip">${escapeHtml(metadata.retrieved_at || 'chưa có ngày lấy nguồn')}</span></div>${source.startsWith('http') ? `<a class="source-link" href="${escapeHtml(source)}" target="_blank" rel="noreferrer">Mở nguồn ↗</a>` : ''}</article>`; }).join(''); };
    const renderDecisionLog = (data, requestedStrategy) => {
      const selection = data.selection;
      if (!selection || selection.mode !== 'auto') {
        decisionLog.className = 'decision-log';
        decisionLog.innerHTML = `<div class="decision-head"><div><strong>Pipeline trace · Manual selection</strong><p>Bạn chọn <strong>${escapeHtml(strategyLabels[data.strategy] || data.strategy)}</strong>; hệ thống chỉ chạy strategy này. Chọn Auto để benchmark 4 strategy trước khi trả lời.</p></div></div><div class="trace-grid"><div class="trace-item selected"><strong>${escapeHtml(strategyLabels[data.strategy] || data.strategy)} · được dùng</strong><span>top score: ${data.results[0] ? Number(data.results[0].score).toFixed(3) : '—'}</span><span>${data.collection_size} chunks · ${data.results.length} evidence</span></div></div>`;
        return;
      }
      const candidates = selection.candidates || [];
      const completed = candidates.filter((item) => !item.error);
      const winner = candidates.find((item) => item.selected);
      const score = winner && winner.top_score !== null ? Number(winner.top_score).toFixed(3) : '—';
      decisionLog.className = 'decision-log';
      decisionLog.innerHTML = `<div class="decision-head"><div><strong>Pipeline trace · Auto decision</strong><p>Đã hoàn tất ${completed.length}/${candidates.length} strategy với cùng Query, filter và top-k. Chọn <strong>${escapeHtml(strategyLabels[selection.selected_strategy] || selection.selected_strategy)}</strong> vì có top cosine score cao nhất (${score}) trong các strategy đã hoàn tất.</p></div><span class="badge green">Đã chọn ${escapeHtml(strategyLabels[selection.selected_strategy] || selection.selected_strategy)}</span></div><div class="trace-grid">${candidates.map((item) => `<div class="trace-item${item.selected ? ' selected' : ''}${item.error ? ' failed' : ''}"><strong>${escapeHtml(strategyLabels[item.strategy] || item.strategy)}${item.selected ? ' · được chọn' : ''}</strong>${item.error ? `<span>${escapeHtml(item.error)}</span>` : `<span>top score: ${item.top_score === null ? '—' : Number(item.top_score).toFixed(3)}</span><span>${item.collection_size} chunks · ${escapeHtml(item.top_doc || 'không có evidence')}#${item.top_chunk ?? '?'}</span>`}</div>`).join('')}</div>`;
    };
    async function search() {
      const question = $('question').value.trim();
      if (!question) { setStatus('Hãy nhập câu hỏi trước khi tìm kiếm.', true); $('question').focus(); return; }
      const strategy = $('strategy').value;
      const audience = $('audience').value;
      const topKValue = $('top-k').value;
      const button = $('search');
      button.disabled = true;
      button.querySelector('span:last-child').textContent = 'Đang tìm…';
      setPipelineState('running');
      decisionLog.className = 'decision-log empty';
      decisionLog.textContent = strategy === 'auto' ? 'Auto đang retrieve bằng Fixed-size, Sentence, Recursive và Heading-aware để chọn strategy phù hợp nhất cho query này…' : `Đang chạy ${strategyLabels[strategy]} theo lựa chọn của bạn…`;
      setStatus(strategy === 'auto' ? 'Đang benchmark 4 strategy → embedding → vector search...' : `Đang chạy ${strategyLabels[strategy]} → embedding → vector search...`, false, true);
      $('answer-query').textContent = `Đang trả lời với ${strategyLabels[strategy]} · top-${topKValue}`;
      $('answer').className = 'answer empty';
      $('answer').textContent = 'Đang tìm ngữ cảnh phù hợp...';
      $('answer').setAttribute('aria-busy', 'true');
      try {
        const params = new URLSearchParams({ question, strategy, audience, top_k: topKValue });
        const response = await fetch('/api/search?' + params);
        if (!response.ok) { const payload = await response.json().catch(() => ({})); throw new Error(payload.error || 'Search request failed'); }
        const data = await response.json();
        $('answer').className = 'answer';
        $('answer').textContent = data.answer;
        $('answer').removeAttribute('aria-busy');
        $('answer-query').textContent = `Trả lời cho: “${question}” · ${strategyLabels[data.strategy] || data.strategy}`;
        setEmbeddingBackend(data.embedding_backend);
        $('llm-backend').textContent = data.llm_backend || 'LLM dự phòng';
        $('count').textContent = `${data.results.length} nguồn · top-${topKValue}`;
        renderEvidence(data.results);
        renderDecisionLog(data, strategy);
        setPipelineState('done');
        const incomplete = data.selection ? data.selection.candidates.filter((item) => item.error).length : 0;
        setStatus(data.selection ? `Auto đã chọn ${strategyLabels[data.strategy] || data.strategy}: top score cao nhất${incomplete ? ` trong ${4 - incomplete}/4 strategy đã hoàn tất` : ' trong 4 strategy'} cho filter ${audienceLabels[data.audience] || data.audience}.` : `Đã tìm thấy ${data.results.length} evidence với ${strategyLabels[data.strategy] || data.strategy} và filter ${audienceLabels[data.audience] || data.audience}.`);
      } catch (error) {
        $('answer').removeAttribute('aria-busy');
        $('answer').className = 'answer empty';
        $('answer').textContent = 'Không thể hoàn thành truy vấn. Hãy kiểm tra server hoặc thử lại.';
        $('answer-query').textContent = 'Có lỗi khi xử lý câu hỏi.';
        decisionLog.className = 'decision-log empty';
        decisionLog.textContent = `Pipeline trace không hoàn tất. ${error.message || 'Kiểm tra terminal server rồi chạy lại query.'}`;
        setPipelineState('error');
        setStatus('Không thể chạy truy xuất. Kiểm tra terminal server.', true);
      } finally {
        button.disabled = false;
        button.querySelector('span:last-child').textContent = 'Tìm câu trả lời';
      }
    }
    const renderComparison = (strategies) => {
      const ranked = strategies.map((item) => ({ item, score: item.results[0] ? Number(item.results[0].score) : -Infinity })).sort((left, right) => right.score - left.score);
      const best = ranked[0];
      $('compare-summary').innerHTML = best && best.item.results[0] ? `<strong>${escapeHtml(strategyLabels[best.item.strategy] || best.item.strategy)}</strong> đang có top score cao nhất (${best.score.toFixed(3)}) cho query này. Đây là tín hiệu retrieval, không phải kết luận strategy tốt nhất.` : 'Không có evidence để so sánh.';
      $('compare-summary').className = 'compare-summary visible';
      $('compare-results').innerHTML = strategies.map((item, index) => {
        const top = item.results[0];
        const topScore = top ? Number(top.score).toFixed(3) : '—';
        const miniEvidence = item.results.slice(0, 3).map((result, resultIndex) => { const metadata = result.metadata || {}; const snippet = String(result.content || '').replace(/\s+/g, ' ').slice(0, 118); return `<div class="mini-evidence-item"><strong>#${resultIndex + 1} · ${escapeHtml(metadata.doc_id || 'không rõ')} · chunk ${escapeHtml(metadata.chunk_index || '?')} · ${Number(result.score).toFixed(3)}</strong><span>${escapeHtml(snippet)}${snippet.length >= 118 ? '…' : ''}</span></div>`; }).join('');
        return `<article class="panel strategy-card"><div class="strategy-head"><h3>${escapeHtml(strategyLabels[item.strategy] || item.strategy)}</h3><span class="strategy-index">0${index + 1}</span></div><p class="strategy-description">${escapeHtml(strategyDetails[item.strategy] || 'Chunking strategy')}</p><div class="comparison-stats"><div class="comparison-stat"><strong>${item.collection_size}</strong><span>chunks trong index</span></div><div class="comparison-stat"><strong>${item.results.length}</strong><span>evidence trả về</span></div><div class="comparison-stat"><strong>${topScore}</strong><span>top cosine score</span></div></div><div class="strategy-meta">${escapeHtml(item.embedding_backend)} · cùng query · cùng filter</div>${item.error ? `<div class="mini-result empty">${escapeHtml(item.error)}</div>` : top ? `<div class="mini-result"><strong>Top evidence · ${escapeHtml(top.metadata.doc_id || 'không rõ')}#${escapeHtml(top.metadata.chunk_index || '?')}</strong><span class="subtle">${escapeHtml(String(top.content || '').replace(/\s+/g, ' ').slice(0, 145))}…</span></div><div class="mini-evidence">${miniEvidence}</div>` : '<div class="mini-result empty">Không có evidence trả về</div>'}</article>`;
      }).join('');
    };
    async function compare() {
      const question = $('question').value.trim();
      const status = $('compare-status');
      const button = $('compare');
      if (!question) { status.textContent = 'Hãy nhập câu hỏi ở phần tra cứu trước khi chạy benchmark.'; status.className = 'status error'; $('question').focus(); return; }
      button.disabled = true;
      button.querySelector('span:last-child').textContent = 'Đang chạy…';
      status.className = 'status loading';
      status.textContent = `Đang chạy cùng query trên 4 chunking strategies · top-${topK.value}...`;
      $('compare-results').innerHTML = '';
      $('compare-summary').className = 'compare-summary';
      try {
        const params = new URLSearchParams({ question, audience: $('audience').value, top_k: topK.value });
        const response = await fetch('/api/compare?' + params);
        if (!response.ok) { const payload = await response.json().catch(() => ({})); throw new Error(payload.error || 'Compare request failed'); }
        const data = await response.json();
        renderComparison(data.strategies);
        status.className = 'status';
        status.textContent = 'Đã chạy xong. So sánh cách chia chunk, collection size, cosine score và evidence thực tế.';
      } catch (error) {
        status.className = 'status error';
        status.textContent = 'Không thể chạy benchmark. Kiểm tra terminal server và thử lại.';
      } finally {
        button.disabled = false;
        button.querySelector('span:last-child').textContent = 'Chạy benchmark';
      }
    }
    const originalSearch = search; search = (...args) => { document.querySelector('.grid').classList.remove('initial'); return originalSearch(...args); };
    document.querySelectorAll('.suggestion').forEach((button) => button.addEventListener('click', () => { $('question').value = button.dataset.question; search(); }));
    const updateBenchmarkQuestion = () => { const question = $('question').value.trim(); $('benchmark-question').textContent = question ? `Dùng câu hỏi hiện tại: “${question}”` : 'Nhập câu hỏi ở phần tra cứu để chạy benchmark.'; };
    $('search').addEventListener('click', search); $('strategy').addEventListener('change', updateStrategyExplanation); $('question').addEventListener('input', updateBenchmarkQuestion); $('question').addEventListener('keydown', (event) => { if (event.key === 'Enter') search(); }); $('compare').addEventListener('click', compare); updateStrategyExplanation(); setPipelineState('idle'); updateBenchmarkQuestion(); loadBackendStatus();
    let pageVersion = null;
    async function refreshWhenSourceChanges() { try { const response = await fetch('/api/version', { cache: 'no-store' }); const { version } = await response.json(); if (pageVersion && pageVersion !== version) window.location.reload(); pageVersion = version; } catch (_) { /* The local server may be restarting after a saved change. */ } }
    refreshWhenSourceChanges(); window.setInterval(refreshWhenSourceChanges, 900);
  </script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload: str, content_type: str = "text/html; charset=utf-8", status: int = 200) -> None:
        encoded = payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(PAGE)
            return
        if parsed.path in {"/slides", "/slides.html"}:
            if not SLIDES_PATH.exists():
                self._send("Slides not found", "text/plain; charset=utf-8", 404)
                return
            self._send(SLIDES_PATH.read_text(encoding="utf-8"))
            return
        if parsed.path == "/api/health":
            self._send(
                json.dumps(
                    {
                        "ok": True,
                        "embedding_backend": getattr(SERVICE.embedding, "_backend_name", "mock"),
                        "llm_backend": getattr(SERVICE.llm, "_backend_name", "fallback"),
                    }
                ),
                "application/json; charset=utf-8",
            )
            return
        if parsed.path == "/api/version":
            self._send(
                json.dumps({"version": max(path.stat().st_mtime_ns for path in (ROOT / "ui_demo.py", SLIDES_PATH) if path.exists())}),
                "application/json; charset=utf-8",
            )
            return
        if parsed.path in {"/api/search", "/api/compare"}:
            params = parse_qs(parsed.query)
            question = params.get("question", [""])[0].strip()
            if not question:
                self._send(json.dumps({"error": "question is required"}), "application/json; charset=utf-8", 400)
                return
            try:
                if parsed.path == "/api/search":
                    strategy = params.get("strategy", ["sentence"])[0]
                    audience = params.get("audience", ["all"])[0]
                    top_k = min(5, max(1, int(params.get("top_k", ["3"])[0])))
                    payload = SERVICE.search_auto(question, audience, top_k) if strategy == "auto" else SERVICE.search(question, strategy, audience, top_k)
                else:
                    audience = params.get("audience", ["all"])[0]
                    top_k = min(5, max(1, int(params.get("top_k", ["3"])[0])))
                    payload = {"top_k": top_k, "strategies": SERVICE.compare(question, audience, top_k)}
                self._send(json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as error:
                status = 503 if "embedding provider" in str(error).lower() else 500
                self._send(json.dumps({"error": str(error)}, ensure_ascii=False), "application/json; charset=utf-8", status)
            return
        self._send("Not found", "text/plain; charset=utf-8", 404)

    def log_message(self, format: str, *args) -> None:
        return


def serve(port: int) -> int:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"PolicyLens running at http://localhost:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping PolicyLens", flush=True)
    finally:
        server.server_close()
    return 0


def run_reloader(port: int) -> int:
    """Restart the localhost server after a saved source or corpus change."""
    command = [sys.executable, str(Path(__file__).resolve()), "--port", str(port), "--no-reload"]
    process: subprocess.Popen[object] | None = None
    try:
        while True:
            before = watch_snapshot()
            process = subprocess.Popen(command)
            while process.poll() is None:
                time.sleep(0.7)
                if watch_snapshot() != before:
                    print("Change detected — reloading PolicyLens...", flush=True)
                    process.terminate()
                    process.wait(timeout=5)
                    break
            else:
                return process.returncode or 0
    except KeyboardInterrupt:
        print("\nStopping PolicyLens", flush=True)
        return 0
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the K4-L3B browser demo")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-reload", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    return serve(args.port) if args.no_reload else run_reloader(args.port)


if __name__ == "__main__":
    raise SystemExit(main())
