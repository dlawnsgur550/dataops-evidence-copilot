"""Accessible local UI graphics; figures only use report/evaluation values."""
from html import escape
from pathlib import Path

import streamlit as st

from .ui_workspace import TASKS, TASK_LABELS, rule_counts

COLORS = {"success": "#147d64", "failed": "#bf4444", "upstream_failed": "#a36919",
          "unknown": "#68778a", "PASS": "#147d64", "REJECT": "#bf4444", "HOLD": "#a36919"}
STATE_NAMES = {"success": "성공", "failed": "실패", "upstream_failed": "선행 실패",
               "skipped": "건너뜀", "running": "실행 중", "unknown": "미수집"}


def setup():
    st.html((Path(__file__).parent / "ui_assets/workspace.css").read_text())


def header(eyebrow, title, description):
    st.html(f'<div class="page-heading"><div class="eyebrow">{escape(eyebrow)}</div>'
            f'<h1>{escape(title)}</h1><p>{escape(description)}</p></div>')


def stats(items):
    cells = "".join(f'<div class="stat"><div class="stat-label">{escape(str(label))}</div>'
                    f'<div class="stat-value">{escape(str(value))}</div>'
                    f'<div class="stat-note">{escape(str(note))}</div></div>' for label, value, note in items)
    st.html('<div class="stat-grid">' + cells + '</div>')


def panel_title(title, note=""):
    st.html(f'<div class="section-heading"><h3>{escape(title)}</h3>'
            f'<span>{escape(note)}</span></div>')


def pipeline(states, title="선택 실행의 파이프라인"):
    if not states:
        st.info("태스크 상태를 확인할 수 있는 실행 근거가 없습니다.")
        return
    parts = []
    for i, task in enumerate(TASKS):
        x = 20 + i * 222
        state = states.get(task, "unknown")
        color = COLORS.get(state, "#68778a")
        label = STATE_NAMES.get(state, state)
        if i < 3:
            parts.append(f'<path d="M{x+184} 60 H{x+216}" stroke="#cdd8e2" stroke-width="2"/>'
                         f'<path d="M{x+210} 55 L{x+216} 60 L{x+210} 65" fill="none" stroke="#a3b1c1" stroke-width="2"/>')
        symbol = "✓" if state == "success" else "×" if state == "failed" else "Ⅱ" if state == "upstream_failed" else "?"
        parts.append(f'<rect x="{x}" y="16" width="184" height="90" rx="12" fill="white" stroke="#dce4ed"/>'
                     f'<circle cx="{x+26}" cy="43" r="12" fill="{color}"/>'
                     f'<text x="{x+26}" y="48" text-anchor="middle" fill="white" font-size="16">{symbol}</text>'
                     f'<text x="{x+47}" y="48" fill="#20344d" font-size="15" font-weight="650">{escape(TASK_LABELS[task])}</text>'
                     f'<text x="{x+17}" y="77" fill="{color}" font-size="13" font-weight="600">{escape(label)}</text>'
                     f'<text x="{x+167}" y="78" text-anchor="end" fill="#5f7085" font-size="10">{escape(task)}</text>')
    text = ", ".join(f"{TASK_LABELS[t]} {STATE_NAMES.get(states.get(t, 'unknown'), states.get(t, 'unknown'))}" for t in TASKS)
    svg = ('<svg viewBox="0 0 890 122" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="'
           + escape(text, quote=True) + '"><title>' + escape(title) + '</title><desc>'
           + escape(text) + '</desc>' + ''.join(parts) + '</svg>')
    st.image(svg, width="stretch", caption=text, alt=title + ": " + text)


def rules_chart(checks, key):
    counts = rule_counts(checks)
    rows = [{"판정": {"PASS": "통과", "REJECT": "차단", "HOLD": "보류"}[k], "검사 수": v,
             "색": COLORS[k]} for k, v in counts.items()]
    chart(rows, "판정", "검사 수", key, height=135, colors=["#147d64", "#bf4444", "#a36919"],
          order=["통과", "차단", "보류"], description="선택 보고서의 구성요소별 규칙 판정 횟수. 모델 정확도를 뜻하지 않습니다.")


def chart(rows, category, value, key, *, height=195, colors=None, order=None,
          number_format=",.0f", description="", x_title=None):
    colors = colors or ["#167e88", "#7994b3", "#b6c7d9"]
    spec = {"description": description, "height": height, "background": "transparent",
            "data": {"values": rows}, "layer": [
                {"mark": {"type": "bar", "cornerRadiusEnd": 5, "height": 26},
                 "encoding": {"color": {"field": category, "type": "nominal", "legend": None,
                                          "scale": {"domain": order or list(dict.fromkeys(r[category] for r in rows)), "range": colors}}}},
                {"mark": {"type": "text", "align": "left", "dx": 8, "fontSize": 12, "color": "#30465e"},
                 "encoding": {"text": {"field": value, "type": "quantitative", "format": number_format}}}],
            "encoding": {"y": {"field": category, "type": "nominal", "sort": order,
                                "axis": {"title": None, "labelLimit": 160, "labelPadding": 12}},
                         "x": {"field": value, "type": "quantitative", "scale": {"zero": True, "nice": True},
                                "axis": {"title": x_title, "tickCount": 4, "format": number_format}},
                         "tooltip": [{"field": category, "type": "nominal"},
                                     {"field": value, "type": "quantitative", "format": number_format}]},
            "config": {"view": {"stroke": None}, "axis": {"domain": False, "tickColor": "#dce4ed",
                          "gridColor": "#edf1f5", "labelColor": "#5f7085", "titleColor": "#5f7085",
                          "labelFont": "sans-serif", "titleFont": "sans-serif", "labelFontSize": 12}}}
    st.vega_lite_chart(spec, width="stretch", theme=None, key=key)


def evidence_chart(report):
    from collections import Counter
    counts = Counter("선택 실행 당시" if e.temporal_scope == "run_snapshot" else "별도 시점 관측" for e in report.evidence)
    rows = [{"근거 범위": k, "자료 수": counts[k]} for k in ["선택 실행 당시", "별도 시점 관측"]]
    chart(rows, "근거 범위", "자료 수", "evidence_scope", height=140,
          description="수집 근거를 선택 실행 당시 기록과 별도 시점 관측으로 구분한 자료 수")


def timeline(events):
    cells = ''.join(f'<div class="timeline-event"><div class="timeline-dot"></div><span>{escape(label)}</span>'
                    f'<strong>{escape(when)}</strong><small>{escape(note)}</small></div>'
                    for label, when, note in events)
    st.html('<div class="timeline" role="list">' + cells + '</div>')
