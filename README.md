# hqp-exporter

Prometheus exporter for [HQPlayer Embedded](https://www.signalyst.com/embedded.html) (daemon), plus a Grafana dashboard generator for a complete audio server monitoring stack.

Developed and tested against HQPlayer Embedded 5.x. Compatibility with HQPlayer Desktop is unknown — the TCP control API may differ.

## What it does

`hqp_exporter.py` connects to HQPlayer's TCP control API (port 4321) and exposes playback state, DSP metrics, track metadata, and output format as Prometheus gauges. The companion dashboard generator (`gen_dashboard.py`) produces a Grafana dashboard JSON covering HQPlayer, CPU, GPU, memory, and system metrics.

<img alt="HQPlayer Dashboard" src="https://github.com/user-attachments/assets/24328e57-d0af-41d4-b415-f62eec2d9ecd" />


## Requirements

- HQPlayer Embedded (tested with 5.x on Ubuntu Server)
- Python 3.8+ with `prometheus_client` (`pip install prometheus-client`)
- Prometheus scraping this exporter
- Grafana for the dashboard

The full dashboard assumes these additional exporters are running on the audio server:

| Exporter | Default port | Purpose |
|---|---|---|
| [node_exporter](https://github.com/prometheus/node_exporter) | 9100 | CPU, memory, network, temps |
| [pcm-sensor-server](https://github.com/intel/pcm) | 9738 | Intel CPU power/frequency counters |
| [dcgm-exporter](https://github.com/NVIDIA/dcgm-exporter) | 9400 | NVIDIA GPU metrics |

You don't need all four — unused panels will simply show no data.

## Running the exporter

```bash
python3 hqp_exporter.py [--port 9744] [--interval 2.0]
```

HQPlayer must be running and accessible on `localhost:4321`.

### Systemd unit (recommended)

```ini
[Unit]
Description=HQPlayer Prometheus exporter
After=network.target

[Service]
ExecStart=/usr/bin/python3 /path/to/hqp_exporter.py
Restart=on-failure
User=nobody

[Install]
WantedBy=multi-user.target
```

Edit with the path to `hqp_exporter.py` on your system.

## Generating the dashboard

Edit the `CONFIG` block at the top of `gen_dashboard.py`:

```python
INSTANCE        = "opal"   # must match the instance label in your Prometheus scrape config
DASHBOARD_TITLE = f"{INSTANCE} — HQPlayer Performance"
DASHBOARD_UID   = f"{INSTANCE}-hqp-perf"
```

Then run:

```bash
python3 gen_dashboard.py > my-dashboard.json
```

Import the resulting JSON into Grafana via **Dashboards → Import**.

A pre-generated example (with `INSTANCE="opal"`) is provided as `hqp-dashboard.json.example`.

## Forking / adapting

The dashboard is tightly coupled to the hardware of the original system (Intel Arrow Lake CPU, NVIDIA RTX, DDR5). If your hardware differs:

- **Different CPU**: pcm-sensor-server metric names and `node_hwmon` chip names will vary. Update the relevant `ts()` panel calls in `gen_dashboard.py`.
- **No NVIDIA GPU**: Remove the GPU row panels.
- **Different RAM**: The memory row queries use standard `node_memory_*` metrics and should work as-is.
- **HQPlayer metrics**: `hqp_exporter.py` is hardware-agnostic — no changes needed.

## Metrics exposed

| Metric | Description |
|---|---|
| `hqplayer_up` | 1 if HQPlayer TCP reachable |
| `hqplayer_state` | 0=stopped, 1=paused, 2=playing |
| `hqplayer_active_rate_hz` | Output sample rate |
| `hqplayer_active_bits` | Output bit depth |
| `hqplayer_active_channels` | Output channel count |
| `hqplayer_process_speed` | DSP throughput multiplier vs realtime |
| `hqplayer_output_fill_ratio` | Output buffer fill (0.0–1.0) |
| `hqplayer_volume_db` | Volume level |
| `hqplayer_clips_total` | Digital clip count |
| `hqplayer_info` | Labels: version, mode, filter, shaper, source_is_dsd, output_fmt |
| `hqplayer_track_info` | Labels: artist, album, song, source_fmt, etc. (set only while playing) |
| `hqplayer_scrape_duration_seconds` | Poll round-trip time |
