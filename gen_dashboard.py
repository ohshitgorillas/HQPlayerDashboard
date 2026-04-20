#!/usr/bin/env python3
"""Generate HQPlayer performance Grafana dashboard JSON."""
import json

# ── CONFIG — edit these before generating ────────────────────────────────────
INSTANCE       = "opal"          # Prometheus instance label for this host
DASHBOARD_TITLE = f"{INSTANCE} — HQPlayer Performance"
DASHBOARD_UID  = f"{INSTANCE}-hqp-perf"
DASHBOARD_TAGS = ["hqplayer", INSTANCE, "pcm", "audio"]
# ─────────────────────────────────────────────────────────────────────────────

DS   = {"type": "prometheus", "uid": "${datasource}"}
INST = f'instance="{INSTANCE}"'
PCM_RATE  = "[2m]"   # irate window for PCM counters (10s scrape)
NODE_RATE = "[2m]"   # irate window for node_exporter counters


def tgt(expr, legend="", ref_id=None, instant=False):
    t = {"datasource": DS, "expr": expr,
         "legendFormat": legend, "refId": ref_id or "A", "interval": ""}
    if instant:
        t["instant"] = True
        t["range"] = False
    return t


def tgts(*pairs):
    return [tgt(e, l, chr(65 + i)) for i, (e, l) in enumerate(pairs)]


def th(*steps, mode="absolute"):
    return {"mode": mode,
            "steps": [{"color": c, "value": v} for v, c in steps]}


def stat(pid, title, expr, gp, unit="short", legend="", mappings=None,
         thresholds=None, color_mode="background", graph_mode="none",
         text_mode="auto", instant=False, no_value=None, overrides=None,
         orientation="auto"):
    defaults = {
        "unit": unit,
        "thresholds": thresholds or th((None, "green")),
    }
    if no_value is not None:
        defaults["noValue"] = no_value
    p = {
        "id": pid, "type": "stat", "title": title, "gridPos": gp,
        "datasource": DS,
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "orientation": orientation, "textMode": text_mode,
            "colorMode": color_mode, "graphMode": graph_mode,
            "justifyMode": "auto",
        },
        "fieldConfig": {
            "defaults": defaults,
            "overrides": overrides or [],
        },
        "targets": [tgt(expr, legend, instant=instant)],
    }
    if mappings:
        p["fieldConfig"]["defaults"]["mappings"] = mappings
    return p


def text_panel(pid, title, content, gp):
    return {
        "id": pid, "type": "text", "title": title, "gridPos": gp,
        "options": {"mode": "markdown", "content": content},
    }


def gauge(pid, title, expr, gp, unit="short", min_=0, max_=100, legend="",
          thresholds=None):
    return {
        "id": pid, "type": "gauge", "title": title, "gridPos": gp,
        "datasource": DS,
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "orientation": "auto",
            "showThresholdLabels": False,
            "showThresholdMarkers": True,
        },
        "fieldConfig": {
            "defaults": {
                "unit": unit, "min": min_, "max": max_,
                "color": {"mode": "thresholds"},
                "thresholds": thresholds or th((None, "green")),
            },
            "overrides": [],
        },
        "targets": [tgt(expr, legend)],
    }


def ts(pid, title, targets_, gp, unit="short", stack=None, fill=10, line=1,
       decimals=None, thresholds=None, min_=None, max_=None, overrides=None,
       show_points="never", span_nulls=True):
    custom = {"lineWidth": line, "fillOpacity": fill,
              "spanNulls": span_nulls, "gradientMode": "none",
              "showPoints": show_points}
    if stack:
        custom["stacking"] = {"group": "A", "mode": stack}
    defaults = {"unit": unit, "custom": custom}
    if min_ is not None:
        defaults["min"] = min_
    if max_ is not None:
        defaults["max"] = max_
    if decimals is not None:
        defaults["decimals"] = decimals
    if thresholds:
        defaults["thresholds"] = thresholds
    return {
        "id": pid, "type": "timeseries", "title": title, "gridPos": gp,
        "datasource": DS,
        "options": {
            "tooltip": {"mode": "multi", "sort": "desc"},
            "legend": {"displayMode": "list", "placement": "bottom",
                       "showLegend": True},
        },
        "fieldConfig": {
            "defaults": defaults,
            "overrides": overrides or [],
        },
        "targets": targets_,
    }


def rowp(pid, title, y):
    return {
        "id": pid, "type": "row", "title": title,
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
        "collapsed": False, "panels": [],
    }


def gp(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


panels = []
pid = 1

# Row heights / Y layout
# HQP:          y=0 (row), panels y=1..5  (h=5)
# Memory:       y=6 (row), panels y=7..14 (h=8 main, h=4 small)
# CPU:          y=15 (row), panels y=16..23 (h=8)
# GPU:          y=24 (row), panels y=25..32 (h=8)
# System:       y=33 (row), panels y=34..39 (h=6)
# Network:      y=40 (row), panels y=41..46 (h=6)

# ── Row 1: HQPlayer Status ────────────────────────────────────────────────────
panels.append(rowp(pid, "HQPlayer Status", 0)); pid += 1

# Track / State — instant query; no_value shown when stopped or paused
panels.append(stat(
    pid, "Now Playing",
    "hqplayer_track_info",
    gp(0, 1, 8, 5),
    legend="{{artist}} — {{song}}  ·  {{album}} ({{date}})",
    text_mode="name", color_mode="none",
    thresholds=th((None, "green")),
    instant=True, no_value="STOPPED / PAUSED",
)); pid += 1

panels.append(gauge(
    pid, "Process Speed  (×realtime)", "hqplayer_process_speed",
    gp(18, 1, 3, 5), unit="short", min_=0, max_=5, legend="speed",
    thresholds=th((None, "red"), (1.3, "orange"), (2.5, "yellow"), (4.0, "green")),
)); pid += 1

# Output format — bit depth and rate from hqplayer_info label
panels.append(stat(
    pid, "Output", "hqplayer_info",
    gp(10, 1, 2, 5), legend="{{output_fmt}}",
    text_mode="name", color_mode="none", instant=True,
)); pid += 1

# Source format (PCM 24/44.1, DSD256, etc.) — from track metadata
panels.append(stat(
    pid, "Source", "hqplayer_track_info",
    gp(8, 1, 2, 5), legend="{{source_fmt}}",
    text_mode="name", color_mode="none", instant=True, no_value="—",
)); pid += 1

# Mode / Filter / Shaper — instant query returns only the active label set
panels.append(stat(
    pid, "Format · Filter · Shaper", "hqplayer_info",
    gp(12, 1, 4, 5), legend="{{mode}} · {{filter}} · {{shaper}}",
    text_mode="name", color_mode="none", instant=True,
)); pid += 1

panels.append(gauge(
    pid, "Output Buffer Fill", "hqplayer_output_fill_ratio * 100",
    gp(21, 1, 3, 5), unit="percent", min_=0, max_=100,
    thresholds=th((None, "red"), (85, "orange"), (90, "yellow"), (95, "green")),
)); pid += 1

panels.append(stat(
    pid, "Volume", "hqplayer_volume_db",
    gp(16, 1, 2, 5), unit="dB", color_mode="none",
)); pid += 1

# ── Row 2: CPU ────────────────────────────────────────────────────────────────
panels.append(rowp(pid, "CPU", 6)); pid += 1

# Layout: [Freq w=7] [Temps w=7] [Heatmap w=7] [Busiest w=3 vertical] = 24
freq_expr = f'avg_over_time(node_cpu_scaling_frequency_hertz{{{INST}}}[30s])'
freq_max  = f'max(node_cpu_frequency_max_hertz{{{INST}}})'
panels.append(ts(
    pid, "Per-Core Actual Frequency",
    tgts((freq_expr, "cpu{{cpu}}"), (freq_max, "max turbo")),
    gp(0, 7, 7, 8), unit="hertz", fill=0, min_=0, show_points="never",
    overrides=[
        {"matcher": {"id": "byFrameRefID", "options": "B"},
         "properties": [
             {"id": "custom.lineStyle", "value": {"fill": "dash"}},
             {"id": "custom.lineWidth", "value": 2},
             {"id": "custom.fillOpacity", "value": 0},
             {"id": "color", "value": {"mode": "fixed", "fixedColor": "rgba(200,200,200,0.5)"}},
         ]},
    ],
)); pid += 1

panels.append(ts(
    pid, "CPU Temperatures",
    tgts(
        (f'max(node_hwmon_temp_celsius{{{INST},chip="platform_coretemp_0"}})', "max"),
        (f'avg(node_hwmon_temp_celsius{{{INST},chip="platform_coretemp_0"}})', "avg"),
    ),
    gp(7, 7, 7, 8), unit="celsius", fill=5, min_=20, show_points="never",
)); pid += 1

# Per-core utilization heatmap — calculate:false: each series = one Y row.
# fieldConfig min/max=0/1 locks the color scale so idle (0%) stays green,
# only truly pegged cores (100%) go red. options.color.min/max alone are advisory.
util_expr = f'1 - rate(node_cpu_seconds_total{{{INST},mode="idle"}}[30s])'
panels.append({
    "id": pid, "type": "heatmap",
    "title": "Per-Core Utilization",
    "gridPos": gp(14, 7, 7, 8),
    "datasource": DS,
    "options": {
        "calculate": False,
        "cellGap": 1,
        "color": {
            "scheme": "RdYlGn",
            "reverse": False,
            "min": 0,
            "max": 1,
            "mode": "scheme",
            "scale": "linear",
            "steps": 64,
        },
        "filterValues": {"le": 1e-9},
        "legend": {"show": False},
        "rowsFrame": {"layout": "auto"},
        "tooltip": {"mode": "single", "showColorScale": False},
        "yAxis": {"axisLabel": "CPU", "reverse": False, "unit": "short"},
    },
    "fieldConfig": {
        "defaults": {
            "min": 0,
            "max": 1,
            "custom": {
                "hideFrom": {"legend": False, "tooltip": False, "viz": False},
                "scaleDistribution": {"type": "linear"},
            },
        },
        "overrides": [],
    },
    "targets": [tgt(util_expr, "{{cpu}}")],
}); pid += 1

# Busiest two cores — bargauge horizontal = one bar per CPU stacked top-to-bottom
topk2_expr = f'topk(2, 1 - irate(node_cpu_seconds_total{{{INST},mode="idle"}}[30s]))'
panels.append({
    "id": pid, "type": "bargauge",
    "title": "Busiest",
    "gridPos": gp(21, 7, 3, 8),
    "datasource": DS,
    "options": {
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        "orientation": "horizontal",
        "displayMode": "basic",
        "showUnfilled": True,
        "minVizWidth": 0,
        "minVizHeight": 10,
    },
    "fieldConfig": {
        "defaults": {
            "unit": "percentunit",
            "min": 0, "max": 1,
            "thresholds": th((None, "green"), (0.5, "yellow"), (0.85, "red")),
            "color": {"mode": "thresholds"},
        },
        "overrides": [],
    },
    "targets": [tgt(topk2_expr, "cpu{{cpu}}", instant=True)],
}); pid += 1

# ── Row 3: GPU ────────────────────────────────────────────────────────────────
panels.append(rowp(pid, "GPU — RTX 3060 Ti", 15)); pid += 1

panels.append(ts(
    pid, "SM & Memory Controller Utilization",
    tgts(("DCGM_FI_DEV_GPU_UTIL", "SM Util %"),
         ("DCGM_FI_DEV_MEM_COPY_UTIL", "Mem Ctrl Util %")),
    gp(0, 16, 12, 8), unit="percent", fill=10, min_=0, max_=100,
    show_points="never",
)); pid += 1

panels.append(gauge(
    pid, "VRAM Used",
    "DCGM_FI_DEV_FB_USED",
    gp(12, 16, 4, 4), unit="decmbytes", min_=0, max_=8192,
    thresholds=th((None, "green"), (6000, "orange"), (7500, "red")),
)); pid += 1

panels.append(ts(
    pid, "VRAM Over Time",
    tgts(("DCGM_FI_DEV_FB_USED", "VRAM MiB")),
    gp(12, 20, 4, 4), unit="decmbytes", fill=10, min_=0, max_=8192,
    show_points="never",
)); pid += 1

panels.append(ts(
    pid, "GPU Temp & Power",
    tgts(("DCGM_FI_DEV_GPU_TEMP", "Temp °C"),
         ("DCGM_FI_DEV_POWER_USAGE", "Power W")),
    gp(16, 16, 8, 4), unit="short", fill=5, min_=0, show_points="never",
)); pid += 1

panels.append(ts(
    pid, "SM Clock & Mem Clock",
    tgts(("DCGM_FI_DEV_SM_CLOCK * 1e6", "SM Clock"),
         ("DCGM_FI_DEV_MEM_CLOCK * 1e6", "Mem Clock")),
    gp(16, 20, 8, 4), unit="hertz", fill=0, min_=0, show_points="never",
    overrides=[
        {"matcher": {"id": "byName", "options": "Mem Clock"},
         "properties": [
             {"id": "custom.axisPlacement", "value": "right"},
             {"id": "color", "value": {"mode": "fixed", "fixedColor": "purple"}},
         ]},
        {"matcher": {"id": "byName", "options": "SM Clock"},
         "properties": [
             {"id": "color", "value": {"mode": "fixed", "fixedColor": "yellow"}},
         ]},
    ],
)); pid += 1

# ── Row 4: Memory ─────────────────────────────────────────────────────────────
panels.append(rowp(pid, "Memory", 24)); pid += 1

dram_r = f'irate(DRAM_Reads{{aggregate="system",source="uncore"}}{PCM_RATE})'
dram_w = f'irate(DRAM_Writes{{aggregate="system",source="uncore"}}{PCM_RATE})'

panels.append(ts(
    pid, "DRAM Bandwidth (total socket)",
    tgts((dram_r, "Read"), (dram_w, "Write")),
    gp(0, 25, 12, 8), unit="Bps", stack="normal", fill=20, min_=0,
)); pid += 1

panels.append(gauge(
    pid, "BW % of DDR5-6400 Max  (102.4 GB/s)",
    f"({dram_r} + {dram_w}) / 102.4e9 * 100",
    gp(12, 25, 4, 4), unit="percent", min_=0, max_=100,
    thresholds=th((None, "green"), (50, "orange"), (75, "red")),
)); pid += 1

ipc = (f'sum(irate(Instructions_Retired_Any{{source="core"}}{PCM_RATE}))'
       f' / sum(irate(Clock_Unhalted_Thread{{source="core"}}{PCM_RATE}))')
panels.append(ts(
    pid, "IPC (socket aggregate)", tgts((ipc, "IPC")),
    gp(16, 25, 8, 4), unit="short", fill=5, decimals=2, min_=0,
)); pid += 1

l3miss = (f'sum(irate(L3_Cache_Misses{{source="core"}}{PCM_RATE}))'
          f' / (sum(irate(L3_Cache_Misses{{source="core"}}{PCM_RATE}))'
          f' + sum(irate(L3_Cache_Hits{{source="core"}}{PCM_RATE})))')
panels.append(ts(
    pid, "L3 Miss Rate", tgts((l3miss, "L3 Miss")),
    gp(12, 29, 6, 4), unit="percentunit", fill=5, min_=0, max_=1,
    thresholds=th((None, "green"), (0.1, "orange"), (0.25, "red")),
)); pid += 1

pkg_pwr = f'irate(Package_Joules_Consumed{{source="uncore"}}{PCM_RATE})'
panels.append(ts(
    pid, "Package Power", tgts((pkg_pwr, "CPU W")),
    gp(18, 29, 6, 4), unit="watt", fill=5, min_=0,
)); pid += 1

# ── Row 5: System Context ─────────────────────────────────────────────────────
panels.append(rowp(pid, "System Context", 33)); pid += 1

# Memory: stack Used+Cached+Buffers, Available as dashed line
ram_used = f'node_memory_MemTotal_bytes{{{INST}}} - node_memory_MemAvailable_bytes{{{INST}}}'
panels.append(ts(
    pid, "Memory Usage",
    tgts((ram_used, "Used"),
         (f'node_memory_Cached_bytes{{{INST}}}', "Cached"),
         (f'node_memory_Buffers_bytes{{{INST}}}', "Buffers"),
         (f'node_memory_MemAvailable_bytes{{{INST}}}', "Available")),
    gp(0, 34, 10, 6), unit="bytes", fill=15, stack="normal", min_=0,
    max_=34_359_738_368,  # 32 GB
    show_points="never",
    overrides=[
        {"matcher": {"id": "byName", "options": "Available"},
         "properties": [
             {"id": "custom.stacking", "value": {"group": "A", "mode": "none"}},
             {"id": "custom.fillOpacity", "value": 0},
             {"id": "custom.lineStyle", "value": {"fill": "dash"}},
         ]},
    ],
)); pid += 1

panels.append(ts(
    pid, "Context Switches / s",
    tgts((f'irate(node_context_switches_total{{{INST}}}{NODE_RATE})', "ctx/s")),
    gp(10, 34, 7, 6), unit="short", fill=5, min_=0, show_points="never",
)); pid += 1

panels.append(ts(
    pid, "CPU Softirqs / s",
    tgts((f'sum(irate(node_cpu_seconds_total{{{INST},mode="softirq"}}{NODE_RATE}))',
          "softirq/s")),
    gp(17, 34, 7, 6), unit="short", fill=5, min_=0, show_points="never",
)); pid += 1

# ── Row 6: Network ────────────────────────────────────────────────────────────
panels.append(rowp(pid, "Network", 40)); pid += 1

rx_bps = f'irate(node_network_receive_bytes_total{{{INST},device="enp129s0"}}{NODE_RATE}) * 8'
tx_bps = f'irate(node_network_transmit_bytes_total{{{INST},device="enp129s0"}}{NODE_RATE}) * 8'

panels.append(ts(
    pid, "NIC Throughput  (enp129s0)",
    tgts((tx_bps, "TX"), (rx_bps, "RX")),
    gp(0, 41, 24, 6), unit="bps", fill=10, show_points="never",
)); pid += 1


# ── Dashboard variables ───────────────────────────────────────────────────────
def label_var(name, label, lbl):
    """Hidden query variable — uses query_result so only current series appear."""
    return {
        "name": name, "label": label,
        "type": "query",
        "datasource": DS,
        "query": {"query": "query_result(hqplayer_info)",
                  "refId": "StandardVariableQuery"},
        "regex": f'/{lbl}="([^"]+)"/',
        "refresh": 2,
        "sort": 0,
        "hide": 2,
        "current": {}, "options": [], "includeAll": False, "multi": False,
    }


templating_vars = [
    {   # datasource picker — visible
        "current": {}, "hide": 0, "includeAll": False,
        "name": "datasource", "options": [], "query": "prometheus",
        "refresh": 1, "type": "datasource", "label": "Datasource",
    },
]

# ── Dashboard wrapper ─────────────────────────────────────────────────────────
dashboard = {
    "title": DASHBOARD_TITLE,
    "uid": DASHBOARD_UID,
    "schemaVersion": 39,
    "version": 4,
    "refresh": "5s",
    "time": {"from": "now-30m", "to": "now"},
    "timezone": "browser",
    "tags": DASHBOARD_TAGS,
    "editable": True,
    "graphTooltip": 1,
    "links": [],
    "panels": panels,
    "templating": {"list": templating_vars},
    "annotations": {
        "list": [{
            "builtIn": 1,
            "datasource": {"type": "grafana", "uid": "-- Grafana --"},
            "enable": True, "hide": True,
            "iconColor": "rgba(0, 211, 255, 1)",
            "name": "Annotations & Alerts", "type": "dashboard",
        }]
    },
}

print(json.dumps(dashboard, indent=2))
