#!/usr/bin/env python3
"""HQPlayer Status exporter for Prometheus."""
import argparse
import logging
import re
import socket
import time
import xml.etree.ElementTree as ET

from prometheus_client import Gauge, REGISTRY, GC_COLLECTOR, PLATFORM_COLLECTOR, PROCESS_COLLECTOR, start_http_server

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

for _c in (GC_COLLECTOR, PLATFORM_COLLECTOR, PROCESS_COLLECTOR):
    try:
        REGISTRY.unregister(_c)
    except Exception:
        pass

HQP_HOST = 'localhost'
HQP_PORT = 4321
_XML_HDR = '<?xml version="1.0" encoding="UTF-8"?>'
_CMD_STATUS = _XML_HDR + '<Status subscribe="0" />'
_CMD_INFO   = _XML_HDR + '<GetInfo/>'

g_up            = Gauge('hqplayer_up',                    '1 if HQPlayer TCP reachable')
g_state         = Gauge('hqplayer_state',                 'Playback state: 0=stopped 1=paused 2=playing')
g_proc_speed    = Gauge('hqplayer_process_speed',         'DSP throughput multiplier vs realtime')
g_out_fill      = Gauge('hqplayer_output_fill_ratio',     'Output buffer fill 0.0-1.0')
g_in_fill       = Gauge('hqplayer_input_fill_ratio',      'Input buffer fill (-1=N/A)')
g_out_delay     = Gauge('hqplayer_output_delay_samples',  'Output delay samples')
g_clips         = Gauge('hqplayer_clips_total',           'Digital clip count (session total)')
g_active_rate   = Gauge('hqplayer_active_rate_hz',        'Output sample rate Hz')
g_active_bits   = Gauge('hqplayer_active_bits',           'Output bit depth')
g_active_chan   = Gauge('hqplayer_active_channels',       'Output channel count')
g_src_rate      = Gauge('hqplayer_source_rate_hz',        'Source sample rate Hz')
g_src_bits      = Gauge('hqplayer_source_bits',           'Source bit depth')
g_volume        = Gauge('hqplayer_volume_db',             'Volume level')
g_apod          = Gauge('hqplayer_apod_flag',             'Apodization flag')
g_filter_20k    = Gauge('hqplayer_filter_20k_flag',       '20kHz cleanup filter active')
g_correction    = Gauge('hqplayer_correction_flag',       'DAC correction profile active')
g_info          = Gauge('hqplayer_info',                  'HQPlayer identity (always 1)',
                        ['version', 'mode', 'filter', 'shaper', 'source_is_dsd', 'output_fmt'])
g_track_info    = Gauge('hqplayer_track_info',            'Currently playing track (1 when playing)',
                        ['artist', 'albumartist', 'album', 'date', 'song',
                         'source_rate', 'source_bits', 'source_is_dsd', 'source_fmt'])
g_scrape_dur    = Gauge('hqplayer_scrape_duration_seconds', 'Last poll round-trip seconds')

_RATE_RE = re.compile(r'([\d.]+)\s*(MHz|kHz|Hz)(?:\s*x\s*(\d+))?', re.IGNORECASE)

def _parse_rate_hz(s: str) -> float:
    if not s:
        return 0.0
    # 5.17 sends raw integer Hz; older format was "192kHz" or "44.1kHz x512"
    try:
        return float(s)
    except ValueError:
        pass
    m = _RATE_RE.search(s)
    if not m:
        return 0.0
    val  = float(m.group(1))
    unit = m.group(2).lower()
    mult = int(m.group(3)) if m.group(3) else 1
    if unit == 'mhz':
        val *= 1_000_000
    elif unit == 'khz':
        val *= 1_000
    return val * mult

def _f(s, default=0.0):
    try: return float(s)
    except (TypeError, ValueError): return default

def _i(s, default=0):
    try: return int(s)
    except (TypeError, ValueError): return default

def _recv_xml(sock: socket.socket) -> str:
    data = b''
    while len(data) < 65536:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError('socket closed by server')
        data += chunk
        text = data.decode('utf-8', errors='replace')
        body = text.split('?>', 1)[-1].strip() if '?>' in text else text
        try:
            ET.fromstring(body)
            return text
        except ET.ParseError:
            # If we have a root closing tag, response is complete — return as-is
            # and let the caller deal with a broken parse (e.g. unescaped & in metadata).
            # Without this, we'd block on recv until socket timeout.
            if body.endswith('>') and re.search(r'</\w+>\s*$', body):
                return text
    raise ValueError('response exceeds 64KB limit')


class Poller:
    def __init__(self, interval: float):
        self.interval   = interval
        self._sock      = None
        self._backoff   = 1.0
        self._hqp_ver   = ''
        self._last_info = None

    def _connect(self) -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect((HQP_HOST, HQP_PORT))
        return s

    def _send(self, cmd: str) -> str:
        self._sock.sendall(cmd.encode())
        return _recv_xml(self._sock)

    def _fetch_info(self):
        raw  = self._send(_CMD_INFO)
        body = raw.split('?>', 1)[-1].strip() if '?>' in raw else raw
        root = ET.fromstring(body)
        self._hqp_ver = root.get('version', '')
        log.info('HQPlayer version: %s', self._hqp_ver)

    def _poll(self):
        t0   = time.monotonic()
        raw  = self._send(_CMD_STATUS)
        body = raw.split('?>', 1)[-1].strip() if '?>' in raw else raw
        try:
            root = ET.fromstring(body)
        except ET.ParseError as e:
            log.warning('Status XML parse error: %s — raw: %.200s', e, body)
            return  # keep g_up=1; stale metrics better than crash

        g_state.set(_i(root.get('state')))
        g_proc_speed.set(_f(root.get('process_speed')))
        g_out_fill.set(_f(root.get('output_fill')))
        g_in_fill.set(_f(root.get('input_fill'), -1.0))
        g_out_delay.set(_f(root.get('output_delay')))
        g_clips.set(_i(root.get('clips')))
        active_rate_val = _parse_rate_hz(root.get('active_rate', ''))
        g_active_rate.set(active_rate_val)
        active_bits_val = _i(root.get('active_bits'))
        g_active_bits.set(active_bits_val)
        if active_bits_val == 1:
            mhz = active_rate_val / 1_000_000 if active_rate_val > 0 else 0
            mhz_str = f'{mhz:.3f}'.rstrip('0').rstrip('.')
            output_fmt = f'1bit/{mhz_str}MHz'
        else:
            rate_khz = active_rate_val / 1000 if active_rate_val > 0 else 0
            rate_str = f'{rate_khz:.0f}' if rate_khz == int(rate_khz) else f'{rate_khz:.1f}'
            output_fmt = f'{active_bits_val}bit/{rate_str}kHz'
        g_active_chan.set(_i(root.get('active_channels')))
        g_volume.set(_f(root.get('volume')))
        g_apod.set(_i(root.get('apod')))
        g_filter_20k.set(_i(root.get('filter_20k')))
        g_correction.set(_i(root.get('correction')))

        meta = root.find('metadata')
        g_track_info.clear()
        if meta is not None:
            g_src_rate.set(_f(meta.get('samplerate')))
            g_src_bits.set(_i(meta.get('bits')))
            is_dsd = '1' if meta.get('sdm', '0') == '1' else '0'
            raw_rate = meta.get('samplerate', '')
            raw_bits = meta.get('bits', '')
            if is_dsd == '1':
                try:
                    dsd_mult = round(float(raw_rate) / (44100 * 64))
                    source_fmt = f'DSD{dsd_mult * 64}'
                except (ValueError, ZeroDivisionError):
                    source_fmt = 'DSD'
            else:
                try:
                    khz = float(raw_rate) / 1000
                    khz_str = f'{khz:.0f}' if khz == int(khz) else f'{khz:.1f}'
                    source_fmt = f'PCM {raw_bits}bit/{khz_str}kHz'
                except (ValueError, TypeError):
                    source_fmt = 'PCM'
            state = _i(root.get('state'))
            if state == 2:  # playing
                g_track_info.labels(
                    artist        = meta.get('artist',      ''),
                    albumartist   = meta.get('albumartist', ''),
                    album         = meta.get('album',       ''),
                    date          = meta.get('date',        ''),
                    song          = meta.get('song',        ''),
                    source_rate   = raw_rate,
                    source_bits   = raw_bits,
                    source_is_dsd = is_dsd,
                    source_fmt    = source_fmt,
                ).set(1)
        else:
            is_dsd = '0'

        new_info = {
            'version':       self._hqp_ver,
            'mode':          root.get('active_mode', ''),
            'filter':        root.get('active_filter', ''),
            'shaper':        root.get('active_shaper', ''),
            'source_is_dsd': is_dsd,
            'output_fmt':    output_fmt,
        }
        g_info.clear()
        g_info.labels(**new_info).set(1)
        self._last_info = new_info

        g_up.set(1)
        g_scrape_dur.set(time.monotonic() - t0)

    def run(self):
        while True:
            try:
                if self._sock is None:
                    log.info('Connecting to HQPlayer %s:%d', HQP_HOST, HQP_PORT)
                    self._sock    = self._connect()
                    self._backoff = 1.0
                    self._fetch_info()
                self._poll()
            except Exception as exc:
                log.warning('Poll error (%s) — retry in %.0fs', exc, self._backoff)
                g_up.set(0)
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
                time.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, 30.0)
                continue
            time.sleep(self.interval)


def main():
    ap = argparse.ArgumentParser(description='HQPlayer exporter for Prometheus')
    ap.add_argument('--port',     type=int,   default=9744)
    ap.add_argument('--interval', type=float, default=2.0, help='Poll interval seconds')
    args = ap.parse_args()

    start_http_server(args.port)
    log.info('Metrics on :%d — polling HQPlayer every %.1fs', args.port, args.interval)
    Poller(args.interval).run()


if __name__ == '__main__':
    main()
