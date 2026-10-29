"""Supervisor-centric agent loop with budgets, checkpoints and tracing."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from ..agents.base import (
    compact_cv_result,
    compact_json,
    message_to_dict,
    parse_tool_arguments,
    tool_reply,
)
from ..agents.critic_agent import CriticAgent
from ..agents.geometry_agent import GeometryAgent
from ..agents.schemas import SUPERVISOR_NAMES, SUPERVISOR_TOOLS
from ..agents.supervisor import initial_messages, step_nudge
from ..agents.tikz_agent import TikZAgent
from ..config import Settings, load_settings
from ..cv_tools.registry import call_cv_tool
from ..llm.client import LLMClient
from ..state.evidence_store import EvidenceStore
from ..state.schemas import ActionRecord, GeometricEvidenceState
from ..tools import compile_tikz, render_pdf, validate_compilation
from ..vision.context import VisualContextManager
from .ingest import ingest_cv_result


class GeoAgentRunner:
    """One end-to-end run on one image."""

    def __init__(
        self,
        image_path: str | Path,
        *,
        settings: Settings | None = None,
        run_overrides: dict[str, Any] | None = None,
        run_dir: str | Path | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.image_path = str(Path(image_path).resolve())
        self.settings = settings or load_settings(run_overrides)
        self.on_event = on_event
        self.started_at = time.time()
        stem = Path(self.image_path).stem
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.run_dir = Path(run_dir) if run_dir else (
            Path(self.settings.paths.runs_dir) / f"{stamp}_{stem}"
        )
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.client = LLMClient(
            self.settings.model,
            log_path=self.run_dir / "llm_calls.jsonl",
        )
        with Image.open(self.image_path) as im:
            width, height = im.size
        self.state = GeometricEvidenceState(
            image_path=self.image_path,
            image_size={"width": int(width), "height": int(height)},
        )
        self.ctx = VisualContextManager(self.run_dir, self.image_path)
        self.store = EvidenceStore(self.run_dir)
        self.geometry_agent = GeometryAgent(self.client, self.state, self.run_dir)
        self.tikz_agent = TikZAgent(self.client, self.state, self.run_dir)
        self.critic_agent = CriticAgent(self.client, self.state)

        self.counters = {"steps": 0, "tool_calls": 0}
        self.stop_reason = ""
        self.final_summary = ""
        self.final_status = ""
        self._nudges = 0
        self._step = 0

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def run(self) -> dict[str, Any]:
        messages = initial_messages(self.state)
        budget = self.settings.budget
        try:
            for step in range(1, int(budget.max_steps) + 1):
                self._step = step
                self.counters["steps"] = step
                stop = self._budget_stop()
                if stop:
                    self.stop_reason = stop
                    break
                self._refresh_accounting()
                self._emit({"event": "step", "step": step, "budget": self.state.remaining_budget})

                result = self.client.chat(
                    messages,
                    tools=SUPERVISOR_TOOLS,
                    tool_choice="auto",
                    tag="supervisor",
                    max_tokens=4096,
                )
                messages.append(message_to_dict(result.message))
                self._emit(
                    {
                        "event": "supervisor_reply",
                        "step": step,
                        "text": (result.text or "")[:800],
                        "tool_calls": [c.function.name for c in result.tool_calls],
                        "usage": result.usage,
                    }
                )

                if not result.tool_calls:
                    self._nudges += 1
                    if self._nudges > 2:
                        self.final_summary = (result.text or "").strip() or "Supervisor stopped without finish."
                        self.final_status = "partial" if self.state.best_version else "blocked"
                        self.stop_reason = "no_tool_call"
                        break
                    messages.append({"role": "user", "content": step_nudge(self.state)})
                    continue

                action_result = self._dispatch(messages, result.tool_calls)
                if action_result == "finish":
                    break
        finally:
            self._finalise()

        return self.result_payload()

    def result_payload(self) -> dict[str, Any]:
        best = self.state.get_version(self.state.best_version) if self.state.best_version else None
        latest = self.state.latest_version()
        usage = self.client.usage_summary()
        return {
            "run_dir": str(self.run_dir),
            "image_path": self.image_path,
            "status": self.final_status or ("success" if self.state.best_version else "partial"),
            "stop_reason": self.stop_reason,
            "summary": self.final_summary,
            "best_version": self.state.best_version,
            "best_score": self.state.best_score,
            "best_tex_path": best.tex_path if best else None,
            "best_png_path": best.png_path if best else None,
            "best_tex": best.tex if best else (latest.tex if latest else None),
            "latest_version": latest.version if latest else None,
            "counts": {
                "steps": self.counters["steps"],
                "tool_calls": self.counters["tool_calls"],
                "objects": len(self.state.objects),
                "relations": len(self.state.relations),
                "tikz_versions": len(self.state.tikz_versions),
                "compilations": len(self.state.compilation_results),
                "critic_reports": len(self.state.critic_reports),
                "conflicts": len(self.state.conflicts),
                "unresolved": len(self.state.unresolved_issues),
            },
            "usage": {
                "totals": usage["totals"],
                "by_agent": usage["by_agent"],
            },
            "elapsed_s": round(time.time() - self.started_at, 2),
            "state_path": str(self.run_dir / "state.json"),
        }

    # ------------------------------------------------------------------ #
    # dispatch
    # ------------------------------------------------------------------ #
    def _dispatch(self, messages: list[dict[str, Any]], tool_calls: list[Any]) -> str | None:
        # Protocol: every tool call in the assistant message needs a tool reply.
        first = tool_calls[0]
        extras = tool_calls[1:]
        name = first.function.name
        args, err = parse_tool_arguments(first)
        started = time.perf_counter()
        tokens_before = int(self.client.usage_summary()["totals"]["total_tokens"])
        visuals_before = int(self.client.usage_summary()["totals"]["visual_calls"])

        status = "ok"
        error: str | None = None
        summary = ""
        purpose = ""
        params: dict[str, Any] = {}

        try:
            if name not in SUPERVISOR_NAMES and name != "call_cv_tool":
                payload = {"ok": False, "error": f"unknown action {name}"}
                status, error = "error", payload["error"]
            elif err:
                payload = {"ok": False, "error": err}
                status, error = "error", err
            elif name == "call_cv_tool":
                params = {"tool_name": args.get("tool_name"), "params": args.get("params") or {}}
                purpose = str(args.get("purpose", ""))
                self.counters["tool_calls"] += 1
                payload = self._do_cv_tool(params["tool_name"], params["params"], purpose)
            elif name == "inspect_image":
                params = {"region": args.get("region"), "question": args.get("question", "")}
                purpose = str(args.get("question", "inspect image"))[:200]
                payload = self._do_inspect_image(args, messages)
            elif name == "run_geometry_agent":
                purpose = str(args.get("instruction", "consolidate geometry"))[:200]
                params = {"instruction": args.get("instruction"), "use_image": args.get("use_image"), "roi": args.get("roi")}
                self.counters["tool_calls"] += 1
                payload = self._do_geometry_agent(args)
            elif name == "run_tikz_agent":
                purpose = str(args.get("instruction", "write tikz"))[:200]
                params = {"mode": args.get("mode"), "use_image": args.get("use_image"), "instruction": args.get("instruction")}
                self.counters["tool_calls"] += 1
                payload = self._do_tikz_agent(args)
            elif name == "run_critic":
                purpose = str(args.get("focus", "critique render"))[:200]
                params = {"focus": args.get("focus")}
                self.counters["tool_calls"] += 1
                payload = self._do_critic(args)
            elif name == "finish":
                params = {"summary": args.get("summary"), "unresolved": args.get("unresolved"), "status": args.get("status")}
                purpose = "finish run"
                payload = self._do_finish(args)
            else:  # pragma: no cover
                payload = {"ok": False, "error": "unhandled action"}
                status, error = "error", str(payload["error"])
        except Exception as exc:  # keep the loop alive; record the real failure
            payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            status, error = "error", payload["error"]

        duration = round(time.perf_counter() - started, 2)
        tokens_after = int(self.client.usage_summary()["totals"]["total_tokens"])
        visuals_after = int(self.client.usage_summary()["totals"]["visual_calls"])
        summary = _summarise_payload(payload)
        if isinstance(payload, dict) and payload.get("ok") is False:
            status = "error"

        self.state.record_action(
            ActionRecord(
                step=self._step,
                action=name if name != "call_cv_tool" else f"call_cv_tool:{params.get('tool_name')}",
                purpose=purpose,
                params=params,
                status=str(payload.get("ok", False) and "ok" or status),
                result_summary=summary,
                duration_s=duration,
                token_usage={"delta": tokens_after - tokens_before},
                visual_calls=visuals_after - visuals_before,
                error=payload.get("error") if isinstance(payload, dict) else None,
            )
        )
        if isinstance(payload, dict) and not payload.get("ok", False) and name != "finish":
            error = payload.get("error", "")

        messages.append(tool_reply(first.id, name, payload, limit=8000))
        for extra in extras:
            messages.append(
                tool_reply(extra.id, extra.function.name, {"ok": False, "error": "ignored: one action per step"})
            )
        self._checkpoint()
        self._emit(
            {
                "event": "action",
                "step": self._step,
                "action": name,
                "purpose": purpose,
                "ok": bool(payload.get("ok", False)) if isinstance(payload, dict) else None,
                "summary": summary,
                "duration_s": duration,
                "visual_calls": visuals_after - visuals_before,
                "error": error,
            }
        )
        return "finish" if name == "finish" else None

    # ------------------------------------------------------------------ #
    # individual actions
    # ------------------------------------------------------------------ #
    def _do_cv_tool(self, tool_name: str, params: dict[str, Any], purpose: str) -> dict[str, Any]:
        params = {k: v for k, v in (params or {}).items() if k not in ("image_path", "out_dir")}
        result = call_cv_tool(tool_name, params, image_path=self.image_path, out_dir=self.run_dir / "cv")
        result["purpose"] = purpose
        ingest_cv_result(self.state, tool_name, params, result)
        return compact_cv_result(result, tool_name)

    def _do_inspect_image(self, args: dict[str, Any], messages: list[dict[str, Any]]) -> dict[str, Any]:
        if self._visual_left() <= 0:
            return {"ok": False, "error": "visual-call budget exhausted"}
        question = str(args.get("question", "Describe the figure."))
        region = args.get("region")
        if region:
            record = self.ctx.crop(region, purpose=question[:80])
            image = record.path
            info = {"region_id": record.region_id, "box_px": record.box_px, "box_norm": record.box_norm}
        else:
            image = self.ctx.original()
            info = {"region_id": "original"}
        # Images cannot travel inside tool messages; attach them as a user turn.
        messages.append(
            {
                "role": "user",
                "content": self.client.build_content(
                    f"[inspect_image result] {info} Question: {question}\n"
                    "Answer internally, then choose your next action.",
                    [image],
                ),
            }
        )
        return {"ok": True, **info, "note": "image attached in the next user message"}

    def _do_geometry_agent(self, args: dict[str, Any]) -> dict[str, Any]:
        instruction = str(args.get("instruction", "Consolidate all CV evidence."))
        use_image = bool(args.get("use_image"))
        image = None
        if use_image and self._visual_left() > 0:
            roi = args.get("roi")
            image = self.ctx.crop(roi, purpose="geometry agent").path if roi else self.ctx.original()
        result = self.geometry_agent.run(
            instruction,
            cv_calls_left=max(0, self.settings.budget.max_tool_calls - self.counters["tool_calls"]),
            image_path=image,
        )
        self.counters["tool_calls"] += int(result.get("cv_calls", 0))
        return result

    def _do_tikz_agent(self, args: dict[str, Any]) -> dict[str, Any]:
        mode = str(args.get("mode", "generate"))
        instruction = str(args.get("instruction", "Write the TikZ figure."))
        image = None
        if mode == "generate" and bool(args.get("use_image")) and self._visual_left() > 0:
            image = self.ctx.original()
        result = self.tikz_agent.run(mode, instruction, image_path=image)
        if not result.get("ok") or not result.get("tex"):
            return {"ok": False, "error": result.get("error", "TikZ agent produced no source")}

        version = self.state.add_tikz_version(
            result["tex"], agent="tikz_agent", mode=mode, notes=result.get("notes", "")
        )
        compile_info = self._compile_version(version.version)
        self.state.add_evidence(
            source="tikz_agent",
            method=f"tikz {mode}",
            summary=f"v{version.version} compiled={compile_info['compile_ok']} "
            f"validation={compile_info['validation_passed']}",
            payload={"notes": result.get("notes", ""), "compile": compile_info},
        )
        return {
            "ok": bool(compile_info["compile_ok"]),
            "version": version.version,
            "latest_version": version.version,
            "mode": mode,
            "compile_ok": compile_info["compile_ok"],
            "validation_passed": compile_info["validation_passed"],
            "errors": compile_info["errors"][:4],
            "warnings": compile_info["warnings"][:2],
            "png_path": compile_info["png_path"],
            "best_version": self.state.best_version,
            "next_step_hint": (
                "run_critic on this new version to update best_version"
                if self.state.best_version != version.version
                else "critique passed version or repair remaining issues"
            ),
            "tex_preview": result["tex"][:600],
            "notes": result.get("notes", "")[:400],
        }

    def _compile_version(self, version_number: int) -> dict[str, Any]:
        version = self.state.get_version(version_number)
        if version is None:
            return {"compile_ok": False, "validation_passed": False, "errors": ["unknown version"], "warnings": [], "png_path": None}
        out = self.run_dir / "tikz" / f"v{version_number}"
        compiled = compile_tikz(
            version.tex,
            out_dir=out,
            stem=f"v{version_number}",
            timeout=float(self.settings.budget.compile_timeout_seconds),
            paths=self.settings.paths,
        )
        png_path = None
        if compiled.get("pdf_path"):
            render = render_pdf(compiled["pdf_path"], out / f"v{version_number}.png", dpi=200)
            png_path = render.get("png_path")
        combined = {**compiled, "png_path": png_path}
        validation = validate_compilation(
            version.tex,
            combined,
            version=version_number,
            reference_size=(self.state.image_size["width"], self.state.image_size["height"]),
        )
        self.state.mark_compilation(
            version_number,
            ok=bool(compiled.get("ok")),
            tex_path=compiled.get("tex_path"),
            pdf_path=compiled.get("pdf_path"),
            png_path=png_path,
            errors=compiled.get("errors", []),
            warnings=compiled.get("warnings", []),
            seconds=compiled.get("seconds"),
            log_tail=compiled.get("log_tail", ""),
            returncode=compiled.get("returncode"),
        )
        self.state.validation_results.append(validation)
        self.state.update_best(allow_unscored=True)
        return {
            "compile_ok": bool(compiled.get("ok")),
            "validation_passed": validation.passed,
            "errors": compiled.get("errors", []),
            "warnings": compiled.get("warnings", []),
            "png_path": png_path,
            "pdf_path": compiled.get("pdf_path"),
            "checks": [
                {"name": check.name, "passed": check.passed, "detail": check.detail}
                for check in validation.checks
            ],
        }

    def _do_critic(self, args: dict[str, Any]) -> dict[str, Any]:
        if self._visual_left() <= 0:
            return {"ok": False, "error": "visual-call budget exhausted"}
        target = None
        for version in reversed(self.state.tikz_versions):
            if version.ok and version.png_path and version.png_path.endswith(".png"):
                target = version
                break
        if target is None:
            return {"ok": False, "error": "no successfully rendered TikZ version to critique"}
        report = self.critic_agent.run(
            self.ctx.original(),
            target.png_path,
            focus=str(args.get("focus", "")),
            version=target.version,
        )
        score = float(report.get("assessment_score", 0.0))
        self.state.attach_critic(target.version, report, score)
        self.state.update_best(allow_unscored=True)
        return {
            "ok": True,
            "version": target.version,
            "assessment_score": score,
            "verdict": report.get("verdict"),
            "issues": report.get("issues", [])[:8],
            "labels": report.get("labels"),
            "best_version": self.state.best_version,
        }

    def _do_finish(self, args: dict[str, Any]) -> dict[str, Any]:
        args = _clean_finish_args(args)
        self.final_summary = str(args.get("summary", ""))[:2000]
        status = str(args.get("status") or "")
        if status not in ("success", "partial", "blocked"):
            status = "success" if self.state.best_version else "blocked"
        self.final_status = status
        for issue in _issue_list(args.get("unresolved")):
            self.state.add_unresolved({"source": "supervisor", "issue": issue})
        self.stop_reason = "finish"
        self.state.meta["finish"] = {"summary": self.final_summary, "status": status}
        return {
            "ok": True,
            "best_version": self.state.best_version,
            "best_score": self.state.best_score,
            "status": status,
        }

    # ------------------------------------------------------------------ #
    # budget / persistence
    # ------------------------------------------------------------------ #
    def _visual_left(self) -> int:
        used = int(self.client.usage_summary()["totals"].get("visual_calls", 0))
        return int(self.settings.budget.max_visual_calls) - used

    def _budget_stop(self) -> str | None:
        if time.time() - self.started_at > self.settings.budget.timeout_seconds:
            return "timeout"
        usage = self.client.usage_summary()["totals"]
        if int(usage.get("total_tokens", 0)) >= int(self.settings.budget.max_total_tokens):
            return "token_budget"
        if self.counters["tool_calls"] >= int(self.settings.budget.max_tool_calls) and self.state.best_version:
            return "tool_budget"
        return None

    def _refresh_accounting(self) -> None:
        usage = self.client.usage_summary()
        self.state.update_accounting(
            {"totals": usage["totals"], "by_agent": usage["by_agent"]},
            self.settings.budget.to_dict(),
            {
                "steps": self.counters["steps"],
                "tool_calls": self.counters["tool_calls"],
                "visual_calls": int(usage["totals"].get("visual_calls", 0)),
            },
        )

    def _checkpoint(self) -> None:
        self._refresh_accounting()
        try:
            self.store.checkpoint(self.state, self._step)
            self.store.save(self.state, tag="state")
        except Exception as exc:  # checkpointing must not kill the run
            self._emit({"event": "checkpoint_error", "error": f"{type(exc).__name__}: {exc}"})

    def _finalise(self) -> None:
        self._refresh_accounting()
        if not self.final_status:
            self.final_status = "success" if self.state.best_version else "partial"
        if not self.final_summary:
            self.final_summary = self._auto_summary()
        self.state.meta["stop_reason"] = self.stop_reason or "max_steps"
        self._checkpoint()
        try:
            self.store.save_trace(self.state)
            self.store.save_result(self.result_payload())
        except Exception:
            pass
        self._emit({"event": "done", "result": self.result_payload()})

    def _auto_summary(self) -> str:
        best = self.state.best_version
        parts = [f"stopped: {self.stop_reason or 'max_steps'}"]
        parts.append(f"best_version={best}" if best else "no compiled TikZ produced")
        if self.state.best_score is not None:
            parts.append(f"critic_score={self.state.best_score}")
        if self.state.compilation_results:
            last = self.state.compilation_results[-1]
            parts.append(f"last_compile_ok={last.ok}")
            if last.errors:
                parts.append(f"first_error={last.errors[0][:200]}")
        return "; ".join(parts)

    def _emit(self, event: dict[str, Any]) -> None:
        event.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
        try:
            self.store.append_event(event)
        except Exception:
            pass
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception:
                pass


_XML_PARAM = re.compile(r'<parameter\s+name="(?P<name>\w+)">(?P<value>.*?)</parameter>', re.S)
_XML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")


def _clean_finish_args(args: dict[str, Any]) -> dict[str, Any]:
    """Tolerate providers that serialise tool arguments with XML-ish markup.

    Some OpenAI-compatible gateways occasionally return finish arguments such as
    ``summary="... </summary><parameter name="unresolved">[...]"``. Recover the
    embedded parameters and strip the leaked tags so the report stays readable.
    """
    cleaned = dict(args)
    raw_summary = str(cleaned.get("summary") or "")
    for match in _XML_PARAM.finditer(raw_summary):
        name, value = match.group("name"), match.group("value").strip()
        if name in ("unresolved", "status") and name not in cleaned:
            cleaned[name] = value
    for marker in ("</summary>", "</invoke>", "<parameter"):
        if marker in raw_summary:
            raw_summary = raw_summary.split(marker, 1)[0]
    cleaned["summary"] = _XML_TAG.sub("", raw_summary).strip()
    status = str(cleaned.get("status") or "")
    cleaned["status"] = _XML_TAG.sub("", status).strip()
    return cleaned


def _issue_list(value: Any) -> list[str]:
    """Normalise an unresolved field that may be a list, JSON string, or prose."""
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return [value[:400]]
    if isinstance(value, dict):
        return [json.dumps(value, ensure_ascii=False)[:400]]
    if isinstance(value, (list, tuple)):
        return [str(item)[:400] for item in value][:12]
    return [str(value)[:400]]


def _summarise_payload(payload: Any) -> str:
    if not isinstance(payload, dict):
        return str(payload)[:300]
    keys = ("ok", "count", "version", "compile_ok", "validation_passed", "best_version", "assessment_score", "merged", "error", "status")
    parts = [f"{key}={payload[key]}" for key in keys if key in payload and payload[key] is not None]
    if not parts:
        parts = [f"keys={list(payload)[:8]}"]
    text = "; ".join(parts)
    if payload.get("issues"):
        text += f"; issues={len(payload['issues'])}"
    if payload.get("errors"):
        text += f"; errors={len(payload['errors'])}"
    return text[:500]
