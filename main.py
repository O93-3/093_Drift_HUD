import json
import logging
import os
import math
import re
import socket
import sys
import time
import ctypes
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt, QRectF, QPointF, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF, QGuiApplication, QLinearGradient
from PyQt6.QtWidgets import QApplication, QWidget


UDP_PORT = 5300
LAYOUT_FILE = "overlay_layout.json"
CARS_FILE = "cars.json"
SIMHUB_FORWARD_CONFIG_FILE = "simhub_forward.json"

HUD_CONFIG_FILE = "hud_config.json"
HUD_PROFILE_FILE = "hud_profile.json"
HUD_PROFILE_ORDER = ["1440P STREAM", "1440P CLEAN", "1080P STREAM", "1080P FULL"]
HUD_PROFILE_VISIBILITY = {
    "1440P STREAM": {
        "left": True,
        "style": False,
        "map": True,
        "g_meter": True,
        "steer": True,
        "input_car": True,
    },
    "1440P CLEAN": {
        "left": False,
        "style": False,
        "map": True,
        "g_meter": True,
        "steer": True,
        "input_car": False,
    },
    "1080P STREAM": {
        "left": True,
        "style": False,
        "map": True,
        "g_meter": True,
        "steer": True,
        "input_car": False,
    },
    "1080P FULL": {
        "left": True,
        "style": False,
        "map": True,
        "g_meter": True,
        "steer": True,
        "input_car": True,
    },
}
HUD_CONFIG_DEFAULT = {
    "splash_enabled": True,
    "splash_duration": 13.9,
    "simhub_forward_enabled": True,
    "simhub_forward_host": "127.0.0.1",
    "simhub_forward_port": 8001,
    "popup_normal_offset_y": 0,
    "popup_hero_offset_y": 80,
    "popup_hero_font_bonus": 7,
    "popup_normal_font_size": 25,
    "popup_normal_font_size_long": 21,
    "popup_hero_font_size": 34,
    "popup_hero_font_size_long": 30,
    "popup_hero_enabled": True,
    "popup_glow_scale": 1.0,
    "popup_marker_scale": 1.0,
    "popup_normal_seconds_scale": 1.0,
    "popup_hero_seconds_scale": 1.0,
    "operation_popup_enabled": True,
    "hold_long_seconds": 8.0,
    "limit_edge_threshold": 45,
    "limit_risk_threshold": 68,
    "limit_max_threshold": 86
}

def load_hud_config(base_dir):
    cfg = dict(HUD_CONFIG_DEFAULT)
    path = Path(base_dir) / HUD_CONFIG_FILE
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
    except Exception as e:
        print(f"HUD CONFIG ERROR: {e}")
    return cfg


# LIVE101 tuning knobs.  These are intentionally grouped here so real-run tweaks
# do not require hunting through the drawing and popup code.
REAR_SLIP_DISPLAY_MAX = 1.70   # lower = RL/RR bars grow faster, higher = calmer
POPUP_OPERATION_SECONDS = 1.25
POPUP_EVENT_SECONDS = 1.15
POPUP_COOLDOWN_SECONDS = 0.90
OPERATION_POPUP_SECONDS = 1.25
OPERATION_POPUP_COOLDOWN_SECONDS = 0.55
POPUP_EMPTY_DRAG_HINT_ALPHA = 62  # shown only while Alt is held, so empty popups can be moved

# LIVE107 visual pass: cleaner pop-street finish.
# No telemetry logic, popup logic, or panel positions are changed by these values.
STREET_HAZE_ALPHA = 46
STREET_TRACE_ALPHA = 52
STREET_GRAFFITI_ALPHA = 42
STREET_LABEL_ALPHA = 252
STREET_CORAL = QColor(238, 246, 255)     # REBASE: cool white accent, not pink
STREET_OFFWHITE = QColor(248, 252, 255) # REBASE: bright neutral white, no beige
STREET_AMBER = QColor(255, 184, 54)     # LIVE169: stronger stream orange
STREET_MINT = QColor(82, 255, 235)      # LIVE169: stronger stream mint
STREET_CHARCOAL = QColor(5, 8, 13)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def lerp(a, b, t):
    return a + (b - a) * t


def f32(buf, offset):
    import struct
    if len(buf) < offset + 4:
        return 0.0
    return struct.unpack_from("<f", buf, offset)[0]


def u8(buf, offset):
    if len(buf) < offset + 1:
        return 0
    return buf[offset]


def s32(buf, offset):
    import struct
    if len(buf) < offset + 4:
        return 0
    return struct.unpack_from("<i", buf, offset)[0]


def color_for_angle(abs_angle):
    if abs_angle >= 45:
        return QColor(STREET_CORAL)
    if abs_angle >= 30:
        return QColor(STREET_AMBER)
    if abs_angle >= 15:
        return QColor(STREET_MINT)
    return QColor(STREET_OFFWHITE)


def with_alpha(color, alpha):
    c = QColor(color)
    c.setAlpha(alpha)
    return c


def hold_color_for_seconds(seconds):
    if seconds >= 8.0:
        return QColor(STREET_CORAL)
    if seconds >= 5.0:
        return QColor(STREET_AMBER)
    if seconds >= 3.0:
        return QColor(STREET_MINT)
    return QColor(STREET_OFFWHITE)


def rating_for_angle(abs_angle):
    if abs_angle >= 45:
        return "MAX"
    if abs_angle >= 30:
        return "DEEP"
    if abs_angle >= 15:
        return "GOOD"
    return "LOW"


CLASS_MAP = {
    0: ("D", QColor(74, 196, 103)),
    1: ("C", QColor(148, 213, 66)),
    2: ("B", QColor(245, 166, 56)),
    3: ("A", QColor(234, 58, 80)),
    4: ("S1", QColor(247, 72, 178)),
    5: ("S2", QColor(151, 104, 255)),
    6: ("X", QColor(74, 224, 255)),
}

DRIVELINE_MAP = {
    0: "FWD",
    1: "RWD",
    2: "AWD",
}


def load_car_name_map():
    path = Path(__file__).resolve().parent / CARS_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def split_car_display_name(full_name):
    full_name = (full_name or "").strip()
    if not full_name:
        return "----", "Unknown", "Vehicle"

    parts = full_name.split()
    year = "----"
    rest_parts = parts[:]
    if parts and re.match(r"^\d{4}$", parts[0]):
        year = parts[0]
        rest_parts = parts[1:]

    rest = " ".join(rest_parts).strip()
    if not rest:
        return year, "Unknown", "Vehicle"

    two_word_makers = {
        "Alfa Romeo", "Aston Martin", "Land Rover", "Mercedes-Benz", "AMG Mercedes",
        "Donkervoort", "Formula Drift", "HDT VK", "HSV GEN", "Lamborghini", "Lotus",
        "McLaren", "RJ Anderson", "Saleen", "Toyota", "Vauxhall", "Zenvo", "Koenigsegg"
    }

    maker = rest_parts[0]
    model_parts = rest_parts[1:]
    if len(rest_parts) >= 2:
        pair = rest_parts[0] + " " + rest_parts[1]
        if pair in two_word_makers:
            maker = pair
            model_parts = rest_parts[2:]

    model = " ".join(model_parts).strip() or maker
    return year, maker, model


@dataclass
class GaugeLayout:
    cx: float
    cy: float
    half_width: float
    rise: float




def setup_hud_logging(base_dir):
    """Set up a small file logger for release/debug builds."""
    try:
        log_dir = Path(base_dir) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "hud_log.txt"
        logger = logging.getLogger("093_hud")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
        logger.info("=== 093 LAB. DRIFT DATA SYSTEM START ===")
        logger.info("base_dir=%s", base_dir)
        return logger
    except Exception:
        return logging.getLogger("093_hud_null")

def hud_log(logger, message, *args):
    try:
        if logger:
            logger.info(message, *args)
    except Exception:
        pass


class AngleOverlay(QWidget):
    def __init__(self):
        super().__init__()

        self.app_dir = Path(__file__).resolve().parent
        self.hud_logger = setup_hud_logging(self.app_dir)
        self.hud_config = load_hud_config(self.app_dir)
        hud_log(self.hud_logger, "hud_config loaded: splash=%s duration=%s simhub=%s:%s enabled=%s", self.hud_config.get("splash_enabled"), self.hud_config.get("splash_duration"), self.hud_config.get("simhub_forward_host"), self.hud_config.get("simhub_forward_port"), self.hud_config.get("simhub_forward_enabled"))

        # LIVE127: startup splash / 093 LAB. boot sequence.
        self.splash_start_time = time.monotonic()
        self.splash_duration = float(self.hud_config.get("splash_duration", 13.9))

        self.angle = 0.0
        self.display_angle = 0.0
        self.hold_seconds = 0.0
        self.speed_kmh = 0.0
        self.gear = "-"
        self.rpm = 0.0
        self.rpm_max = 9000.0
        self.accel_pct = 0.0
        self.brake_pct = 0.0
        self.clutch_pct = 0.0
        self.handbrake_pct = 0.0
        self.packet_count = 0
        self.last_packet_ms = 0
        self.demo_mode = False
        self.demo_phase = 0.0
        self.drag_pos = None
        self.god_entry_count = 0
        self.was_god_zone = False
        self.god_word = "GOD"
        self.car_class_id = 3
        self.car_class_label = "A"
        self.car_class_color = QColor(234, 58, 80)
        self.pi_value = 700
        self.driveline_id = 1
        self.driveline_label = "RWD"
        self.car_ordinal = 0
        self.car_full_name = "2002 Nissan Silvia Spec-R"
        self.car_year = "2002"
        self.car_make = "Nissan"
        self.car_model = "Silvia Spec-R"
        self.num_cylinders = 4
        self.engine_label = "I4 / 9.0K"
        self.rear_slip = 0.0
        self.rear_slip_rl = 0.0
        self.rear_slip_rr = 0.0
        self.rear_temp_avg = 0.0
        self.g_lat = 0.0
        self.g_long = 0.0
        self.g_vert = 0.0
        self.g_lat_display = 0.0
        self.g_long_display = 0.0
        self.g_trail = []
        self.steer_pct = 0.0
        self.counter_pct = 0.0
        self.flow_pct = 0.0
        self.flow_quality_label = "FLOW"
        self.flow_stability_pct = 0.0
        self.spin_risk = 0.0
        self.spin_label = "SAFE"
        self.limit_edge_cooldown = 0
        self.limit_edge_last_label = "SAFE"
        self.style_label = "CLEAN"
        self.drift_state = "GRIP"
        self.state_reason = "WAITING"
        self.active_hold = 0
        self.entry_hold = 0
        self.not_holding_seconds = 0.0
        self.prev_angle_abs = 0.0
        self.prev_rear_slip = 0.0
        self.prev_steer_pct = 0.0
        self.prev_flow_pct = 0.0
        self.popup_text = ""
        self.popup_ttl = 0
        self.popup_priority = 0
        self.operation_popup_text = ""
        self.operation_popup_ttl = 0
        self.prev_handbrake_pct = 0.0
        self.prev_clutch_pct = 0.0
        self.prev_brake_pct = 0.0
        self.prev_accel_pct = 0.0
        self.long_hold_shown = False
        self.spin_save_armed = False
        self.spin_save_cooldown = 0
        self.spin_save_peak_risk = 0.0
        self.spin_save_peak_angle = 0.0
        self.spin_save_recover_frames = 0
        self.style_override_label = ""
        self.style_override_ttl = 0
        self.packet_status_text = "NO DATA"
        self.position_x = 0.0
        self.position_y = 0.0
        self.position_z = 0.0
        self.live_map_points = []
        self.live_map_misses = []
        self.map_last_x = None
        self.map_last_z = None
        self.map_prev_speed = 0.0
        self.map_prev_abs_angle = 0.0
        self.map_prev_rear_slip = 0.0
        self.map_miss_cooldown = 0
        self.map_cursor_x = None
        self.map_cursor_z = None

        # LIVE164: runtime visibility controls.
        self.hud_visible = True
        self.hud_profile = "1440P STREAM"
        self.panel_visibility = dict(HUD_PROFILE_VISIBILITY[self.hud_profile])
        self._load_hud_profile_config()
        self.control_notice_text = ""
        self.control_notice_until = 0.0

        # LIVE164A: global Windows hotkey polling.
        # keyPressEvent only works when this HUD has focus; FH6 usually owns focus.
        self._hotkey_prev_down = set()
        self.key_help_visible = False
        self.key_help_until = 0.0
        self.popup_cooldown = 0
        self.operation_popup_cooldown = 0
        self.last_drift_state = 'GRIP'
        self.last_style_label = 'CLEAN'
        self.car_name_map = load_car_name_map()
        self.widget_offsets = {
            "vehicle_info": [0.0, 0.0],
            "input": [0.0, 0.0],
            "drift_panel": [0.0, 0.0],
            "style_panel": [0.0, 0.0],
            "map_panel": [0.0, 0.0],
            "g_meter": [0.0, 0.0],
            "steer_panel": [0.0, 0.0],
            "popup_panel": [0.0, 0.0],
            "operation_popup_panel": [0.0, 0.0],
        }
        self.drag_mode = None
        self.drag_widget = None
        self.drag_origin = None
        self.drag_widget_origin = None
        self._load_layout_config()

        # LIVE129: SimHub UDP passthrough.
        # FH6 sends telemetry to this HUD; this HUD can forward the same raw packet
        # to SimHub on a separate port so both can run together.
        self.simhub_forward_enabled = True
        self.simhub_forward_host = "127.0.0.1"
        self.simhub_forward_port = 8001
        self.simhub_forward_socket = None
        self.simhub_forward_count = 0
        self.simhub_forward_error = ""
        self._load_simhub_forward_config()
        self._apply_hud_config_simhub_override()
        self._setup_simhub_forward()

        self.sock = None
        self.udp_error = ""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setblocking(False)
            self.sock.bind(("127.0.0.1", UDP_PORT))
            print(f"UDP listening on 127.0.0.1:{UDP_PORT}")
        except OSError as e:
            self.udp_error = f"UDP ERROR: {e}"
            self.demo_mode = True
            print(self.udp_error)
            print("Starting in DEMO mode. Close other telemetry HUDs using port 5300, or change FH6 Data Out port.")

        self.setWindowTitle("OKUSURI FH6 DRIFT Overlay")
        self.resize(1720, 700)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

        self.hotkey_timer = QTimer(self)
        self.hotkey_timer.timeout.connect(self._poll_global_hotkeys)
        self.hotkey_timer.start(50)

        self._move_to_bottom_center()

    def _move_to_bottom_center(self):
        # Use the full available screen as the drawing surface.
        # This keeps individually dragged HUD parts from disappearing when moved far away.
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        self.setGeometry(geo)

    def _layout_config_path(self):
        return Path(__file__).resolve().parent / LAYOUT_FILE

    def _simhub_forward_config_path(self):
        return Path(__file__).resolve().parent / SIMHUB_FORWARD_CONFIG_FILE

    def _load_simhub_forward_config(self):
        # Optional config. If missing, create a sane default that avoids UDP port
        # contention: HUD listens on 5300, SimHub receives forwarded packets on 8001.
        path = self._simhub_forward_config_path()
        default_data = {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 8001,
            "note": "Set FH6 Data Out to 127.0.0.1:5300. Set SimHub to listen on 127.0.0.1:8001."
        }
        if not path.exists():
            try:
                path.write_text(json.dumps(default_data, indent=2), encoding="utf-8")
            except Exception:
                pass
            data = default_data
        else:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                self.simhub_forward_error = f"SIMHUB CONFIG ERROR: {e}"
                data = default_data
        self.simhub_forward_enabled = bool(data.get("enabled", True))
        self.simhub_forward_host = str(data.get("host", "127.0.0.1"))
        try:
            self.simhub_forward_port = int(data.get("port", 8001))
        except Exception:
            self.simhub_forward_port = 8001


    def _apply_hud_config_simhub_override(self):
        try:
            cfg = getattr(self, "hud_config", {}) or {}
            self.simhub_forward_enabled = bool(cfg.get("simhub_forward_enabled", self.simhub_forward_enabled))
            self.simhub_forward_host = str(cfg.get("simhub_forward_host", self.simhub_forward_host))
            self.simhub_forward_port = int(cfg.get("simhub_forward_port", self.simhub_forward_port))
        except Exception as e:
            self.simhub_forward_error = f"SIMHUB HUD CONFIG ERROR: {e}"

    def _setup_simhub_forward(self):
        self.simhub_forward_socket = None
        if not getattr(self, "simhub_forward_enabled", False):
            return
        try:
            self.simhub_forward_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            print(f"SimHub forwarding enabled -> {self.simhub_forward_host}:{self.simhub_forward_port}")
        except OSError as e:
            self.simhub_forward_error = f"SIMHUB FORWARD ERROR: {e}"
            self.simhub_forward_socket = None
            print(self.simhub_forward_error)

    def forward_simhub_packet(self, data):
        # Forward the raw FH6 packet unchanged. This keeps SimHub compatible with
        # the same Data Out format while avoiding both apps binding the same port.
        if not getattr(self, "simhub_forward_enabled", False):
            return
        sock = getattr(self, "simhub_forward_socket", None)
        if sock is None:
            return
        try:
            sock.sendto(data, (self.simhub_forward_host, self.simhub_forward_port))
            self.simhub_forward_count += 1
        except OSError as e:
            self.simhub_forward_error = f"SIMHUB FORWARD ERROR: {e}"
    def _load_layout_config(self):
        path = self._layout_config_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in self.widget_offsets.keys():
                if key in data and isinstance(data[key], list) and len(data[key]) == 2:
                    self.widget_offsets[key] = [float(data[key][0]), float(data[key][1])]
        except Exception:
            pass

    def _save_layout_config(self):
        path = self._layout_config_path()
        try:
            path.write_text(json.dumps(self.widget_offsets, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def vehicle_info_rect(self):
        x, y, w, h = self.vehicle_info_geometry()
        return QRectF(x, y, w, h)

    def input_group_rect(self):
        x, y, w, h = self.input_group_geometry()
        return QRectF(x, y, w, h)

    def drift_panel_rect(self):
        x, y, w, h = self.drift_panel_geometry()
        return QRectF(x, y, w, h)

    def style_panel_rect(self):
        x, y, w, h = self.style_panel_geometry()
        return QRectF(x, y, w, h)

    def map_panel_rect(self):
        x, y, w, h = self.map_panel_geometry()
        return QRectF(x, y, w, h)

    def g_meter_rect(self):
        x, y, w, h = self.g_meter_geometry()
        return QRectF(x, y, w, h)

    def popup_panel_rect(self):
        x, y, w, h = self.popup_panel_geometry()
        return QRectF(x, y, w, h)

    def operation_popup_panel_rect(self):
        x, y, w, h = self.operation_popup_panel_geometry()
        return QRectF(x, y, w, h)

    def parse_packet(self, buf):
        # FH6 / Forza Data Out offsets.
        speed_ms = f32(buf, 256)
        acceleration_x = f32(buf, 20)
        acceleration_y = f32(buf, 24)
        acceleration_z = f32(buf, 28)
        velocity_x = f32(buf, 32)
        velocity_z = f32(buf, 40)

        g_lat = 0.0
        g_long = 0.0
        speed_plane = math.hypot(velocity_x, velocity_z)
        if speed_plane > 0.75:
            fx = velocity_x / speed_plane
            fz = velocity_z / speed_plane
            # Convert world acceleration into a simple car-relative G ball.
            g_long = (acceleration_x * fx + acceleration_z * fz) / 9.80665
            g_lat = (acceleration_x * fz - acceleration_z * fx) / 9.80665
        g_vert = acceleration_y / 9.80665

        angle = 0.0
        if abs(speed_ms) > 4.0 and (abs(velocity_x) + abs(velocity_z)) > 0.5:
            angle = math.degrees(math.atan2(velocity_x, velocity_z))
            if not math.isfinite(angle):
                angle = 0.0
            angle = clamp(angle, -90.0, 90.0)

        gear_raw = u8(buf, 319)
        gear = "R" if gear_raw == 0 else str(gear_raw)

        rpm_max = f32(buf, 8)
        rpm = f32(buf, 16)

        accel = u8(buf, 315)
        brake = u8(buf, 316)
        clutch = u8(buf, 317)
        handbrake = u8(buf, 318)

        steer_raw = 0
        if len(buf) >= 321:
            import struct
            steer_raw = struct.unpack_from('<b', buf, 320)[0]

        # Vehicle metadata from the Sled section
        car_ordinal = max(0, s32(buf, 212))
        car_class_id = max(0, min(6, s32(buf, 216)))
        pi_value = max(0, s32(buf, 220))
        driveline_id = max(0, min(2, s32(buf, 224)))
        num_cylinders = max(0, s32(buf, 228))

        position_x = f32(buf, 244)
        position_y = f32(buf, 248)
        position_z = f32(buf, 252)

        tire_combined_rl = abs(f32(buf, 188))
        tire_combined_rr = abs(f32(buf, 192))
        rear_slip_rl = tire_combined_rl
        rear_slip_rr = tire_combined_rr
        rear_slip = (rear_slip_rl + rear_slip_rr) * 0.5

        tire_temp_rl = f32(buf, 276)
        tire_temp_rr = f32(buf, 280)
        rear_temp_avg = (tire_temp_rl + tire_temp_rr) * 0.5 if (tire_temp_rl > 0 or tire_temp_rr > 0) else 0.0

        return {
            "angle": clamp(angle, -90.0, 90.0),
            "speed_kmh": speed_ms * 3.6,
            "gear": gear,
            "rpm": rpm,
            "rpm_max": rpm_max if rpm_max > 1 else 9000.0,
            "accel_pct": accel / 255.0 * 100.0,
            "brake_pct": brake / 255.0 * 100.0,
            "clutch_pct": clutch / 255.0 * 100.0,
            "handbrake_pct": handbrake / 255.0 * 100.0,
            "steer_pct": clamp(steer_raw / 127.0 * 100.0, -100.0, 100.0),
            "car_ordinal": car_ordinal,
            "car_class_id": car_class_id,
            "pi_value": pi_value,
            "driveline_id": driveline_id,
            "num_cylinders": num_cylinders,
            "position_x": position_x,
            "position_y": position_y,
            "position_z": position_z,
            "rear_slip": rear_slip,
            "rear_slip_rl": rear_slip_rl,
            "rear_slip_rr": rear_slip_rr,
            "rear_temp_avg": rear_temp_avg,
            "g_lat": clamp(g_lat, -2.5, 2.5),
            "g_long": clamp(g_long, -2.5, 2.5),
            "g_vert": clamp(g_vert, -3.0, 3.0),
        }

    def poll_udp(self):
        got = False
        if self.sock is None:
            return False

        while True:
            try:
                data, _addr = self.sock.recvfrom(2048)
                self.forward_simhub_packet(data)
            except BlockingIOError:
                break
            except OSError as e:
                self.udp_error = f"UDP ERROR: {e}"
                break

            if len(data) >= 324:
                parsed = self.parse_packet(data)
                self.angle = parsed["angle"]
                self.speed_kmh = parsed["speed_kmh"]
                self.gear = parsed["gear"]
                self.rpm = parsed["rpm"]
                self.rpm_max = parsed["rpm_max"]
                self.accel_pct = parsed["accel_pct"]
                self.brake_pct = parsed["brake_pct"]
                self.clutch_pct = parsed["clutch_pct"]
                self.handbrake_pct = parsed["handbrake_pct"]
                self.steer_pct = parsed.get("steer_pct", 0.0)
                self.rear_slip = parsed.get("rear_slip", 0.0)
                self.rear_slip_rl = parsed.get("rear_slip_rl", self.rear_slip)
                self.rear_slip_rr = parsed.get("rear_slip_rr", self.rear_slip)
                self.rear_temp_avg = parsed.get("rear_temp_avg", 0.0)
                self.g_lat = parsed.get("g_lat", 0.0)
                self.g_long = parsed.get("g_long", 0.0)
                self.g_vert = parsed.get("g_vert", 0.0)
                self.position_x = parsed.get("position_x", 0.0)
                self.position_y = parsed.get("position_y", 0.0)
                self.position_z = parsed.get("position_z", 0.0)
                self.car_ordinal = parsed.get("car_ordinal", 0)
                self.car_class_id = parsed["car_class_id"] if parsed["car_class_id"] in CLASS_MAP else self.car_class_id
                self.pi_value = parsed["pi_value"] if parsed["pi_value"] > 0 else self.pi_value
                self.driveline_id = parsed["driveline_id"] if parsed["driveline_id"] in DRIVELINE_MAP else self.driveline_id
                self.num_cylinders = parsed.get("num_cylinders", self.num_cylinders) or self.num_cylinders
                self.car_class_label, self.car_class_color = CLASS_MAP.get(self.car_class_id, ("A", QColor(234, 58, 80)))
                self.driveline_label = DRIVELINE_MAP.get(self.driveline_id, "RWD")

                mapped_name = self.car_name_map.get(str(self.car_ordinal))
                if mapped_name:
                    self.car_full_name = mapped_name
                    self.car_year, self.car_make, self.car_model = split_car_display_name(mapped_name)

                cyl_label = f"I{self.num_cylinders}" if self.num_cylinders > 0 else "ENG"
                self.engine_label = f"{cyl_label} / {self.rpm_max / 1000.0:.1f}K"

                self.packet_count += 1
                self.last_packet_ms = 0
                got = True

        return got

    def _tick(self):
        self.poll_udp()

        if self.demo_mode:
            self.demo_phase += 0.018
            self.angle = math.sin(self.demo_phase) * 72.0
            self.speed_kmh = 86 + math.sin(self.demo_phase * 1.4) * 22
            self.gear = "3"
            self.rpm_max = 9000.0
            self.rpm = 5200 + (math.sin(self.demo_phase * 2.2) + 1.0) * 1700
            self.accel_pct = clamp(62 + math.sin(self.demo_phase * 2.0) * 38, 0, 100)
            self.brake_pct = clamp(max(0, -math.sin(self.demo_phase * 1.5)) * 80, 0, 100)
            self.clutch_pct = 0.0
            self.handbrake_pct = clamp(max(0, math.sin(self.demo_phase * 0.8 - 1.2)) * 100, 0, 100)
            self.steer_pct = clamp(math.sin(self.demo_phase * 1.7) * 100, -100, 100)
            self.car_class_id = 3
            self.car_class_label, self.car_class_color = CLASS_MAP.get(self.car_class_id, ("A", QColor(234, 58, 80)))
            self.pi_value = 700
            self.driveline_id = 1
            self.driveline_label = DRIVELINE_MAP.get(self.driveline_id, "RWD")
            self.car_full_name = "2002 Nissan Silvia Spec-R"
            self.car_year, self.car_make, self.car_model = split_car_display_name(self.car_full_name)
            self.num_cylinders = 4
            self.engine_label = "I4 / 9.0K"
            self.rear_slip_rl = 0.30 + abs(math.sin(self.demo_phase * 1.18 + 0.25)) * 1.25
            self.rear_slip_rr = 0.30 + abs(math.sin(self.demo_phase * 1.06 - 0.35)) * 1.18
            self.rear_slip = (self.rear_slip_rl + self.rear_slip_rr) * 0.5
            self.rear_temp_avg = 72 + abs(math.sin(self.demo_phase * 0.55)) * 18
            self.g_lat = math.sin(self.demo_phase * 1.3) * 0.85 + math.sin(self.demo_phase * 3.0) * 0.18
            self.g_long = math.cos(self.demo_phase * 0.9) * 0.55 + math.sin(self.demo_phase * 2.2) * 0.12
            self.g_vert = 1.0 + math.sin(self.demo_phase * 1.7) * 0.05
            self.position_x = math.cos(self.demo_phase * 0.45) * 220 + math.sin(self.demo_phase * 1.4) * 28
            self.position_z = math.sin(self.demo_phase * 0.45) * 160 + math.cos(self.demo_phase * 1.1) * 22

        self.last_packet_ms += 16
        dt = 0.016

        # Smooth displayed angle a little so it does not vibrate too hard.
        self.display_angle += (self.angle - self.display_angle) * 0.22
        self.g_lat_display += (self.g_lat - self.g_lat_display) * 0.18
        self.g_long_display += (self.g_long - self.g_long_display) * 0.18
        self.g_trail.append((self.g_lat_display, self.g_long_display))
        if len(self.g_trail) > 30:
            self.g_trail = self.g_trail[-30:]
        abs_angle = abs(self.display_angle)

        # COUNTER: use the real drift-side vs steering-side relationship.
        # In this overlay's data/sign convention, a valid counter-steer happens when
        # display_angle and steer_pct point to the same side (same sign).
        countering = abs_angle >= 8.0 and (self.display_angle * self.steer_pct) > 0.0
        if countering:
            angle_factor = clamp((abs_angle - 8.0) / 42.0, 0.0, 1.0)
            target_counter = clamp(abs(self.steer_pct) * (0.45 + 0.55 * angle_factor), 0.0, 100.0)
        else:
            target_counter = 0.0
        self.counter_pct += (target_counter - self.counter_pct) * 0.24

        holding_drift = self.speed_kmh > 14 and abs_angle >= 12 and self.rear_slip >= 0.25
        if holding_drift:
            self.hold_seconds += dt
            self.not_holding_seconds = 0.0
        else:
            self.not_holding_seconds += dt
            if self.not_holding_seconds >= 0.45:
                self.hold_seconds = 0.0
                self.long_hold_shown = False
                self.not_holding_seconds = 0.0

        if self.hold_seconds >= 5.0 and not self.long_hold_shown:
            self.request_popup("LONG HOLD!", dt, seconds=1.65, cooldown_seconds=1.6)
            self.long_hold_shown = True

        # Drift flow / spin risk / style.
        # LIVE124: FLOW is now less about "big angle only" and more about
        # smooth sustained drift: stable angle, stable rear slip, steady throttle,
        # and useful counter-steer all raise the score. Sudden corrections lower it.
        angle_delta = abs(abs_angle - self.prev_angle_abs)
        slip_delta = abs(self.rear_slip - self.prev_rear_slip)
        steer_delta = abs(self.steer_pct - self.prev_steer_pct)
        accel_delta = abs(self.accel_pct - self.prev_accel_pct)

        angle_score = clamp((abs_angle - 8.0) / 42.0 * 36.0, 0.0, 36.0)
        slip_score = clamp((self.rear_slip - 0.25) / 1.45 * 20.0, 0.0, 20.0)
        throttle_score = clamp((self.accel_pct - 10.0) / 55.0 * 14.0, 0.0, 14.0)
        counter_score = clamp(self.counter_pct / 100.0 * 12.0, 0.0, 12.0) if countering else 0.0

        stability_score = 0.0
        if holding_drift:
            stability_score += clamp((1.0 - angle_delta / 7.5) * 9.0, 0.0, 9.0)
            stability_score += clamp((1.0 - slip_delta / 0.42) * 7.0, 0.0, 7.0)
            stability_score += clamp((1.0 - accel_delta / 26.0) * 5.0, 0.0, 5.0)
        calm_bonus = clamp((self.hold_seconds - 1.0) / 5.0 * 8.0, 0.0, 8.0)

        chaos_penalty = 0.0
        chaos_penalty += clamp((angle_delta - 8.0) / 16.0 * 10.0, 0.0, 10.0)
        chaos_penalty += clamp((slip_delta - 0.45) / 0.85 * 10.0, 0.0, 10.0)
        chaos_penalty += clamp((steer_delta - 22.0) / 55.0 * 7.0, 0.0, 7.0)
        if self.speed_kmh < 10:
            chaos_penalty += 18.0

        target_flow = angle_score + slip_score + throttle_score + counter_score + stability_score + calm_bonus - chaos_penalty
        target_flow = clamp(target_flow, 0.0, 100.0)
        self.flow_pct += (target_flow - self.flow_pct) * 0.22
        self.flow_pct = clamp(self.flow_pct, 0.0, 100.0)
        self.flow_stability_pct = clamp(stability_score / 21.0 * 100.0, 0.0, 100.0)
        if self.flow_pct >= 82 and self.flow_stability_pct >= 55:
            self.flow_quality_label = "LOCKED"
        elif self.flow_pct >= 66:
            self.flow_quality_label = "SMOOTH"
        elif holding_drift and chaos_penalty >= 14:
            self.flow_quality_label = "CHASE"
        elif holding_drift:
            self.flow_quality_label = "FLOW"
        else:
            self.flow_quality_label = "BUILD"

        # LIVE125: LIMIT/EDGE is now a broader "near the limit" meter.
        # It still feeds SPIN SAVE, but it is not only raw angle: it also reacts to
        # fast angle change, rear slip growth, low-speed deep angle, throttle push,
        # and whether counter-steer is keeping up.
        counter_need = clamp((abs_angle - 18.0) / 42.0 * 100.0, 0.0, 100.0)
        counter_deficit = max(0.0, counter_need - self.counter_pct)

        risk = 0.0
        risk += clamp((abs_angle - 14.0) / 44.0 * 50.0, 0.0, 50.0)
        risk += clamp((self.rear_slip - 0.45) / 1.35 * 20.0, 0.0, 20.0)
        risk += clamp((angle_delta - 3.5) / 14.0 * 12.0, 0.0, 12.0)
        risk += clamp((slip_delta - 0.18) / 0.75 * 10.0, 0.0, 10.0)
        risk += clamp((counter_deficit - 8.0) / 70.0 * 10.0, 0.0, 10.0)
        if self.accel_pct >= 62 and self.rear_slip >= 0.72 and abs_angle >= 22:
            risk += clamp((self.accel_pct - 62.0) / 38.0 * 8.0, 0.0, 8.0)
        if self.speed_kmh < 18 and abs_angle >= 30:
            risk += clamp((30.0 - self.speed_kmh) / 20.0 * 8.0, 0.0, 8.0)
        if holding_drift and self.flow_quality_label in ("SMOOTH", "LOCKED") and countering:
            risk -= clamp((self.flow_pct - 58.0) / 34.0 * 8.0, 0.0, 8.0)
        if self.speed_kmh < 8 and abs_angle < 16:
            risk *= 0.35

        target_risk = clamp(risk, 0.0, 100.0)
        self.spin_risk += (target_risk - self.spin_risk) * 0.30
        self.spin_risk = clamp(self.spin_risk, 0.0, 100.0)

        prev_spin_label = self.spin_label
        if self.spin_risk >= 84:
            self.spin_label = "MAX"
        elif self.spin_risk >= 58:
            self.spin_label = "RISK"
        elif self.spin_risk >= 28:
            self.spin_label = "EDGE"
        else:
            self.spin_label = "SAFE"

        if self.limit_edge_cooldown > 0:
            self.limit_edge_cooldown -= 1
        if (
            self.spin_label == "EDGE" and
            prev_spin_label == "SAFE" and
            holding_drift and
            self.limit_edge_cooldown <= 0
        ):
            if self.request_popup("LIMIT EDGE!", dt, seconds=1.15, cooldown_seconds=1.2):
                self.limit_edge_cooldown = int(3.2 / dt)
        self.limit_edge_last_label = self.spin_label

        style = "CLEAN"
        if self.spin_label == "MAX":
            style = "DANGER"
        elif self.spin_label == "RISK":
            style = "EDGE"
        elif self.rear_slip >= 1.35 and self.accel_pct >= 50 and abs_angle >= 28:
            style = "WILD"
        elif self.flow_quality_label == "LOCKED" and abs_angle >= 24:
            style = "LOCKED"
        elif self.flow_pct >= 76 and abs_angle >= 30:
            style = "DEEP"
        elif self.flow_pct >= 56 and self.rear_slip >= 0.65:
            style = "SMOOTH"
        elif holding_drift:
            style = "CLEAN"
        elif abs_angle >= 10 and self.speed_kmh > 15:
            style = "ENTRY"
        else:
            style = "GRIP"
        if self.style_override_ttl > 0:
            self.style_override_ttl -= 1
            style = self.style_override_label or style
        self.style_label = style

        # LIVE123: SPIN SAVE detection.
        # Arm when the car reaches a dangerous LIMIT/EDGE moment, then fire only
        # after the driver actually recovers it. Cooldown prevents spam.
        if self.spin_save_cooldown > 0:
            self.spin_save_cooldown -= 1

        spin_save_danger = (
            self.spin_risk >= 76 and
            abs_angle >= 24 and
            self.speed_kmh > 12 and
            self.rear_slip >= 0.55
        )
        if spin_save_danger:
            self.spin_save_armed = True
            self.spin_save_peak_risk = max(self.spin_save_peak_risk, self.spin_risk)
            self.spin_save_peak_angle = max(self.spin_save_peak_angle, abs_angle)
            self.spin_save_recover_frames = 0

        if self.spin_save_armed:
            self.spin_save_peak_risk = max(self.spin_save_peak_risk, self.spin_risk)
            self.spin_save_peak_angle = max(self.spin_save_peak_angle, abs_angle)
            recovered_from_limit = (
                self.spin_save_peak_risk >= 78 and
                self.spin_risk <= 42 and
                8 <= abs_angle <= 36 and
                self.speed_kmh > 12 and
                self.rear_slip >= 0.25
            )
            if recovered_from_limit:
                self.spin_save_recover_frames += 1
            else:
                self.spin_save_recover_frames = 0

            if (
                self.spin_save_recover_frames >= 3 and
                self.spin_save_cooldown <= 0
            ):
                self.request_popup("SPIN SAVE!", dt, seconds=1.95, cooldown_seconds=2.3)
                self.style_override_label = "SAVE"
                self.style_override_ttl = int(2.3 / dt)
                self.spin_save_cooldown = int(4.2 / dt)
                self.spin_save_armed = False
                self.spin_save_peak_risk = 0.0
                self.spin_save_peak_angle = 0.0
                self.spin_save_recover_frames = 0

        if self.speed_kmh < 8 or abs_angle < 5:
            self.spin_save_armed = False
            self.spin_save_peak_risk = 0.0
            self.spin_save_peak_angle = 0.0
            self.spin_save_recover_frames = 0

        # Drift state: reduce ENTRY spam and prefer ANGLE/SMOKE once established.
        drift_like = (
            (abs_angle > 8 and self.speed_kmh > 15) or
            self.rear_slip > 0.35 or
            (abs(self.steer_pct) > 28 and self.accel_pct > 20 and self.speed_kmh > 20) or
            self.handbrake_pct > 12 or
            (self.brake_pct > 20 and self.speed_kmh > 25)
        )
        if drift_like:
            self.active_hold = 10
        else:
            self.active_hold = max(0, self.active_hold - 1)

        entering_now = (
            (
                (self.handbrake_pct > 14 and self.speed_kmh > 18) or
                (self.brake_pct > 26 and self.speed_kmh > 28 and abs_angle < 14) or
                (abs(self.steer_pct) > 42 and self.accel_pct > 10 and self.speed_kmh > 22 and abs_angle < 12) or
                (abs_angle > 12 and self.prev_angle_abs < 6 and self.speed_kmh > 22)
            ) and self.rear_slip < 1.0
        )
        self.entry_hold = max(0, self.entry_hold - 1)
        if entering_now:
            self.entry_hold = 8

        if self.speed_kmh < 8 and abs_angle < 5:
            self.drift_state = "GRIP"
            self.state_reason = "WAITING"
        elif self.spin_label == "MAX" and self.speed_kmh > 12:
            self.drift_state = "SPIN"
            self.state_reason = "LIMIT MAX"
        elif self.active_hold > 0 and self.rear_slip >= 1.15 and self.accel_pct >= 28:
            self.drift_state = "SMOKE"
            self.state_reason = "REAR SLIP"
        elif self.active_hold > 0 and abs_angle >= 18 and self.speed_kmh > 14:
            self.drift_state = "ANGLE"
            self.state_reason = "ANGLE HOLD"
        elif self.entry_hold > 0:
            self.drift_state = "ENTRY"
            self.state_reason = "INITIATE"
        elif self.active_hold > 0:
            self.drift_state = "HOLD"
            self.state_reason = "STABLE"
        else:
            self.drift_state = "GRIP"
            self.state_reason = "RESET"

        self.update_live_map(abs_angle, holding_drift)

        in_god_zone = abs_angle > 60
        if in_god_zone and not self.was_god_zone:
            self.god_entry_count += 1
            self.god_word = "CAT" if self.god_entry_count % 10 == 0 else "GOD"
        self.was_god_zone = in_god_zone

        if self.popup_cooldown > 0:
            self.popup_cooldown -= 1
        if self.operation_popup_cooldown > 0:
            self.operation_popup_cooldown -= 1

        if self.popup_ttl > 0:
            self.popup_ttl -= 1
        else:
            self.popup_text = ""
            self.popup_priority = 0

        if self.operation_popup_ttl > 0:
            self.operation_popup_ttl -= 1
        else:
            self.operation_popup_text = ""

        # Extra popup events to restore richer callouts.
        # Operation popups are intentionally high priority because they are useful on stream.
        handbrake_hit = self.handbrake_pct >= 38 and self.prev_handbrake_pct < 18 and self.speed_kmh > 8
        clutch_kick = (
            self.clutch_pct >= 58 and self.prev_clutch_pct < 22 and
            self.accel_pct >= 18 and self.speed_kmh > 8
        )
        foot_brake = (
            self.brake_pct >= 48 and self.prev_brake_pct < 20 and
            self.handbrake_pct < 18 and self.speed_kmh > 10
        )

        # LIVE102: operation popups are now independent from the normal popup.
        # This keeps HANDBRAKE / FOOT BRAKE / CLUTCH KICK visible even when
        # ENTRY, SMOKE, BIG ANGLE, LONG HOLD, etc. are also firing.
        if self.operation_popup_cooldown <= 0:
            if handbrake_hit:
                self.operation_popup_text = "HANDBRAKE!"
                self.operation_popup_ttl = int(OPERATION_POPUP_SECONDS / dt)
                self.operation_popup_cooldown = int(OPERATION_POPUP_COOLDOWN_SECONDS / dt)
                self.style_override_label = "ENTRY"
                self.style_override_ttl = int(1.15 / dt)
            elif clutch_kick:
                self.operation_popup_text = "CLUTCH KICK!"
                self.operation_popup_ttl = int(OPERATION_POPUP_SECONDS / dt)
                self.operation_popup_cooldown = int(OPERATION_POPUP_COOLDOWN_SECONDS / dt)
                self.style_override_label = "KICK"
                self.style_override_ttl = int(1.15 / dt)
            elif foot_brake:
                self.operation_popup_text = "FOOT BRAKE!"
                self.operation_popup_ttl = int(OPERATION_POPUP_SECONDS / dt)
                self.operation_popup_cooldown = int(OPERATION_POPUP_COOLDOWN_SECONDS / dt)
                self.style_override_label = "BRAKE"
                self.style_override_ttl = int(1.15 / dt)

        # LIVE128: popup priority lanes. Hero events can overwrite lower callouts.
        if abs_angle >= 46 and self.prev_angle_abs < 46:
            self.request_popup("BIG ANGLE!", dt, seconds=1.85, cooldown_seconds=1.2)
        elif self.popup_cooldown <= 0:
            if self.style_label == "LOCKED" and self.last_style_label != "LOCKED":
                self.request_popup("FLOW LOCK!", dt, seconds=1.55, cooldown_seconds=1.8)
            elif self.style_label == "DEEP" and self.last_style_label != "DEEP":
                self.request_popup("DEEP LINE!", dt, seconds=1.20, cooldown_seconds=1.4)
            elif self.drift_state == "SMOKE" and self.last_drift_state != "SMOKE":
                self.request_popup("SMOKE RUN!", dt, seconds=1.10, cooldown_seconds=1.4)
            elif self.drift_state == "ENTRY" and self.last_drift_state != "ENTRY":
                self.request_popup("ENTRY!", dt, seconds=1.00, cooldown_seconds=1.1)

        self.last_drift_state = self.drift_state
        self.last_style_label = self.style_label
        self.prev_angle_abs = abs_angle
        self.prev_rear_slip = self.rear_slip
        self.prev_steer_pct = self.steer_pct
        self.prev_flow_pct = self.flow_pct
        self.prev_handbrake_pct = self.handbrake_pct
        self.prev_clutch_pct = self.clutch_pct
        self.prev_brake_pct = self.brake_pct
        self.prev_accel_pct = self.accel_pct
        self.update()


    def popup_event_priority(self, text):
        priorities = {
            "SPIN SAVE!": 100,
            "BIG ANGLE!": 95,
            "LONG HOLD!": 80,
            "FLOW LOCK!": 75,
            "DEEP LINE!": 60,
            "LIMIT EDGE!": 55,
            "SMOKE RUN!": 45,
            "ENTRY!": 40,
        }
        return priorities.get(str(text), 10)

    def popup_event_seconds(self, text):
        durations = {
            "SPIN SAVE!": 1.95,
            "BIG ANGLE!": 1.85,
            "LONG HOLD!": 1.65,
            "FLOW LOCK!": 1.55,
            "DEEP LINE!": 1.20,
            "LIMIT EDGE!": 1.15,
            "SMOKE RUN!": 1.10,
            "ENTRY!": 1.00,
        }
        base_seconds = durations.get(str(text), POPUP_EVENT_SECONDS)
        try:
            if self.is_hero_popup(text):
                scale = float(self.hud_config.get("popup_hero_seconds_scale", 1.0))
            else:
                scale = float(self.hud_config.get("popup_normal_seconds_scale", 1.0))
            return max(0.25, base_seconds * scale)
        except Exception:
            return base_seconds

    def request_popup(self, text, dt, seconds=None, cooldown_seconds=None):
        # LIVE128: priority lanes. High-value events may replace low-value popups,
        # but low-value callouts do not interrupt hero moments.
        priority = self.popup_event_priority(text)
        current_priority = self.popup_priority if self.popup_ttl > 0 else 0
        if self.popup_ttl > 0 and priority < current_priority:
            return False
        safe_dt = max(float(dt), 0.001)
        self.popup_text = str(text)
        self.popup_priority = priority
        self.popup_ttl = max(1, int((seconds if seconds is not None else self.popup_event_seconds(text)) / safe_dt))
        if cooldown_seconds is not None:
            self.popup_cooldown = max(self.popup_cooldown, int(float(cooldown_seconds) / safe_dt))
        return True

    def is_hero_popup(self, text=None):
        return self.popup_event_priority(text if text is not None else self.popup_text) >= 75

    def _show_control_notice(self, text, seconds=1.45):
        self.control_notice_text = text
        self.control_notice_until = time.monotonic() + seconds
        self.update()

    def _visibility_text(self, name, visible):
        return f"{name} {'ON' if visible else 'OFF'}"

    def _toggle_panel_visibility(self, key, label):
        self.panel_visibility[key] = not bool(self.panel_visibility.get(key, True))
        self._show_control_notice(self._visibility_text(label, self.panel_visibility[key]))

    def _reset_live_map(self):
        self.live_map_points.clear()
        self.live_map_misses.clear()
        self.map_last_x = None
        self.map_last_z = None
        self.map_cursor_x = None
        self.map_cursor_z = None
        self._show_control_notice("TRACK MAP RESET", 1.65)

    def draw_control_notice(self, painter):
        if not self.control_notice_text:
            return
        now = time.monotonic()
        if now >= self.control_notice_until:
            self.control_notice_text = ""
            return

        remain = self.control_notice_until - now
        alpha = int(220 * clamp(remain / 0.35, 0.0, 1.0))
        W = self.width()
        H = self.height()
        box_w = 300
        box_h = 44
        x = W * 0.5 - box_w * 0.5
        y = H - 92

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(2, 7, 12, int(alpha * 0.58)))
        painter.drawRoundedRect(QRectF(x, y, box_w, box_h), 9, 9)
        painter.setPen(QPen(QColor(STREET_MINT.red(), STREET_MINT.green(), STREET_MINT.blue(), int(alpha * 0.72)), 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawRoundedRect(QRectF(x + 1, y + 1, box_w - 2, box_h - 2), 9, 9)
        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), int(alpha * 0.58)))
        painter.drawText(QRectF(x + 14, y + 7, box_w - 28, 12), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "093 HUD CONTROL")
        painter.setFont(QFont("Arial Black", 14))
        painter.setPen(QColor(250, 253, 255, alpha))
        painter.drawText(QRectF(x, y + 16, box_w, 24), Qt.AlignmentFlag.AlignCenter, self.control_notice_text)
        painter.restore()

    def _global_key_down(self, vk):
        try:
            return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
        except Exception:
            return False

    def _global_combo_pressed_once(self, combo_name, vk, require_shift=False):
        ctrl_down = self._global_key_down(0x11) or self._global_key_down(0xA2) or self._global_key_down(0xA3)
        shift_down = self._global_key_down(0x10) or self._global_key_down(0xA0) or self._global_key_down(0xA1)
        down = ctrl_down and (shift_down if require_shift else True) and self._global_key_down(vk)
        was_down = combo_name in self._hotkey_prev_down
        if down:
            self._hotkey_prev_down.add(combo_name)
        else:
            self._hotkey_prev_down.discard(combo_name)
        return down and not was_down

    def _exit_hud(self):
        self._shutdown_resources()
        app = QApplication.instance()
        if app is not None:
            app.quit()
        self.close()
        # Public release safety: if a native handle or Qt tool-window keeps the
        # app alive in the background, force the process down after cleanup.
        QTimer.singleShot(120, lambda: os._exit(0))

    def _shutdown_resources(self):
        for attr in ("hotkey_timer", "timer"):
            obj = getattr(self, attr, None)
            try:
                if obj is not None:
                    obj.stop()
            except Exception:
                pass

        for attr in ("sock", "simhub_forward_socket"):
            obj = getattr(self, attr, None)
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass
            try:
                setattr(self, attr, None)
            except Exception:
                pass

    def closeEvent(self, event):
        self._shutdown_resources()
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)
        try:
            event.accept()
        except Exception:
            pass

    def _hud_profile_config_path(self):
        return Path(__file__).resolve().parent / HUD_PROFILE_FILE

    def _screen_height_for_profile_safety(self):
        try:
            screen = QGuiApplication.primaryScreen()
            if not screen:
                return 0
            return int(screen.availableGeometry().height())
        except Exception:
            return 0

    def _use_1080p_safe_startup_profile(self):
        # Public release safety: 1440p layouts can push panels toward the edge on
        # 1080p displays. On low-height screens, start in the dedicated 1080P STREAM
        # profile so users can see the HUD and still switch profiles with Ctrl+F9.
        h = self._screen_height_for_profile_safety()
        return 0 < h < 1200

    def _load_hud_profile_config(self):
        path = self._hud_profile_config_path()
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                profile = str(data.get("hud_profile", self.hud_profile))
                if profile in HUD_PROFILE_VISIBILITY:
                    self.hud_profile = profile
        except Exception as e:
            print(f"HUD PROFILE CONFIG ERROR: {e}")

        if self._use_1080p_safe_startup_profile() and not str(self.hud_profile).startswith("1080P"):
            self.hud_profile = "1080P STREAM"
            print("Screen safety: low-height display detected; starting in 1080P STREAM profile.")

        self._apply_hud_profile(show_notice=False, save=False)

    def _save_hud_profile_config(self):
        path = self._hud_profile_config_path()
        try:
            path.write_text(json.dumps({"hud_profile": self.hud_profile}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"HUD PROFILE SAVE ERROR: {e}")

    def _apply_hud_profile(self, show_notice=True, save=True):
        self.hud_visible = True
        self.panel_visibility.update(HUD_PROFILE_VISIBILITY.get(self.hud_profile, HUD_PROFILE_VISIBILITY["1440P STREAM"]))
        if save:
            self._save_hud_profile_config()
        if show_notice:
            self._show_control_notice(f"PROFILE: {self.hud_profile}", 1.85)

    def _cycle_hud_profile(self):
        try:
            idx = HUD_PROFILE_ORDER.index(self.hud_profile)
        except ValueError:
            idx = 0
        self.hud_profile = HUD_PROFILE_ORDER[(idx + 1) % len(HUD_PROFILE_ORDER)]
        self._apply_hud_profile(show_notice=True, save=True)

    def _show_hud_profile(self):
        self._show_control_notice(f"PROFILE: {self.hud_profile}", 1.85)

    def _toggle_key_help(self):
        now = time.monotonic()
        if self.key_help_visible and now < self.key_help_until:
            self.key_help_visible = False
            self.key_help_until = 0.0
            self._show_control_notice("KEY LIST OFF", 0.95)
        else:
            self.key_help_visible = True
            self.key_help_until = now + 10.0
            self._show_control_notice("KEY LIST", 0.95)
        self.update()

    def draw_key_help(self, painter):
        if not self.key_help_visible:
            return
        now = time.monotonic()
        if now >= self.key_help_until:
            self.key_help_visible = False
            return

        remain = self.key_help_until - now
        fade = clamp(remain / 0.45, 0.0, 1.0)
        alpha = int(232 * fade)
        W = self.width()
        H = self.height()
        box_w = 500
        box_h = 368
        x = W * 0.5 - box_w * 0.5
        y = H * 0.5 - box_h * 0.5

        rows = [
            ("Ctrl + F1",  "HUD ALL ON/OFF"),
            ("Ctrl + F2",  "CAR STATUS ON/OFF"),
            ("Ctrl + F3",  "TRACK MAP ON/OFF"),
            ("Ctrl + F4",  "G TELEMETRY ON/OFF"),
            ("Ctrl + F5",  "WHEEL / COUNTER ON/OFF"),
            ("Ctrl + F6",  "INPUT / CAR INFO ON/OFF"),
            ("Ctrl + F9",  "HUD PROFILE NEXT"),
            ("Ctrl + F10", "SHOW CURRENT PROFILE"),
            ("Ctrl + F11", "HELP / KEY LIST"),
            ("Ctrl + F12", "TRACK MAP RESET"),
            ("Ctrl + Shift + L", "TRACK MAP RESET"),
            ("Ctrl + Shift + Q", "EXIT HUD"),
            ("Alt + Drag", "MOVE PANEL"),
        ]

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        panel = QRectF(x, y, box_w, box_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(2, 7, 12, int(alpha * 0.78)))
        painter.drawRoundedRect(panel, 12, 12)

        edge = QColor(STREET_MINT)
        edge.setAlpha(int(alpha * 0.70))
        painter.setPen(QPen(edge, 1.45, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawRoundedRect(panel.adjusted(1.0, 1.0, -1.0, -1.0), 12, 12)

        accent = QColor(STREET_AMBER)
        accent.setAlpha(int(alpha * 0.86))
        painter.setPen(QPen(accent, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(x + 24, y + 52), QPointF(x + 178, y + 48))
        painter.drawLine(QPointF(x + box_w - 132, y + box_h - 32), QPointF(x + box_w - 24, y + box_h - 36))

        painter.setFont(QFont("Arial Black", 18))
        painter.setPen(QColor(250, 253, 255, alpha))
        painter.drawText(QRectF(x + 24, y + 16, box_w - 48, 28), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "093 HUD KEY LIST")

        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        painter.setPen(QColor(STREET_MINT.red(), STREET_MINT.green(), STREET_MINT.blue(), int(alpha * 0.72)))
        painter.drawText(QRectF(x + box_w - 170, y + 22, 144, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "CTRL + F11 TO CLOSE")

        row_y = y + 72
        key_w = 150
        for i, (key_text, desc) in enumerate(rows):
            yy = row_y + i * 22
            if i % 2 == 0:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, int(alpha * 0.035)))
                painter.drawRoundedRect(QRectF(x + 18, yy - 1, box_w - 36, 20), 5, 5)

            painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
            painter.setPen(QColor(STREET_AMBER.red(), STREET_AMBER.green(), STREET_AMBER.blue(), int(alpha * 0.94)))
            painter.drawText(QRectF(x + 30, yy, key_w, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, key_text)

            painter.setFont(QFont("Bahnschrift", 10, QFont.Weight.Bold))
            painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), int(alpha * 0.90)))
            painter.drawText(QRectF(x + 192, yy, box_w - 222, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, desc)

        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), int(alpha * 0.54)))
        painter.drawText(QRectF(x + 24, y + box_h - 24, box_w - 48, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "AUTO CLOSE: 10 SEC")

        painter.restore()

    def _poll_global_hotkeys(self):
        # Windows virtual-key codes:
        # F1-F12 = 0x70-0x7B. Q = 0x51.
        # Polling works even when FH6 has focus.
        if self._global_combo_pressed_once("CTRL_SHIFT_Q_EXIT", 0x51, require_shift=True):
            self._exit_hud()
            return

        hotkeys = [
            ("CTRL_F1", 0x70, lambda: self._toggle_all_hud()),
            ("CTRL_F2", 0x71, lambda: self._toggle_panel_visibility("left", "CAR STATUS")),
            ("CTRL_F3", 0x72, lambda: self._toggle_panel_visibility("map", "TRACK MAP")),
            ("CTRL_F4", 0x73, lambda: self._toggle_panel_visibility("g_meter", "G TELEMETRY")),
            ("CTRL_F5", 0x74, lambda: self._toggle_panel_visibility("steer", "WHEEL / COUNTER")),
            ("CTRL_F6", 0x75, lambda: self._toggle_panel_visibility("input_car", "INPUT / CAR")),
            ("CTRL_F9", 0x78, self._cycle_hud_profile),
            ("CTRL_F10", 0x79, self._show_hud_profile),
            ("CTRL_F11", 0x7A, self._toggle_key_help),
            ("CTRL_F12", 0x7B, self._reset_live_map),
        ]
        for name, vk, action in hotkeys:
            if self._global_combo_pressed_once(name, vk):
                action()
                return

    def _toggle_all_hud(self):
        self.hud_visible = not self.hud_visible
        self._show_control_notice(self._visibility_text("HUD ALL", self.hud_visible))

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        if ctrl and shift and key == Qt.Key.Key_Q:
            self._exit_hud()
            return

        # LIVE164 visibility / operation controls.
        if ctrl and key == Qt.Key.Key_F1:
            self._toggle_all_hud()
            return

        if ctrl and key == Qt.Key.Key_F2:
            self._toggle_panel_visibility("left", "CAR STATUS")
            return

        if ctrl and key == Qt.Key.Key_F3:
            self._toggle_panel_visibility("map", "TRACK MAP")
            return

        if ctrl and key == Qt.Key.Key_F4:
            self._toggle_panel_visibility("g_meter", "G TELEMETRY")
            return

        if ctrl and key == Qt.Key.Key_F5:
            self._toggle_panel_visibility("steer", "WHEEL / COUNTER")
            return

        if ctrl and key == Qt.Key.Key_F6:
            self._toggle_panel_visibility("input_car", "INPUT / CAR")
            return

        if ctrl and key == Qt.Key.Key_F9:
            self._cycle_hud_profile()
            return

        if ctrl and key == Qt.Key.Key_F10:
            self._show_hud_profile()
            return

        if ctrl and key == Qt.Key.Key_F11:
            self._toggle_key_help()
            return

        if ctrl and key == Qt.Key.Key_F12:
            self._reset_live_map()
            return

        if key == Qt.Key.Key_Escape:
            self._exit_hud()
            return

        if key == Qt.Key.Key_Space:
            self.demo_mode = not self.demo_mode
            return

        if key == Qt.Key.Key_R:
            self.hold_seconds = 0.0
            self.angle = 0.0
            self.display_angle = 0.0
            self.demo_phase = 0.0
            self.update()
            return

        # Keep old reset shortcut too.
        if key == Qt.Key.Key_L and ctrl and shift:
            self._reset_live_map()
            return

        if key == Qt.Key.Key_Left:
            self.demo_mode = True
            self.angle = clamp(self.angle - 5, -90, 90)
            self.display_angle = self.angle
            self.update()
            return

        if key == Qt.Key.Key_Right:
            self.demo_mode = True
            self.angle = clamp(self.angle + 5, -90, 90)
            self.display_angle = self.angle
            self.update()
            return

        if key == Qt.Key.Key_0:
            self.demo_mode = False
            self.angle = 0
            self.display_angle = 0
            self.update()
            return


    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            local = event.position()
            mods = event.modifiers()
            if mods & Qt.KeyboardModifier.AltModifier:
                if self.steer_panel_rect().contains(local):
                    self.drag_mode = "widget"
                    self.drag_widget = "steer_panel"
                elif self.input_group_rect().contains(local):
                    self.drag_mode = "widget"
                    self.drag_widget = "input"
                elif self.vehicle_info_rect().contains(local):
                    self.drag_mode = "widget"
                    self.drag_widget = "vehicle_info"
                elif self.drift_panel_rect().contains(local):
                    self.drag_mode = "widget"
                    self.drag_widget = "drift_panel"
                elif self.style_panel_rect().contains(local):
                    self.drag_mode = "widget"
                    self.drag_widget = "style_panel"
                elif self.map_panel_rect().contains(local):
                    self.drag_mode = "widget"
                    self.drag_widget = "map_panel"
                elif self.operation_popup_panel_rect().contains(local):
                    self.drag_mode = "widget"
                    self.drag_widget = "operation_popup_panel"
                elif self.popup_panel_rect().contains(local):
                    self.drag_mode = "widget"
                    self.drag_widget = "popup_panel"
                elif self.g_meter_rect().contains(local):
                    self.drag_mode = "widget"
                    self.drag_widget = "g_meter"
                if self.drag_mode == "widget":
                    self.drag_origin = event.globalPosition().toPoint()
                    self.drag_widget_origin = list(self.widget_offsets[self.drag_widget])
                    event.accept()
                    return

            self.drag_mode = "window"
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if self.drag_mode == "widget" and self.drag_widget is not None:
            delta = event.globalPosition().toPoint() - self.drag_origin
            self.widget_offsets[self.drag_widget] = [
                self.drag_widget_origin[0] + delta.x(),
                self.drag_widget_origin[1] + delta.y(),
            ]
            self.update()
            event.accept()
            return
        if self.drag_mode == "window" and self.drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if self.drag_mode == "widget":
            self._save_layout_config()
        self.drag_mode = None
        self.drag_widget = None
        self.drag_origin = None
        self.drag_widget_origin = None
        self.drag_pos = None

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self.resize(int(self.width() * 1.04), int(self.height() * 1.04))
        elif delta < 0:
            self.resize(max(980, int(self.width() * 0.96)), max(360, int(self.height() * 0.96)))
        self.update()

    def _is_1080p_profile(self):
        return str(getattr(self, "hud_profile", "")).startswith("1080P")

    def _profile_metric(self, name, default_value):
        """Profile-specific geometry tuning. 1080p uses dedicated panel sizes, not global scaling."""
        if not self._is_1080p_profile():
            return default_value
        metrics = {
            "angle_half_width_factor": 0.150,
            "angle_half_width_max": 318.0,
            "angle_rise_factor": 0.048,
            "angle_rise_max": 46.0,
            "angle_cy_factor": 0.876,
            "angle_bottom_pad": 42.0,
            "map_w_factor": 0.86,
            "map_h_factor": 0.84,
            "g_w_factor": 0.86,
            "g_h_factor": 0.84,
            "drift_w_factor": 0.88,
            "drift_h_factor": 0.88,
            "steer_w_factor": 0.92,
            "steer_h_factor": 0.92,
            "popup_w_factor": 0.92,
            "popup_h_factor": 0.92,
            "op_popup_w_factor": 0.92,
            "op_popup_h_factor": 0.92,
            "right_margin": 26,
        }
        return metrics.get(name, default_value)


    def _layout(self):
        w = self.width()
        h = self.height()
        # Profile-aware ANGLE geometry. 1080p gets a dedicated compact arc instead of global scaling.
        half_width = min(w * self._profile_metric("angle_half_width_factor", 0.164),
                         self._profile_metric("angle_half_width_max", 362.0))
        rise = min(h * self._profile_metric("angle_rise_factor", 0.0496),
                   self._profile_metric("angle_rise_max", 52.8))
        return GaugeLayout(
            cx=w * 0.50,
            cy=min(h * self._profile_metric("angle_cy_factor", 0.882), h - rise - self._profile_metric("angle_bottom_pad", 44.0)),
            half_width=half_width,
            rise=rise,
        )

    def curve_point(self, t, layout):
        # Shallow U arc: the middle sits lowest, sides lift gently.
        x = layout.cx + t * layout.half_width
        y = layout.cy + layout.rise * (1.0 - (t * t))
        return QPointF(x, y)

    def upper_curve_point(self, t, layout, offset=34.0):
        # Secondary guide curve used for LEFT/RIGHT colored guide lines.
        x = layout.cx + t * (layout.half_width * 0.72)
        y = (layout.cy - offset) + (layout.rise * 0.48) * (1.0 - (t * t))
        return QPointF(x, y)

    def curve_path(self, t0, t1, steps=90):
        layout = self._layout()
        t0 = clamp(t0, -1.0, 1.0)
        t1 = clamp(t1, -1.0, 1.0)
        path = QPainterPath()

        for i in range(steps + 1):
            u = i / steps
            t = lerp(t0, t1, u)
            p = self.curve_point(t, layout)
            if i == 0:
                path.moveTo(p)
            else:
                path.lineTo(p)

        return path

    def tangent_and_normal(self, t, layout):
        eps = 0.01
        p0 = self.curve_point(clamp(t - eps, -1.0, 1.0), layout)
        p1 = self.curve_point(clamp(t + eps, -1.0, 1.0), layout)
        tx = p1.x() - p0.x()
        ty = p1.y() - p0.y()
        length = math.hypot(tx, ty) or 1.0
        tx /= length
        ty /= length

        nx1, ny1 = -ty, tx
        nx2, ny2 = ty, -tx
        if ny1 > ny2:
            return (tx, ty), (nx1, ny1)
        return (tx, ty), (nx2, ny2)



    def draw_angle_corner_frame(self, painter):
        layout = self._layout()
        x0 = layout.cx - layout.half_width - 64
        x1 = layout.cx + layout.half_width + 64
        y0 = layout.cy - layout.rise - 88
        y1 = layout.cy + 124

        # Barely-there glass plate only around the angle module.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(4, 9, 15, 38))
        painter.drawRoundedRect(QRectF(x0 + 12, y0 + 10, (x1 - x0) - 24, (y1 - y0) - 20), 18, 18)

        frame_col = QColor(235, 248, 255, 118)
        mint = QColor(STREET_MINT); mint.setAlpha(122)
        amber = QColor(STREET_AMBER); amber.setAlpha(106)

        painter.setPen(QPen(frame_col, 1.25, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        # Open corner brackets, not a full box.
        l = 54
        painter.drawLine(QPointF(x0, y0 + 18), QPointF(x0, y0 + l))
        painter.drawLine(QPointF(x0 + 18, y0), QPointF(x0 + l, y0))
        painter.drawLine(QPointF(x1 - l, y0), QPointF(x1 - 18, y0))
        painter.drawLine(QPointF(x1, y0 + 18), QPointF(x1, y0 + l))
        painter.drawLine(QPointF(x0, y1 - l), QPointF(x0, y1 - 18))
        painter.drawLine(QPointF(x0 + 18, y1), QPointF(x0 + l, y1))
        painter.drawLine(QPointF(x1 - l, y1), QPointF(x1 - 18, y1))
        painter.drawLine(QPointF(x1, y1 - l), QPointF(x1, y1 - 18))

        # Micro UI details: technical, but not noisy.
        painter.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        painter.setPen(QColor(218, 232, 242, 116))
        painter.drawText(QRectF(x0 + 22, y0 + 21, 150, 12), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "093 / EDGE TRACE")
        painter.setPen(QPen(mint, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(x0 + 22, y0 + 38), QPointF(x0 + 42, y0 + 38))
        painter.setPen(QPen(QColor(235, 248, 255, 75), 0.85, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(x0 + 50, y0 + 38), QPointF(x0 + 136, y0 + 38))
        painter.drawLine(QPointF(x0 + 146, y0 + 38), QPointF(x0 + 156, y0 + 38))
        painter.setPen(amber)
        painter.drawPoint(QPointF(x1 - 4, y1 - 7))
        painter.setPen(QColor(218, 232, 242, 78))
        painter.drawText(QRectF(x0 + 2, y1 + 13, 110, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "CALIB. 1.02")
        painter.drawText(QRectF(x1 - 100, y1 + 13, 98, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "UNIT : DEG")


    def draw_segmented_arc(self, painter):
        layout = self._layout()
        segments = 80
        abs_angle = abs(self.display_angle)
        active_t = clamp(abs_angle / 60.0, 0.0, 1.0)
        signed_t = active_t if self.display_angle >= 0 else -active_t
        angle_gain = max(0.0, abs_angle - self.prev_angle_abs)
        rise_energy = clamp(angle_gain / 2.4, 0.0, 1.0)
        base_dim = 0.52 + 0.58 * rise_energy
        active_energy = 0.12 + 0.88 * rise_energy

        def zone_metrics(norm_abs):
            # Quieter at low angle, then grows from ~25deg, with a strong 45deg+ zone.
            if norm_abs >= 0.95:  # 57deg+
                return {
                    "base_h": 21.6,
                    "base_w": 5.0,
                    "base_alpha": 88,
                    "active_h": 32.0,
                    "active_w": 5.6,
                    "active_alpha": 255,
                }
            if norm_abs >= 0.68:  # 41deg+
                return {
                    "base_h": 18.8,
                    "base_w": 4.55,
                    "base_alpha": 76,
                    "active_h": 28.8,
                    "active_w": 5.05,
                    "active_alpha": 252,
                }
            if norm_abs >= 0.42:  # 25deg+
                return {
                    "base_h": 15.4,
                    "base_w": 3.9,
                    "base_alpha": 62,
                    "active_h": 23.6,
                    "active_w": 4.45,
                    "active_alpha": 244,
                }
            return {
                "base_h": 12.4,
                "base_w": 3.25,
                "base_alpha": 44,
                "active_h": 18.8,
                "active_w": 3.9,
                "active_alpha": 230,
            }

        def draw_bar(center_x, base_y, bar_h, bar_w, color, active=False, center=False, limit=False, tip_level=0, energy=0.0):
            rect = QRectF(center_x - bar_w * 0.5, base_y - bar_h, bar_w, bar_h)
            if active:
                if tip_level >= 2:
                    glow_passes = ((18.0, 18), (13.2, 36), (8.8, 62), (5.4, 98)) if limit else ((16.0, 14), (11.8, 30), (7.8, 56), (4.8, 92))
                elif tip_level == 1:
                    glow_passes = ((15.0, 13), (10.8, 28), (7.0, 50), (4.4, 84)) if limit else ((13.6, 11), (9.7, 25), (6.4, 46), (4.0, 78))
                else:
                    glow_passes = ((14.0, 12), (10.0, 26), (6.6, 46), (4.2, 80)) if limit else ((12.0, 10), (8.5, 22), (5.8, 42), (3.8, 74))
                glow_gain = 1.0 + 0.38 * energy + (0.10 if tip_level >= 1 else 0.0)
                for inflate, alpha in glow_passes:
                    glow = QColor(color)
                    glow.setAlpha(int(clamp(alpha * (1.0 + 0.34 * energy), 0, 255)))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(glow)
                    painter.drawRoundedRect(
                        QRectF(rect.x() - (inflate * glow_gain) * 0.20, rect.y() - (inflate * glow_gain) * 0.34,
                               rect.width() + (inflate * glow_gain) * 0.40, rect.height() + (inflate * glow_gain) * 0.68),
                        1.95, 1.95)
            elif center:
                for inflate, alpha in ((4.0, 26), (2.5, 52)):
                    glow = QColor(color)
                    glow.setAlpha(alpha)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(glow)
                    painter.drawRoundedRect(
                        QRectF(rect.x() - inflate * 0.18, rect.y() - inflate * 0.28,
                               rect.width() + inflate * 0.36, rect.height() + inflate * 0.56),
                        1.15, 1.15)
            else:
                glow = QColor(color)
                glow.setAlpha(12)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glow)
                painter.drawRoundedRect(QRectF(rect.x() - 0.25, rect.y() - 0.5, rect.width() + 0.5, rect.height() + 1.0), 0.9, 0.9)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 1.0, 1.0)
            if active or center:
                hi_alpha = 92 if tip_level >= 2 else 80 if tip_level == 1 else 72 if active else 48
                painter.setBrush(QColor(255, 255, 255, hi_alpha))
                painter.drawRoundedRect(QRectF(rect.x() + 0.35, rect.y() + 0.55, max(1.0, rect.width() - 0.7), max(1.4, rect.height() * 0.28)), 0.9, 0.9)

        # Base arc: keep low-angle quiet and let the outer arc gradually build presence.
        for i in range(segments + 1):
            t = -1.0 + 2.0 * i / segments
            p = self.curve_point(t, layout)
            norm_abs = abs(t)
            metrics = zone_metrics(norm_abs)
            edge_boost = 1.0 + max(0.0, norm_abs - 0.42) * 0.12
            alt_scale = 1.0 if (i % 2 == 0) else (0.72 if norm_abs < 0.42 else 0.80 if norm_abs < 0.68 else 0.86)
            if abs(t) < 0.012:
                draw_bar(p.x(), p.y(), 27.0, 4.6, QColor(252, 252, 255, 132), active=False, center=True)
            else:
                alpha_bias = 4 if norm_abs >= 0.68 else 0
                base_alpha = int(clamp((metrics["base_alpha"] + 18 + alpha_bias) * base_dim, 18, 170))
                base_color = QColor(118, 240, 255, base_alpha) if t < 0 else QColor(255, 104, 142, base_alpha)
                draw_bar(
                    p.x(),
                    p.y(),
                    metrics["base_h"] * edge_boost * alt_scale,
                    metrics["base_w"],
                    base_color,
                    active=False,
                    energy=0.0,
                )

        # Active portion from the center outward. 45deg+ and the final tip get the strongest treatment.
        if abs_angle > 0.08:
            tip_width = 1.0 / segments
            for i in range(segments + 1):
                t = -1.0 + 2.0 * i / segments
                p = self.curve_point(t, layout)
                norm_abs = abs(t)
                metrics = zone_metrics(norm_abs)
                if signed_t >= 0:
                    on = 0.0 <= t <= signed_t + tip_width
                    hot_alpha = int(clamp(metrics["active_alpha"] + 12 + 36 * active_energy, 0, 255))
                    color = QColor(255, 86 + int(10 * active_energy), 130 + int(12 * active_energy), hot_alpha)
                else:
                    on = signed_t - tip_width <= t <= 0.0
                    hot_alpha = int(clamp(metrics["active_alpha"] + 12 + 36 * active_energy, 0, 255))
                    color = QColor(88 + int(8 * active_energy), 238 + int(10 * active_energy), 255, hot_alpha)
                if on:
                    dist_to_tip = abs(t - signed_t)
                    tip_level = 2 if dist_to_tip <= tip_width * 0.9 else 1 if dist_to_tip <= tip_width * 2.1 else 0
                    active_h = metrics["active_h"] * (1.0 if (i % 2 == 0) else 0.82)
                    active_w = metrics["active_w"]
                    active_h *= 1.0 + 0.18 * active_energy
                    active_w += 0.10 * active_energy
                    if tip_level == 1:
                        active_h *= 1.08
                        active_w += 0.14
                    elif tip_level >= 2:
                        active_h *= 1.22
                        active_w += 0.34
                        color = QColor(min(255, color.red() + 16), min(255, color.green() + 16), min(255, color.blue() + 16), min(255, color.alpha() + 8))
                    draw_bar(p.x(), p.y(), active_h, active_w, color, active=True, limit=(norm_abs >= 0.95), tip_level=tip_level, energy=active_energy)


    def draw_curve_ticks(self, painter):
        layout = self._layout()
        # Keep the hierarchy, but balance each vertical marker against the surrounding segment heights.
        tick_values = sorted(set(list(range(-60, 61, 10)) + [-45, 45]))

        for value in tick_values:
            t = value / 60.0
            p = self.curve_point(t, layout)
            abs_value = abs(value)

            if value == 0:
                tick_h = 27.0
                width = 3.1
                glow_alpha = 82
                extra_glow = 4.0
                core_color = QColor(255, 255, 255, 234)
            elif abs_value == 60:
                tick_h = 21.6
                width = 2.6
                glow_alpha = 84
                extra_glow = 4.0
                core_color = QColor(58, 220, 255, 236) if value < 0 else QColor(255, 92, 190, 236)
            elif abs_value == 45:
                tick_h = 18.8
                width = 2.3
                glow_alpha = 72
                extra_glow = 3.7
                core_color = QColor(100, 236, 255, 232) if value < 0 else QColor(255, 138, 178, 232)
            elif abs_value == 40:
                tick_h = 16.2
                width = 1.95
                glow_alpha = 50
                extra_glow = 2.9
                core_color = QColor(74, 216, 248, 218) if value < 0 else QColor(255, 108, 164, 218)
            elif abs_value == 30:
                tick_h = 15.0
                width = 1.78
                glow_alpha = 40
                extra_glow = 2.45
                core_color = QColor(142, 208, 224, 186) if value < 0 else QColor(236, 180, 208, 186)
            elif abs_value == 20:
                tick_h = 13.2
                width = 1.5
                glow_alpha = 32
                extra_glow = 2.0
                core_color = QColor(148, 196, 210, 154) if value < 0 else QColor(228, 174, 198, 154)
            else:  # 10deg minor
                tick_h = 9.4
                width = 1.0
                glow_alpha = 16
                extra_glow = 1.4
                core_color = QColor(184, 214, 224, 88) if value < 0 else QColor(230, 188, 208, 88)

            # Match the segment bars: same baseline, no extra tail below the segment row.
            p1 = QPointF(p.x(), p.y() - tick_h)
            p2 = QPointF(p.x(), p.y())
            glow = QColor(core_color)
            glow.setAlpha(int(clamp(glow_alpha, 0, 255)))
            painter.setPen(QPen(glow, width + extra_glow, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(p1, p2)
            painter.setPen(QPen(core_color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(p1, p2)
    def draw_angle_labels(self, painter):
        layout = self._layout()
        painter.setFont(QFont("Bahnschrift", 13, QFont.Weight.Bold))

        for value in (-60, -40, -20, 0, 20, 40, 60):
            t = value / 60.0
            p = self.curve_point(t, layout)
            label = f"{value}°" if value != 0 else "0°"
            box_w = 54 if abs(value) == 60 else 46 if value != 0 else 38
            pos_y = p.y() + 26
            painter.setPen(QColor(255, 255, 255, 236))
            painter.drawText(QRectF(p.x() - box_w / 2, pos_y, box_w, 22), Qt.AlignmentFlag.AlignCenter, label)
    def draw_glow_path(self, painter, path, color, width):
        for mul, alpha in [(4.2, 24), (2.7, 42), (1.7, 70)]:
            c = QColor(color)
            c.setAlpha(alpha)
            pen = QPen(c, width * mul)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(path)

        main = QColor(color)
        main.setAlpha(238)
        pen = QPen(main, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)

        hi = QColor(255, 255, 255, 150)
        pen = QPen(hi, max(1.5, width * 0.22))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawPath(path)


    def draw_triangle_marker(self, painter, tip, t, layout):
        (tx, ty), (nx, ny) = self.tangent_and_normal(t, layout)
        # Stronger directional marker: larger, accented glow, then crisp white core.
        center = QPointF(tip.x() + nx * 19.0, tip.y() + ny * 19.0)
        accent = QColor(255, 108, 142, 220) if t >= 0 else QColor(118, 240, 255, 220)

        def triangle_points(apex_len, base_len, half_width):
            apex = QPointF(center.x() - nx * apex_len, center.y() - ny * apex_len)
            base_center = QPointF(center.x() + nx * base_len, center.y() + ny * base_len)
            left = QPointF(base_center.x() - tx * half_width, base_center.y() - ty * half_width)
            right = QPointF(base_center.x() + tx * half_width, base_center.y() + ty * half_width)
            return QPolygonF([apex, left, right])

        shadow = triangle_points(18.5, 11.8, 15.0)
        shadow.translate(1.6, 1.8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 138))
        painter.drawPolygon(shadow)

        for apex_len, base_len, half_width, alpha in (
            (18.6, 11.8, 15.0, 42),
            (17.2, 10.8, 13.7, 92),
        ):
            glow = QColor(accent)
            glow.setAlpha(alpha)
            painter.setBrush(glow)
            painter.drawPolygon(triangle_points(apex_len, base_len, half_width))

        painter.setPen(QPen(QColor(18, 22, 28, 206), 1.1))
        painter.setBrush(QColor(255, 255, 255, 252))
        painter.drawPolygon(triangle_points(16.2, 9.8, 12.6))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 118))
        painter.drawPolygon(triangle_points(11.5, 7.1, 8.1))

    def vehicle_info_geometry(self):
        # All frame widths shortened by about 5% while keeping the right edge aligned.
        map_w = int(456 * 0.80 * 0.95)
        w = map_w
        h = 187
        x = self.width() - w - 38
        y = 34
        dx, dy = self.widget_offsets.get("vehicle_info", [0.0, 0.0])
        return x + dx, y + dy, w, h

    def input_group_geometry(self):
        # Default INPUT position: a little to the left of the HOLD area,
        # near the angle gauge instead of high on the screen.
        layout = self._layout()
        hold_anchor = self.curve_point(-0.96, layout)
        w = int(154 * 0.95)
        h = 206
        x = hold_anchor.x() - w - 26
        y = hold_anchor.y() - 102
        dx, dy = self.widget_offsets.get("input", [0.0, 0.0])
        return x + dx, y + dy, w, h

    def steer_panel_geometry(self):
        # No-frame mini WHEEL / COUNTER panel.
        layout = self._layout()
        hold_anchor = self.curve_point(-0.96, layout)
        input_w = int(154 * 0.95)
        input_h = 206
        iy = hold_anchor.y() - 102

        # Profile-aware WHEEL / COUNTER: 1080p keeps readable bars but uses a tighter shell.
        w = int(342 * self._profile_metric("steer_w_factor", 1.0))
        h = int(76 * self._profile_metric("steer_h_factor", 1.0))

        # LIVE182: horizontally sync the WHEEL / COUNTER zero with the ANGLE gauge zero.
        # draw_steer_panel uses bar_x = x + 82 and bar_w = w - 92,
        # so bar zero is x + 82 + (w - 92) / 2.
        zero_offset_in_panel = 82 + (w - 92) * 0.5
        x = layout.cx - zero_offset_in_panel

        y_under = iy + input_h + 12
        y_above = iy - h - 12
        y = y_under if (y_under + h) <= (self.height() - 10) else y_above
        x = clamp(x, 8, self.width() - w - 8)
        y = clamp(y, 8, self.height() - h - 8)

        # Keep the user's vertical offset, but ignore horizontal offset so the zero line
        # continues to follow the ANGLE gauge zero across profiles/resolutions.
        _dx, dy = self.widget_offsets.get("steer_panel", [0.0, 0.0])
        return x, y + dy, w, h

    def steer_panel_rect(self):
        x, y, w, h = self.steer_panel_geometry()
        return QRectF(x, y, w, h)

    def map_panel_geometry(self):
        # Default initial position aligned to the reference layout screenshot.
        w = int(456 * 0.80 * 0.95 * self._profile_metric("map_w_factor", 1.0))
        h = int(240 * 1.30 * 0.90 * self._profile_metric("map_h_factor", 1.0))
        x = self.width() - w - self._profile_metric("right_margin", 38)
        y = 166
        dx, dy = self.widget_offsets.get("map_panel", [0.0, 0.0])
        return x + dx, y + dy, w, h
    def g_meter_geometry(self):
        # G telemetry is independently placed and independently draggable.
        # It no longer follows TRACK MAP when the map is moved.
        w = int(456 * 0.80 * 0.95 * self._profile_metric("g_w_factor", 1.0))
        h = int(250 * self._profile_metric("g_h_factor", 1.0))
        x = self.width() - w - self._profile_metric("right_margin", 38)
        y = 388
        dx, dy = self.widget_offsets.get("g_meter", [0.0, 0.0])
        return x + dx, y + dy, w, h

    def drift_panel_geometry(self):
        # Default initial position aligned to the reference layout screenshot.
        w = int(360 * 0.95 * self._profile_metric("drift_w_factor", 1.0))
        h = int(270 * self._profile_metric("drift_h_factor", 1.0))
        x = self.width() - w - self._profile_metric("right_margin", 38)
        y = 646
        dx, dy = self.widget_offsets.get("drift_panel", [0.0, 0.0])
        return x + dx, y + dy, w, h

    def style_panel_geometry(self):
        w = int(360 * 0.95)
        x = self.width() - w - 50
        y = 386
        h = 178
        dx, dy = self.widget_offsets.get("style_panel", [0.0, 0.0])
        return x + dx, y + dy, w, h

    def popup_panel_geometry(self):
        w = int(430 * 0.95 * self._profile_metric("popup_w_factor", 1.0))
        h = int(118 * self._profile_metric("popup_h_factor", 1.0))
        x = (self.width() - w) * 0.5
        y = 34
        dx, dy = self.widget_offsets.get("popup_panel", [0.0, 0.0])
        return x + dx, y + dy, w, h

    def operation_popup_panel_geometry(self):
        # Separate draggable text-only operation popup for pedal / handbrake actions.
        # Default is slightly below the main popup so both can be read at once.
        w = int(430 * 0.95 * self._profile_metric("op_popup_w_factor", 1.0))
        h = int(96 * self._profile_metric("op_popup_h_factor", 1.0))
        x = (self.width() - w) * 0.5
        y = 86
        dx, dy = self.widget_offsets.get("operation_popup_panel", [0.0, 0.0])
        return x + dx, y + dy, w, h

    def draw_reference_panel(self, painter, x, y, w, h, title=None, accent=None, alpha=34):
        """CAR INFO-style reference frame reused across panels.
        Cyan/white only, layered glass, complex corners, dedicated title treatment,
        and uneven glow hotspots.
        """
        cyan = QColor(46, 232, 255) if accent is None else QColor(accent)
        white = QColor(246, 252, 255)

        pts = [
            QPointF(x + 18, y + 0),
            QPointF(x + w - 28, y + 0),
            QPointF(x + w - 10, y + 14),
            QPointF(x + w - 10, y + h - 18),
            QPointF(x + w - 26, y + h),
            QPointF(x + 18, y + h),
            QPointF(x + 0, y + h - 16),
            QPointF(x + 0, y + 16),
        ]
        outer = QPainterPath()
        outer.addPolygon(QPolygonF(pts))
        outer.closeSubpath()

        body = QLinearGradient(x, y, x, y + h)
        body.setColorAt(0.00, QColor(0, 18, 26, min(255, alpha + 48)))
        body.setColorAt(0.20, QColor(0, 12, 18, min(255, alpha + 30)))
        body.setColorAt(0.70, QColor(0, 8, 14, min(255, alpha + 8)))
        body.setColorAt(1.00, QColor(0, 4, 8, max(22, alpha - 2)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(body)
        painter.drawPath(outer)

        sheen = QLinearGradient(x, y, x + w, y + h)
        sheen.setColorAt(0.00, QColor(255, 255, 255, 14))
        sheen.setColorAt(0.18, QColor(255, 255, 255, 0))
        sheen.setColorAt(0.54, QColor(70, 226, 255, 10))
        sheen.setColorAt(1.00, QColor(255, 255, 255, 0))
        painter.setBrush(sheen)
        painter.drawPath(outer)

        painter.save()
        painter.setClipPath(outer)
        painter.setPen(QPen(QColor(95, 228, 255, 11), 1.0))
        sy = y + 14
        while sy < y + h - 12:
            painter.drawLine(QPointF(x + 10, sy), QPointF(x + w - 12, sy))
            sy += 8

        painter.setPen(QPen(QColor(90, 225, 255, 6), 1.0))
        sx = x + 20
        while sx < x + w - 16:
            painter.drawLine(QPointF(sx, y + 22), QPointF(sx, y + h - 14))
            sx += 44

        sep_y = y + min(h - 36, max(56, h * 0.72))
        painter.setPen(QPen(QColor(96, 226, 255, 26), 1.0))
        painter.drawLine(QPointF(x + 14, sep_y), QPointF(x + w - 16, sep_y))
        painter.restore()

        for width, a in [(5.0, 8), (2.5, 20), (1.2, 44)]:
            painter.setPen(QPen(QColor(54, 230, 255, a), width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(outer)
        painter.setPen(QPen(QColor(72, 236, 255, 180), 0.54))
        painter.drawPath(outer)

        ix, iy, iw, ih = x + 6, y + 6, w - 12, h - 12
        ipts = [
            QPointF(ix + 14, iy + 0),
            QPointF(ix + iw - 22, iy + 0),
            QPointF(ix + iw - 6, iy + 12),
            QPointF(ix + iw - 6, iy + ih - 16),
            QPointF(ix + iw - 22, iy + ih),
            QPointF(ix + 14, iy + ih),
            QPointF(ix + 0, iy + ih - 12),
            QPointF(ix + 0, iy + 12),
        ]
        inner = QPainterPath()
        inner.addPolygon(QPolygonF(ipts))
        inner.closeSubpath()
        painter.setPen(QPen(QColor(232, 252, 255, 28), 0.95))
        painter.drawPath(inner)

        if title:
            painter.setFont(QFont('Bahnschrift', 10, QFont.Weight.Bold))
            painter.setPen(QColor(214, 248, 255, 240))
            title_y = y + 6
            painter.drawText(QRectF(x + 18, title_y, max(84, w - 36), 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(title))
            fm = QFontMetrics(QFont('Bahnschrift', 10, QFont.Weight.Bold))
            tw = fm.horizontalAdvance(str(title))
            line_start = min(x + 18 + tw + 10, x + w - 40)
            painter.setPen(QPen(QColor(80, 232, 255, 96), 1.0))
            painter.drawLine(QPointF(line_start, title_y + 9), QPointF(x + w * 0.44 if w > 180 else x + w - 24, title_y + 9))

        detail = [
            (QColor(82, 236, 255, 200), 1.5, x + 6, y + 18, x + 18, y + 6),
            (QColor(82, 236, 255, 200), 1.5, x + 18, y + 6, x + 58, y + 6),
            (QColor(160, 245, 255, 82), 1.0, x + 28, y + 12, x + 72, y + 12),
            (QColor(82, 236, 255, 200), 1.5, x + w - 62, y + 6, x + w - 24, y + 6),
            (QColor(82, 236, 255, 200), 1.5, x + w - 24, y + 6, x + w - 10, y + 18),
            (QColor(160, 245, 255, 82), 1.0, x + w - 76, y + 12, x + w - 34, y + 12),
            (QColor(82, 236, 255, 180), 1.4, x + 6, y + h - 18, x + 18, y + h - 6),
            (QColor(82, 236, 255, 180), 1.4, x + 18, y + h - 6, x + 78, y + h - 6),
            (QColor(160, 245, 255, 70), 1.0, x + 32, y + h - 12, x + 88, y + h - 12),
            (QColor(82, 236, 255, 180), 1.4, x + w - 84, y + h - 6, x + w - 24, y + h - 6),
            (QColor(82, 236, 255, 180), 1.4, x + w - 24, y + h - 6, x + w - 10, y + h - 18),
            (QColor(160, 245, 255, 70), 1.0, x + w - 92, y + h - 12, x + w - 36, y + h - 12),
        ]
        for col, width, x1, y1, x2, y2 in detail:
            painter.setPen(QPen(col, width))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        hotspots = [
            (x + 22, y + 5, x + 78, y + 5),
            (x + w - 88, y + 5, x + w - 28, y + 5),
            (x + 6, y + 28, x + 6, min(y + 88, y + h - 44)),
            (x + w - 4, y + 42, x + w - 4, y + h - 44),
            (x + 22, y + h - 6, x + 78, y + h - 6),
        ]
        for x1, y1, x2, y2 in hotspots:
            painter.setPen(QPen(QColor(70, 235, 255, 26), 3.5))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            painter.setPen(QPen(QColor(70, 235, 255, 112), 0.9))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            painter.setPen(QPen(QColor(255, 255, 255, 72), 0.7))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def draw_clean_spray(self, painter, x, y, color, scale=1.0, alpha=44):
        """Tiny controlled paint flecks.  LIVE117: lighter for readability."""
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        alpha = int(alpha * 0.72)
        scale = scale * 0.88
        for ox, oy, r, mul in [
            (0, 0, 1.55, 1.0), (6, -2, 1.05, 0.72), (10, 3, 0.78, 0.56),
            (-5, 2, 0.92, 0.60), (15, -4, 0.62, 0.42)
        ]:
            c = QColor(color)
            c.setAlpha(max(4, int(alpha * mul)))
            painter.setBrush(c)
            painter.drawEllipse(QPointF(x + ox * scale, y + oy * scale), r * scale, r * scale)
        painter.restore()

    def draw_marker_line(self, painter, x1, y1, x2, y2, color, width=2.4, alpha=150):
        """Short paint-marker stroke used instead of cyber frames. LIVE117: reduced weight."""
        alpha = int(alpha * 0.62)
        width = max(1.0, width * 0.92)
        c = QColor(color)
        c.setAlpha(alpha)
        painter.setPen(QPen(c, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        # small dry-brush echo line
        c2 = QColor(STREET_OFFWHITE)
        c2.setAlpha(max(12, alpha // 5))
        painter.setPen(QPen(c2, max(0.55, width * 0.28), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(x1 + 5, y1 + 3.5), QPointF(x2 - 4, y2 + 2.0))

    def draw_street_label(self, painter, x, y, text, accent=None, max_w=180, compact=True):
        """Small clean street-art title label.

        Labels stay quiet; the accent stroke provides the 093 / Unbound-ish energy.
        """
        accent = QColor(STREET_CORAL if accent is None else accent)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        fs = 9 if compact else 10
        font = QFont('Bahnschrift', fs, QFont.Weight.Bold)
        painter.setFont(font)
        fm = QFontMetrics(font)
        tw = min(max_w - 8, max(34, fm.horizontalAdvance(str(text)) + 10))
        # Tiny black backing directly behind the title only; keeps text readable
        # without turning it into a large logo/image.
        back = QColor(0, 0, 0, 48)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(back)
        painter.drawRoundedRect(QRectF(x - 3, y + 1, tw + 10, 14), 3, 3)
        painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), STREET_LABEL_ALPHA))
        painter.drawText(QRectF(x, y, max_w, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(text))
        self.draw_marker_line(painter, x - 2, y + 17, x + tw, y + 14, accent, 2.6 if compact else 3.2, 162)
        # small terminal dash: reads as hand-marker, not a splash asset
        dash = QColor(accent)
        dash.setAlpha(90)
        painter.setPen(QPen(dash, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(x + tw + 4, y + 9), QPointF(x + tw + 15, y + 7))
        self.draw_clean_spray(painter, x + tw + 18, y + 10, accent, 0.52, 18)
        painter.restore()

    def draw_halftone_dots(self, painter, x, y, color, rows=4, cols=5, spacing=5.0, radius=1.15, alpha=34):
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        alpha = int(alpha * 0.62)
        radius = radius * 0.90
        for r in range(rows):
            for c in range(cols):
                col = QColor(color)
                col.setAlpha(max(4, int(alpha * (1.0 - 0.08 * r - 0.05 * c))))
                painter.setBrush(col)
                painter.drawEllipse(QPointF(x + c * spacing, y + r * spacing), radius, radius)
        painter.restore()

    def draw_graffiti_arrow(self, painter, x1, y1, x2, y2, color, width=1.7, alpha=86):
        painter.save()
        alpha = int(alpha * 0.68)
        width = max(0.9, width * 0.90)
        c = QColor(color)
        c.setAlpha(alpha)
        painter.setPen(QPen(c, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        dx = x2 - x1
        dy = y2 - y1
        ln = max(1.0, (dx * dx + dy * dy) ** 0.5)
        ux, uy = dx / ln, dy / ln
        head = max(6.0, width * 3.4)
        lx = x2 - ux * head - uy * head * 0.55
        ly = y2 - uy * head + ux * head * 0.55
        rx = x2 - ux * head + uy * head * 0.55
        ry = y2 - uy * head - ux * head * 0.55
        painter.drawLine(QPointF(x2, y2), QPointF(lx, ly))
        painter.drawLine(QPointF(x2, y2), QPointF(rx, ry))
        painter.restore()

    def draw_graffiti_cross(self, painter, x, y, color, scale=0.8, alpha=70):
        painter.save()
        alpha = int(alpha * 0.62)
        scale = scale * 0.84
        c = QColor(color)
        c.setAlpha(alpha)
        painter.setPen(QPen(c, max(0.75, 1.1 * scale), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        s = 4.0 * scale
        painter.drawLine(QPointF(x - s, y - s), QPointF(x + s, y + s))
        painter.drawLine(QPointF(x + s, y - s), QPointF(x - s, y + s))
        painter.restore()

    def draw_sticker_slash(self, painter, x, y, w, h, color, alpha=34):
        """Clean pop-street accent shape. LIVE117: lighter so values win."""
        alpha = int(alpha * 0.76)
        c = QColor(color)
        c.setAlpha(alpha)
        path = QPainterPath()
        path.moveTo(x, y + h * 0.25)
        path.lineTo(x + w * 0.86, y)
        path.lineTo(x + w, y + h * 0.62)
        path.lineTo(x + w * 0.14, y + h)
        path.closeSubpath()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c)
        painter.drawPath(path)
        c2 = QColor(STREET_OFFWHITE)
        c2.setAlpha(max(6, alpha // 3))
        painter.setBrush(c2)
        painter.drawEllipse(QPointF(x + w * 0.78, y + h * 0.22), max(1.0, h * 0.11), max(1.0, h * 0.11))
        painter.restore()

    def draw_midnight_street_panel(self, painter, x, y, w, h, title=None, accent=None, alpha=34):
        """LIVE106 clean no-frame base.

        Replaces the LIVE104/105 dirty panel feel with a light, readable backing
        plus small street-art labels.  No hard boxes or cyber neon frames.
        """
        accent = QColor(STREET_CORAL if accent is None else accent)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        panel = QRectF(x + 5, y + 7, max(40.0, w - 10), max(30.0, h - 12))
        haze = QLinearGradient(panel.left(), panel.top(), panel.left(), panel.bottom())
        haze.setColorAt(0.00, QColor(3, 7, 12, clamp(alpha + STREET_HAZE_ALPHA, 42, 104)))
        haze.setColorAt(0.55, QColor(2, 6, 11, clamp(alpha + STREET_HAZE_ALPHA - 4, 34, 86)))
        haze.setColorAt(1.00, QColor(1, 4, 8, clamp(alpha + STREET_HAZE_ALPHA - 10, 26, 70)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(haze)
        painter.drawRoundedRect(panel, 7, 7)

        # LIVE119: code-only street panel accents.  These are small structural
        # marks, not image assets: corner cuts + white marker edge.
        edge = QColor(STREET_OFFWHITE)
        edge.setAlpha(58)
        painter.setPen(QPen(edge, 1.25, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(panel.left() + 12, panel.top() + 3), QPointF(panel.left() + min(84, panel.width() * 0.30), panel.top() + 1))
        painter.drawLine(QPointF(panel.right() - min(82, panel.width() * 0.28), panel.bottom() - 2), QPointF(panel.right() - 12, panel.bottom() - 5))
        cut = QColor(accent)
        cut.setAlpha(78)
        painter.setPen(QPen(cut, 1.65, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(panel.left() + 6, panel.top() + 17), QPointF(panel.left() + 20, panel.top() + 5))
        painter.drawLine(QPointF(panel.right() - 22, panel.bottom() - 5), QPointF(panel.right() - 7, panel.bottom() - 18))

        # Subtle tire/marker texture only near edges; center stays clean.
        painter.save()
        painter.setClipRect(panel.adjusted(0, 0, 0, 0))
        trace = QColor(STREET_OFFWHITE)
        trace.setAlpha(STREET_TRACE_ALPHA)
        painter.setPen(QPen(trace, 1.15, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        by = panel.bottom() - 10
        painter.drawLine(QPointF(panel.left() + 10, by), QPointF(panel.left() + min(panel.width() * 0.34, 116), by - 5))
        painter.drawLine(QPointF(panel.right() - min(panel.width() * 0.30, 104), panel.top() + 13), QPointF(panel.right() - 14, panel.top() + 8))
        painter.restore()

        if title:
            self.draw_street_label(painter, x + 14, y + 4, title, accent, max_w=max(90, int(w - 28)), compact=True)

        painter.restore()

    def draw_cyber_panel(self, painter, x, y, w, h, title=None, accent=None, alpha=34):
        self.draw_midnight_street_panel(painter, x, y, w, h, title, accent, alpha)

    def draw_hbar(self, painter, x, y, w, h, pct, color):
        painter.setPen(QPen(QColor(195, 240, 255, 38), 1.0))
        painter.setBrush(QColor(10, 18, 26, 45))
        painter.drawRoundedRect(QRectF(x, y, w, h), 4, 4)
        fw = (w - 2) * clamp(pct, 0, 100) / 100.0
        if fw > 1:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(with_alpha(color, 70))
            painter.drawRoundedRect(QRectF(x + 1, y + 1, fw, h - 2), 3, 3)
            painter.setBrush(with_alpha(color, 220))
            painter.drawRoundedRect(QRectF(x + 1, y + 1, max(2, fw - 1), h - 2), 3, 3)

    def draw_input_vertical_bar(self, painter, x, y, w, h, pct, label, color):
        pct = clamp(pct, 0.0, 100.0)

        # Requested refinement: keep the same overall bar length, but use finer,
        # thinner stacked segments with a slightly taller feel and a bit more glow.
        painter.setPen(QPen(QColor(200, 240, 255, 54), 1.0))
        painter.setBrush(QColor(10, 18, 26, 18))
        painter.drawRoundedRect(QRectF(x, y, w, h), 3.4, 3.4)

        inner_pad_x = 1.9
        inner_pad_y = 1.4
        ix = x + inner_pad_x
        iy = y + inner_pad_y
        iw = w - inner_pad_x * 2.0
        ih = h - inner_pad_y * 2.0

        seg_count = 16
        seg_gap = 1.15
        seg_h = max(3.1, (ih - seg_gap * (seg_count - 1)) / seg_count)
        filled_height = ih * pct / 100.0

        base = QColor(color)
        inactive_fill = QColor(8, 16, 24, 28)
        inactive_edge = QColor(210, 236, 255, 24)

        for i in range(seg_count):
            seg_bottom = iy + ih - (i + 1) * seg_h - i * seg_gap
            seg_rect = QRectF(ix, seg_bottom, iw, seg_h)

            # inactive segment shell
            painter.setPen(QPen(inactive_edge, 0.75))
            painter.setBrush(inactive_fill)
            painter.drawRoundedRect(seg_rect, 1.2, 1.2)

            # overlap of the continuous fill against this segment
            dist_from_bottom = i * (seg_h + seg_gap)
            seg_fill = max(0.0, min(seg_h, filled_height - dist_from_bottom))
            if seg_fill <= 0.05:
                continue

            fill_rect = QRectF(ix, seg_bottom + (seg_h - seg_fill), iw, seg_fill)
            glow_rect = QRectF(fill_rect.x() - 0.55, fill_rect.y() - 0.55, fill_rect.width() + 1.1, fill_rect.height() + 1.1)

            glow = QColor(base)
            glow.setAlpha(76)
            fill = QColor(base)
            fill.setAlpha(226)
            core = QColor(255, 255, 255, 44)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawRoundedRect(glow_rect, 1.45, 1.45)
            painter.setBrush(fill)
            painter.drawRoundedRect(fill_rect, 1.1, 1.1)

            # slim highlight strip for a slightly more luminous segmented look
            hi_w = max(0.9, iw * 0.18)
            hi_rect = QRectF(fill_rect.x() + 0.5, fill_rect.y() + 0.38, hi_w, max(1.0, fill_rect.height() - 0.76))
            painter.setBrush(core)
            painter.drawRoundedRect(hi_rect, 0.9, 0.9)

        painter.setFont(QFont("Arial Black", 10))
        painter.setPen(QColor(242, 248, 255, 226))
        painter.drawText(QRectF(x - 7, y + h + 4, w + 14, 18), Qt.AlignmentFlag.AlignCenter, label)

    def draw_car_info_frame(self, painter, x, y, w, h):
        # CAR INFO only: one outer frame + decorative lines (no inner box).
        # Adds line-thickness variation, darker dead zones, light scratches,
        # and stronger-but-uneven cyan glow to feel closer to a textured HUD plate.
        pts = [
            QPointF(x + 18, y + 0),
            QPointF(x + w - 30, y + 0),
            QPointF(x + w, y + 18),
            QPointF(x + w, y + h - 18),
            QPointF(x + w - 26, y + h),
            QPointF(x + 18, y + h),
            QPointF(x + 0, y + h - 16),
            QPointF(x + 0, y + 16),
        ]
        outer = QPainterPath()
        outer.addPolygon(QPolygonF(pts))
        outer.closeSubpath()

        # Base glass body.
        body = QLinearGradient(x, y, x, y + h)
        body.setColorAt(0.00, QColor(2, 22, 31, 108))
        body.setColorAt(0.14, QColor(2, 17, 26, 94))
        body.setColorAt(0.48, QColor(1, 11, 18, 76))
        body.setColorAt(0.80, QColor(0, 8, 14, 64))
        body.setColorAt(1.00, QColor(0, 5, 9, 56))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(body)
        painter.drawPath(outer)

        painter.save()
        painter.setClipPath(outer)

        # Uneven atmospheric glow washes.
        washes = []
        g = QLinearGradient(x - 8, y + 4, x + w * 0.55, y + h * 0.32)
        g.setColorAt(0.00, QColor(255, 255, 255, 14))
        g.setColorAt(0.08, QColor(72, 233, 255, 30))
        g.setColorAt(0.16, QColor(188, 248, 255, 12))
        g.setColorAt(0.36, QColor(255, 255, 255, 0))
        g.setColorAt(1.00, QColor(255, 255, 255, 0))
        washes.append(g)
        g = QLinearGradient(x + w * 0.40, y + 10, x + w, y + h * 0.62)
        g.setColorAt(0.00, QColor(255, 255, 255, 0))
        g.setColorAt(0.18, QColor(76, 232, 255, 10))
        g.setColorAt(0.34, QColor(255, 255, 255, 8))
        g.setColorAt(0.58, QColor(56, 224, 255, 5))
        g.setColorAt(1.00, QColor(255, 255, 255, 0))
        washes.append(g)
        g = QLinearGradient(x + 6, y + h * 0.35, x + w * 0.75, y + h)
        g.setColorAt(0.00, QColor(0, 0, 0, 0))
        g.setColorAt(0.22, QColor(58, 228, 255, 8))
        g.setColorAt(0.52, QColor(255, 255, 255, 4))
        g.setColorAt(1.00, QColor(0, 0, 0, 0))
        washes.append(g)
        for wash in washes:
            painter.setBrush(wash)
            painter.drawPath(outer)

        # Sparse vertical raster hints.
        xx = x + 16
        idx = 0
        while xx < x + w - 14:
            a = 8 if idx % 3 == 0 else 4
            painter.setPen(QPen(QColor(90, 224, 255, a), 0.65))
            painter.drawLine(QPointF(xx, y + 20), QPointF(xx, y + h - 16))
            xx += 46
            idx += 1

        def draw_var_segment(x1, y1, x2, y2, core_alpha=90, glow_alpha=18, width=1.0, bright=False):
            # soft glow base
            painter.setPen(QPen(QColor(62, 230, 255, glow_alpha), max(1.4, width * 2.2)))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            # core line with slight brightness variation
            core = QColor(196, 248, 255, core_alpha) if bright else QColor(74, 234, 255, core_alpha)
            painter.setPen(QPen(core, width))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Title section decorative rails / fragments.
        title_segments = [
            (x + 16, y + 12, x + 44, y + 12, 82, 20, 1.15, True),
            (x + 50, y + 12, x + 78, y + 12, 48, 10, 0.9, False),
            (x + 86, y + 12, x + 124, y + 12, 66, 16, 1.0, False),
            (x + 132, y + 12, x + 176, y + 12, 102, 24, 1.25, True),
            (x + w - 128, y + 12, x + w - 94, y + 12, 44, 10, 0.9, False),
            (x + w - 88, y + 12, x + w - 54, y + 12, 92, 22, 1.15, True),
            (x + w - 46, y + 12, x + w - 18, y + 12, 58, 14, 1.0, False),
            (x + 18, y + 28, x + 54, y + 28, 62, 12, 0.95, False),
            (x + 62, y + 28, x + 104, y + 28, 98, 18, 1.1, True),
            (x + 110, y + 28, x + 142, y + 28, 52, 10, 0.85, False),
        ]
        for seg in title_segments:
            draw_var_segment(*seg)

        # Mid decoration / separators, intentionally broken and uneven.
        mid_segments = [
            (x + 20, y + 48, x + 70, y + 48, 36, 8, 0.85, False),
            (x + 28, y + 56, x + 58, y + 56, 78, 16, 1.0, True),
            (x + 26, y + 68, x + 64, y + 68, 42, 8, 0.8, False),
            (x + 82, y + 48, x + 118, y + 48, 28, 6, 0.75, False),
            (x + 134, y + 48, x + 174, y + 48, 52, 10, 0.85, False),
            (x + w - 150, y + 46, x + w - 118, y + 46, 32, 8, 0.8, False),
            (x + w - 112, y + 46, x + w - 78, y + 46, 86, 16, 1.05, True),
            (x + w - 72, y + 46, x + w - 30, y + 46, 38, 8, 0.8, False),
            (x + w - 128, y + 68, x + w - 94, y + 68, 52, 10, 0.85, False),
            (x + w - 88, y + 68, x + w - 62, y + 68, 92, 18, 1.1, True),
        ]
        for seg in mid_segments:
            draw_var_segment(*seg)

        # Bottom decoration and side technical marks.
        bottom_segments = [
            (x + 18, y + h - 18, x + 44, y + h - 18, 64, 12, 0.95, False),
            (x + 52, y + h - 18, x + 84, y + h - 18, 96, 18, 1.05, True),
            (x + 92, y + h - 18, x + 126, y + h - 18, 40, 8, 0.8, False),
            (x + w - 128, y + h - 18, x + w - 102, y + h - 18, 38, 8, 0.8, False),
            (x + w - 96, y + h - 18, x + w - 60, y + h - 18, 92, 18, 1.05, True),
            (x + w - 54, y + h - 18, x + w - 24, y + h - 18, 52, 10, 0.9, False),
            (x + 14, y + h - 52, x + 14, y + h - 38, 74, 16, 1.0, True),
            (x + 14, y + h - 32, x + 14, y + h - 20, 28, 8, 0.8, False),
            (x + w - 18, y + 24, x + w - 18, y + 46, 82, 18, 1.05, True),
            (x + w - 18, y + 54, x + w - 18, y + 74, 34, 8, 0.85, False),
        ]
        for seg in bottom_segments:
            draw_var_segment(*seg)

        # Small scratches / worn-tech texture.
        painter.setPen(QPen(QColor(208, 248, 255, 12), 0.75))
        scratch_lines = [
            (x + 136, y + 34, x + 184, y + 70),
            (x + w - 106, y + 18, x + w - 58, y + 54),
            (x + 48, y + h - 34, x + 86, y + h - 14),
            (x + 92, y + h - 52, x + 148, y + h - 22),
            (x + 198, y + 24, x + 230, y + 44),
            (x + 220, y + 72, x + 262, y + 96),
        ]
        for x1, y1, x2, y2 in scratch_lines:
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Dark interruption zones to avoid uniformity.
        dark_cuts = [
            QRectF(x + 58, y + 10, 12, 5),
            QRectF(x + 148, y + 10, 16, 5),
            QRectF(x + w - 86, y + 10, 10, 5),
            QRectF(x + 34, y + 46, 18, 4),
            QRectF(x + w - 96, y + 44, 14, 4),
            QRectF(x + 72, y + h - 20, 14, 4),
            QRectF(x + w - 70, y + h - 20, 16, 4),
            QRectF(x + w - 20, y + 58, 4, 12),
        ]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 42))
        for rect in dark_cuts:
            painter.drawRect(rect)

        painter.restore()

        # Outer glow stack kept subtle but uneven.
        for width, a in [(6.0, 5), (3.6, 16), (1.8, 34)]:
            painter.setPen(QPen(QColor(64, 232, 255, a), width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(outer)
        painter.setPen(QPen(QColor(96, 244, 255, 196), 0.62))
        painter.drawPath(outer)

        # Brighter hotspots around the outer frame.
        bright_segments = [
            (x + 24, y + 2, x + 62, y + 2),
            (x + 74, y + 2, x + 96, y + 2),
            (x + 116, y + 2, x + 142, y + 2),
            (x + w - 96, y + 2, x + w - 74, y + 2),
            (x + w - 82, y + 2, x + w - 58, y + 2),
            (x + w - 46, y + 2, x + w - 32, y + 2),
            (x + w - 2, y + 24, x + w - 2, y + 50),
            (x + w - 2, y + 68, x + w - 2, y + 88),
            (x + 2, y + h - 58, x + 2, y + h - 40),
            (x + 24, y + h - 2, x + 72, y + h - 2),
            (x + 94, y + h - 2, x + 128, y + h - 2),
        ]
        for x1, y1, x2, y2 in bright_segments:
            painter.setPen(QPen(QColor(68, 232, 255, 34), 3.8))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            painter.setPen(QPen(QColor(198, 248, 255, 156), 1.0))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            painter.setPen(QPen(QColor(255, 255, 255, 96), 0.9))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Title text.
        title_font = QFont('Bahnschrift', 10, QFont.Weight.Bold)
        painter.setFont(title_font)
        painter.setPen(QColor(76, 234, 255, 242))
        painter.drawText(QRectF(x + 18, y + 6, max(84, w - 36), 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, 'CAR INFO')

    def draw_vehicle_info(self, painter):
        x, y, w, h = self.vehicle_info_geometry()
        self.draw_cyber_panel(painter, x, y, w, h, "CAR INFO", STREET_CORAL, 28)

        class_label = self.car_class_label or "A"
        pi_text = str(int(self.pi_value if self.pi_value > 0 else 700))
        drive_text = self.driveline_label or "RWD"
        engine_text = self.engine_label or "ENG"
        year_text = self.car_year or "----"
        make_text = self.car_make or "Unknown"
        model_text = self.car_model or "Vehicle"

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # LIVE111: make CAR INFO feel like the clean street-art family,
        # without adding any new information or heavy frames.
        self.draw_halftone_dots(painter, x + w - 56, y + 27, STREET_CORAL,
                                rows=3, cols=5, spacing=4.0, radius=0.72, alpha=15)
        self.draw_marker_line(painter, x + 18, y + h - 25, x + 106, y + h - 29,
                              STREET_CORAL, 1.7, 48)

        left = x + 18
        top = y + 28
        class_w = 50 if len(class_label) == 1 else 62
        pi_w = 78
        badge_h = 34
        class_x = left
        pi_x = class_x + class_w + 3

        # Tiny sticker/slash behind the badge so it reads like a designed decal.
        self.draw_sticker_slash(painter, class_x - 8, top - 4, class_w + pi_w + 28, badge_h + 10,
                                STREET_CORAL, alpha=20)

        class_color = QColor(self.car_class_color)
        # Clamp very bright/cyber class colors into a warmer street-paint badge.
        mixed_class = QColor(
            int(class_color.red() * 0.72 + STREET_CORAL.red() * 0.28),
            int(class_color.green() * 0.72 + STREET_CORAL.green() * 0.28),
            int(class_color.blue() * 0.72 + STREET_CORAL.blue() * 0.28),
            238,
        )
        if class_label.upper().startswith('S'):
            mixed_class = QColor(STREET_CORAL.red(), STREET_CORAL.green(), STREET_CORAL.blue(), 238)

        # CLASS badge: still Forza-readable, but cleaner and less neon.
        class_rect = QRectF(class_x, top, class_w, badge_h)
        class_grad = QLinearGradient(class_rect.left(), class_rect.top(), class_rect.left(), class_rect.bottom())
        class_grad.setColorAt(0.0, QColor(min(mixed_class.red() + 18, 255), min(mixed_class.green() + 14, 255), min(mixed_class.blue() + 12, 255), 236))
        class_grad.setColorAt(1.0, QColor(max(mixed_class.red() - 18, 0), max(mixed_class.green() - 16, 0), max(mixed_class.blue() - 12, 0), 232))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(class_grad)
        painter.drawRoundedRect(class_rect, 4, 4)
        painter.setPen(QPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 128), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(class_rect, 4, 4)

        painter.setFont(QFont("Arial Black", 19 if len(class_label) == 1 else 17))
        painter.setPen(QColor(250, 246, 236, 250))
        painter.drawText(class_rect.adjusted(0, -1, 0, 1), Qt.AlignmentFlag.AlignCenter, class_label)

        # PI badge: sticker-black, not cyber-black.
        pi_rect = QRectF(pi_x, top, pi_w, badge_h)
        pi_grad = QLinearGradient(pi_rect.left(), pi_rect.top(), pi_rect.left(), pi_rect.bottom())
        pi_grad.setColorAt(0.0, QColor(26, 24, 23, 224))
        pi_grad.setColorAt(1.0, QColor(7, 8, 9, 220))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pi_grad)
        painter.drawRoundedRect(pi_rect, 4, 4)
        painter.setPen(QPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 96), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(pi_rect, 4, 4)

        painter.setFont(QFont("Arial Black", 18))
        painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 244))
        painter.drawText(pi_rect.adjusted(0, -1, 0, 1), Qt.AlignmentFlag.AlignCenter, pi_text)
        self.draw_clean_spray(painter, pi_rect.right() + 8, top + 6, STREET_CORAL, 0.52, 18)

        # YEAR / MAKE: calmer hierarchy, amber year + off-white make.
        meta_y = top + badge_h + 13
        header_font = QFont("Bahnschrift", 16, QFont.Weight.Bold)
        painter.setFont(header_font)
        fm = QFontMetrics(header_font)
        year_draw = str(year_text)
        painter.setPen(QColor(STREET_AMBER.red(), STREET_AMBER.green(), STREET_AMBER.blue(), 232))
        painter.drawText(QRectF(left, meta_y, 96, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, year_draw)
        year_w = fm.horizontalAdvance(year_draw)
        painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 230))
        painter.drawText(QRectF(left + year_w + 10, meta_y, max(20, w - 38 - year_w - 10), 22),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(make_text))

        # MODEL: primary readable line, slightly less loud than previous Arial Black block.
        painter.setFont(QFont("Arial Black", 20))
        painter.setPen(QColor(246, 242, 232, 245))
        model_rect = QRectF(left, meta_y + 25, w - 34, 27)
        painter.drawText(model_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(model_text))
        self.draw_marker_line(painter, left + 1, meta_y + 54, left + min(w - 46, 184), meta_y + 50,
                              STREET_CORAL, 1.6, 58)

        # DRIVE / ENGINE: compact spec tags instead of panel-like columns.
        info_y = meta_y + 64
        stats = [("DRIVE", drive_text, STREET_CORAL), ("ENGINE", engine_text, STREET_AMBER)]
        col_w = (w - 42) / 2.0
        for i, (label, value, accent) in enumerate(stats):
            sx = left + i * (col_w + 8)
            tag_rect = QRectF(sx, info_y, col_w, 30)
            shade = QColor(STREET_CHARCOAL)
            shade.setAlpha(34)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(shade)
            painter.drawRoundedRect(tag_rect, 5, 5)
            self.draw_marker_line(painter, sx + 2, info_y + 3, sx + min(col_w - 6, 62), info_y + 1,
                                  accent, 1.4, 58)

            painter.setFont(QFont("Bahnschrift", 8, QFont.Weight.Bold))
            painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 132))
            painter.drawText(QRectF(sx + 7, info_y + 3, col_w - 12, 10),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            painter.setFont(QFont("Bahnschrift", 15, QFont.Weight.Bold))
            painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 228))
            painter.drawText(QRectF(sx + 7, info_y + 13, col_w - 12, 17),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(value))

        painter.restore()

    def draw_core_data(self, painter):
        x, y, w, h = self.input_group_geometry()

        rows = [
            ("H", self.handbrake_pct, QColor(STREET_AMBER)),
            ("C", self.clutch_pct, QColor(STREET_MINT)),
            ("B", self.brake_pct, QColor(STREET_AMBER)),
            ("T", self.accel_pct, QColor(STREET_MINT)),
        ]

        # LIVE110: INPUT stays compact, but now has the same clean street label
        # language as the larger panels.  No added data, only a clearer identity.
        self.draw_street_label(painter, x + 2, y - 8, "INPUT", STREET_CORAL, max_w=86, compact=True)
        self.draw_halftone_dots(painter, x + w - 30, y + 4, STREET_CORAL, rows=2, cols=4, spacing=4.2, radius=0.75, alpha=16)
        self.draw_graffiti_arrow(painter, x + 58, y + 10, x + 74, y + 7, STREET_CORAL, 1.2, 42)
        self.draw_graffiti_cross(painter, x + w - 10, y + 126, STREET_CORAL, 0.58, 34)

        bar_w = 13
        bar_h = 112
        gap = 6
        total_w = len(rows) * bar_w + (len(rows) - 1) * gap
        start_x = x + (w - total_w) * 0.5
        bar_y = y + 18

        for i, (letter, value, color) in enumerate(rows):
            bx = start_x + i * (bar_w + gap)
            # tiny sticker shadow behind each stack so the bars read on bright road reflections
            shade = QColor(STREET_CHARCOAL); shade.setAlpha(22)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(shade)
            painter.drawRoundedRect(QRectF(bx - 2, bar_y - 2, bar_w + 4, bar_h + 6), 4, 4)
            self.draw_input_vertical_bar(painter, bx, bar_y, bar_w, bar_h, value, letter, color)

    def draw_value_bar(self, painter, x, y, w, h, pct, fill_color, bg_alpha=22):
        painter.setPen(QPen(QColor(220, 245, 255, 42), 1.0))
        painter.setBrush(QColor(7, 12, 18, bg_alpha))
        painter.drawRoundedRect(QRectF(x, y, w, h), 5, 5)
        fill_w = (w - 2) * clamp(pct, 0.0, 100.0) / 100.0
        if fill_w > 0.5:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(with_alpha(fill_color, 52))
            painter.drawRoundedRect(QRectF(x + 1, y + 1, fill_w, h - 2), 4, 4)
            painter.setBrush(with_alpha(fill_color, 210))
            painter.drawRoundedRect(QRectF(x + 1, y + 1, max(1.5, fill_w - 1), h - 2), 4, 4)

    def draw_signed_center_bar(self, painter, x, y, w, h, pct, left_color, right_color):
        pct = clamp(pct, -100.0, 100.0)
        center = x + w * 0.5
        segs_per_side = 8
        gap = 2.0
        side_w = (w - gap * (segs_per_side * 2 - 1)) * 0.5
        seg_w = max(4.0, side_w / segs_per_side)
        seg_h = h

        # transparent segmented gauge (no solid black background)
        for side in (-1, 1):
            for i in range(segs_per_side):
                if side < 0:
                    sx = center - gap * 0.5 - seg_w - i * (seg_w + gap)
                    col = QColor(left_color)
                else:
                    sx = center + gap * 0.5 + i * (seg_w + gap)
                    col = QColor(right_color)
                rect = QRectF(sx, y, seg_w, seg_h)
                painter.setPen(QPen(QColor(230, 246, 255, 58), 0.9))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect, 1.8, 1.8)

        # thin center reference line
        painter.setPen(QPen(QColor(236, 248, 255, 135), 0.9))
        painter.drawLine(QPointF(center, y - 2), QPointF(center, y + h + 2))

        active_side = -1 if pct < 0 else 1
        active_ratio = abs(pct) / 100.0
        active_count = active_ratio * segs_per_side
        active_color = QColor(left_color if active_side < 0 else right_color)

        for i in range(segs_per_side):
            if active_side < 0:
                sx = center - gap * 0.5 - seg_w - i * (seg_w + gap)
            else:
                sx = center + gap * 0.5 + i * (seg_w + gap)
            fill_amount = max(0.0, min(1.0, active_count - i))
            if fill_amount <= 0.02:
                continue
            rect = QRectF(sx, y + (1.0 - fill_amount) * seg_h, seg_w, seg_h * fill_amount)
            glow = QColor(active_color); glow.setAlpha(90)
            core = QColor(active_color); core.setAlpha(242)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawRoundedRect(QRectF(rect.x() - 0.8, rect.y() - 0.6, rect.width() + 1.6, rect.height() + 1.2), 2.0, 2.0)
            painter.setBrush(core)
            painter.drawRoundedRect(rect, 1.8, 1.8)
            painter.setBrush(QColor(255, 255, 255, 42))
            painter.drawRoundedRect(QRectF(rect.x() + 0.7, rect.y() + 0.5, max(1.0, rect.width() * 0.18), max(1.0, rect.height() - 1.0)), 1.0, 1.0)

        knob_x = center + (w * 0.5) * (pct / 100.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 236))
        painter.drawEllipse(QPointF(knob_x, y + h * 0.5), 3.0, 3.0)

    def draw_counter_bar(self, painter, x, y, w, h, pct):
        pct = clamp(pct, 0.0, 100.0)
        seg_count = 16
        gap = 2.0
        seg_w = max(3.8, (w - gap * (seg_count - 1)) / seg_count)

        for i in range(seg_count):
            sx = x + i * (seg_w + gap)
            rect = QRectF(sx, y, seg_w, h)
            painter.setPen(QPen(QColor(230, 246, 255, 58), 0.9))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 1.8, 1.8)

        active_count = (pct / 100.0) * seg_count
        for i in range(seg_count):
            fill_amount = max(0.0, min(1.0, active_count - i))
            if fill_amount <= 0.02:
                continue
            sx = x + i * (seg_w + gap)
            col = QColor(255, 166, 70) if pct < 75 else QColor(255, 92, 108)
            if pct < 42:
                col = QColor(STREET_MINT)
            rect = QRectF(sx, y + (1.0 - fill_amount) * h, seg_w, h * fill_amount)
            glow = QColor(col); glow.setAlpha(88)
            core = QColor(col); core.setAlpha(242)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawRoundedRect(QRectF(rect.x() - 0.8, rect.y() - 0.6, rect.width() + 1.6, rect.height() + 1.2), 2.0, 2.0)
            painter.setBrush(core)
            painter.drawRoundedRect(rect, 1.8, 1.8)
            painter.setBrush(QColor(255, 255, 255, 42))
            painter.drawRoundedRect(QRectF(rect.x() + 0.7, rect.y() + 0.5, max(1.0, rect.width() * 0.18), max(1.0, rect.height() - 1.0)), 1.0, 1.0)

    def draw_steer_panel(self, painter):
        x, y, w, h = self.steer_panel_geometry()
        # LIVE163: viewer-facing WHEEL / COUNTER panel.
        # Same size and position, but the arrows carry the meaning before the text does.
        label_x = x + 10
        bar_x = x + 82
        bar_w = w - 92
        row1_y = y + 15
        row2_y = y + 45

        self.draw_marker_line(painter, x + 6, y + 6, x + 68, y + 4, STREET_AMBER, 2.0, 72)

        painter.setFont(QFont("Bahnschrift", 11, QFont.Weight.Bold))
        painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 252))
        painter.drawText(QRectF(label_x, row1_y - 6, 74, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "WHEEL")
        painter.drawText(QRectF(label_x, row2_y - 6, 82, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "COUNTER")

        painter.setFont(QFont("Bahnschrift", 8, QFont.Weight.Bold))
        painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 152))
        painter.drawText(QRectF(bar_x - 22, row1_y - 1, 18, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "L")
        painter.drawText(QRectF(bar_x + bar_w + 2, row1_y - 1, 18, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "R")

        zero_x = bar_x + bar_w * 0.5

        self.draw_signed_center_bar(painter, bar_x, row1_y, bar_w, 14, self.steer_pct, QColor(STREET_AMBER), QColor(STREET_MINT))
        self.draw_counter_bar(painter, bar_x, row2_y, bar_w, 14, self.counter_pct)

        # LIVE182: draw synced zero marker on top so it remains readable.
        painter.setPen(QPen(QColor(255, 255, 255, 118), 1.25, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(zero_x, row1_y - 8), QPointF(zero_x, row1_y + 8))
        painter.drawLine(QPointF(zero_x, row2_y - 8), QPointF(zero_x, row2_y + 8))
        painter.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        painter.setPen(QColor(255, 255, 255, 154))
        painter.drawText(QRectF(zero_x - 10, row1_y + 8, 20, 10), Qt.AlignmentFlag.AlignCenter, "0")
        self.draw_clean_spray(painter, bar_x + bar_w + 10, row2_y + 5, STREET_MINT, 0.54, 16)

        painter.setFont(QFont("Bahnschrift", 8, QFont.Weight.Bold))
        painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 196))
        painter.drawText(QRectF(bar_x + bar_w - 40, row2_y + 13, 40, 13), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{round(self.counter_pct):d}%")

    def update_live_map(self, abs_angle, holding_drift):
        x = float(self.position_x)
        z = float(self.position_z)
        if not math.isfinite(x) or not math.isfinite(z):
            return
        if abs(x) < 0.0001 and abs(z) < 0.0001:
            return

        if self.map_cursor_x is None or self.map_cursor_z is None:
            self.map_cursor_x = x
            self.map_cursor_z = z
        else:
            smooth = 0.24 if self.speed_kmh > 16 else 0.16
            self.map_cursor_x = lerp(self.map_cursor_x, x, smooth)
            self.map_cursor_z = lerp(self.map_cursor_z, z, smooth)

        if self.map_miss_cooldown > 0:
            self.map_miss_cooldown -= 1

        if self.map_last_x is not None and self.map_last_z is not None:
            jump = math.hypot(x - self.map_last_x, z - self.map_last_z)
            if jump > 650:
                self.live_map_points.clear()
                self.live_map_misses.clear()
                self.map_last_x = x
                self.map_last_z = z
                self.map_cursor_x = x
                self.map_cursor_z = z
                return

        moved = 999 if self.map_last_x is None else math.hypot(x - self.map_last_x, z - self.map_last_z)
        if self.speed_kmh > 8 and moved > 4.5:
            self.live_map_points.append({
                "x": x,
                "z": z,
                "drift": bool(holding_drift),
            })
            if len(self.live_map_points) > 520:
                self.live_map_points = self.live_map_points[-520:]
            self.map_last_x = x
            self.map_last_z = z

        hard_stop = self.map_prev_abs_angle > 36 and self.map_prev_speed > 28 and self.speed_kmh < 8
        sudden_stop = self.map_prev_speed > 42 and self.speed_kmh < 7 and self.map_prev_abs_angle > 18
        slip_collapse = self.map_prev_rear_slip > 1.55 and self.rear_slip < 0.35 and self.map_prev_abs_angle > 28 and self.speed_kmh < 10
        if self.map_miss_cooldown <= 0 and (hard_stop or sudden_stop or slip_collapse):
            miss_type = "SPIN" if hard_stop else "STOP" if sudden_stop else "MISS"
            self.live_map_misses.append({"x": x, "z": z, "type": miss_type})
            self.live_map_misses = self.live_map_misses[-24:]
            self.map_miss_cooldown = 112

        self.map_prev_speed = self.speed_kmh
        self.map_prev_abs_angle = abs_angle
        self.map_prev_rear_slip = self.rear_slip

    def draw_g_meter(self, painter):
        x, y, w, h = self.g_meter_geometry()
        self.draw_cyber_panel(painter, x, y, w, h, "G TELEMETRY", QColor(STREET_MINT), 34)

        # LIVE161: G TELEMETRY is a load/weight-shift readout.
        # Keep it compact and practical: cleaner ball, quieter trail, and short LOAD labels.
        self.draw_halftone_dots(painter, x + w - 52, y + 24, STREET_MINT, rows=3, cols=5, spacing=4.4, radius=0.82, alpha=13)
        self.draw_marker_line(painter, x + 18, y + h - 22, x + 76, y + h - 25, STREET_MINT, 1.7, 42)
        self.draw_graffiti_arrow(painter, x + 80, y + h - 25, x + 96, y + h - 28, STREET_MINT, 1.1, 32)
        self.draw_graffiti_cross(painter, x + w - 18, y + h - 20, STREET_MINT, 0.54, 26)

        cx = x + w * 0.375
        cy = y + h * 0.52
        radius = min(w * 0.31, h * 0.34)
        g_range = 1.50

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Soft technical rings.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for r, alpha, width in [(radius, 154, 1.9), (radius * 0.66, 72, 1.25), (radius * 0.34, 38, 0.9)]:
            painter.setPen(QPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), alpha), width))
            painter.drawEllipse(QPointF(cx, cy), r, r)

        # Axes: lateral line is slightly stronger because this is a drift HUD.
        painter.setPen(QPen(QColor(STREET_MINT.red(), STREET_MINT.green(), STREET_MINT.blue(), 66), 1.35))
        painter.drawLine(QPointF(cx - radius, cy), QPointF(cx + radius, cy))
        painter.setPen(QPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 42), 1.0))
        painter.drawLine(QPointF(cx, cy - radius), QPointF(cx, cy + radius))
        painter.setPen(QPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 20), 0.9))
        painter.drawLine(QPointF(cx - radius * 0.72, cy + radius * 0.72), QPointF(cx + radius * 0.72, cy - radius * 0.72))
        painter.drawLine(QPointF(cx - radius * 0.72, cy - radius * 0.72), QPointF(cx + radius * 0.72, cy + radius * 0.72))

        # Trail clarity pass: show the path as a readable motion line,
        # with a brighter recent section so viewers can instantly tell
        # where the load is moving now.
        trail_points = []
        for gl, gf in self.g_trail:
            px = cx - clamp(gl / g_range, -1.0, 1.0) * radius
            py = cy + clamp(gf / g_range, -1.0, 1.0) * radius
            trail_points.append(QPointF(px, py))

        if len(trail_points) >= 2:
            recent_start = max(1, len(trail_points) - 8)
            for i in range(1, len(trail_points)):
                t = i / max(1, len(trail_points) - 1)
                p0 = trail_points[i - 1]
                p1 = trail_points[i]
                width = 1.2 + 1.35 * t
                glow_alpha = int(12 + 36 * t)
                core_alpha = int(20 + 95 * t)
                glow_col = QColor(STREET_MINT.red(), STREET_MINT.green(), STREET_MINT.blue(), glow_alpha)
                core_col = QColor(246, 250, 255, core_alpha if i >= recent_start else int(core_alpha * 0.52))
                painter.setPen(QPen(glow_col, width + 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(p0, p1)
                painter.setPen(QPen(core_col, width * (1.1 if i >= recent_start else 0.86), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(p0, p1)

            # Recent direction accent.
            tail_a = trail_points[-2]
            tail_b = trail_points[-1]
            dx = tail_b.x() - tail_a.x()
            dy = tail_b.y() - tail_a.y()
            seg_len = math.hypot(dx, dy)
            if seg_len > 0.001:
                ux = dx / seg_len
                uy = dy / seg_len
                nx = -uy
                ny = ux
                arrow_tip = tail_b
                arrow_back = QPointF(tail_b.x() - ux * 8.0, tail_b.y() - uy * 8.0)
                arrow_left = QPointF(arrow_back.x() + nx * 3.0, arrow_back.y() + ny * 3.0)
                arrow_right = QPointF(arrow_back.x() - nx * 3.0, arrow_back.y() - ny * 3.0)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(STREET_MINT.red(), STREET_MINT.green(), STREET_MINT.blue(), 168))
                painter.drawPolygon(QPolygonF([arrow_tip, arrow_left, arrow_right]))

        # Sample dots stay, but quieter in the old tail and stronger near now.
        for i, pt in enumerate(trail_points):
            t = (i + 1) / max(1, len(trail_points))
            is_recent = i >= max(0, len(trail_points) - 6)
            painter.setPen(Qt.PenStyle.NoPen)
            if is_recent:
                painter.setBrush(QColor(STREET_MINT.red(), STREET_MINT.green(), STREET_MINT.blue(), int(72 + 84 * t)))
                painter.drawEllipse(pt, 1.8 + 2.2 * t, 1.8 + 2.2 * t)
                painter.setBrush(QColor(248, 252, 255, int(92 + 92 * t)))
                painter.drawEllipse(pt, 0.75 + 0.8 * t, 0.75 + 0.8 * t)
            else:
                painter.setBrush(QColor(STREET_MINT.red(), STREET_MINT.green(), STREET_MINT.blue(), int(5 + 24 * t)))
                painter.drawEllipse(pt, 1.0 + 1.3 * t, 1.0 + 1.3 * t)

        dot_x = cx - clamp(self.g_lat_display / g_range, -1.0, 1.0) * radius
        dot_y = cy + clamp(self.g_long_display / g_range, -1.0, 1.0) * radius

        # Center marker and load vector.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 160))
        painter.drawEllipse(QPointF(cx, cy), 2.0, 2.0)
        for lw, alpha in [(7.0, 18), (4.3, 34), (2.1, 76)]:
            painter.setPen(QPen(QColor(STREET_MINT.red(), STREET_MINT.green(), STREET_MINT.blue(), alpha), lw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(cx, cy), QPointF(dot_x, dot_y))
        painter.setPen(QPen(QColor(235, 250, 255, 132), 0.95))
        painter.drawLine(QPointF(cx, cy), QPointF(dot_x, dot_y))

        # Main point: still obvious, but less shouty than the old magenta blob.
        point_col = QColor(STREET_CORAL)
        for glow_r, alpha in [(13.5, 28), (9.5, 54), (6.8, 96)]:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(point_col.red(), point_col.green(), point_col.blue(), alpha))
            painter.drawEllipse(QPointF(dot_x, dot_y), glow_r, glow_r)
        painter.setPen(QPen(QColor(point_col.red(), point_col.green(), point_col.blue(), 188), 1.15))
        painter.setBrush(QColor(point_col.red(), point_col.green(), point_col.blue(), 212))
        painter.drawEllipse(QPointF(dot_x, dot_y), 5.8, 5.8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 242, 252, 250))
        painter.drawEllipse(QPointF(dot_x, dot_y), 2.0, 2.0)

        # Load interpretation.
        abs_lat = abs(self.g_lat_display)
        abs_long = abs(self.g_long_display)
        load_side = "CENTER"
        if abs_lat >= 0.10:
            load_side = "LEFT" if self.g_lat_display > 0 else "RIGHT"
        drive_state = "NEUTRAL"
        if abs_long >= 0.10:
            drive_state = "DRIVE" if self.g_long_display > 0 else "BRAKE"

        label_x = x + w - 122
        g_total = math.hypot(self.g_lat_display, self.g_long_display)

        painter.setFont(QFont("Bahnschrift", 8, QFont.Weight.Bold))
        painter.setPen(QColor(246, 250, 255, 148))
        painter.drawText(QRectF(label_x, y + 38, 104, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "TOTAL G")
        painter.setFont(QFont("Arial Black", 17))
        painter.setPen(QColor(255, 255, 255, 248))
        painter.drawText(QRectF(label_x, y + 51, 98, 26), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{g_total:.2f}")

        # LAT/LONG numeric rows.
        painter.setFont(QFont("Bahnschrift", 8, QFont.Weight.Bold))
        painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 112))
        painter.drawText(QRectF(label_x, y + 82, 44, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "LAT")
        painter.drawText(QRectF(label_x, y + 101, 44, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "LONG")
        painter.setFont(QFont("Bahnschrift", 11, QFont.Weight.Bold))
        painter.setPen(QColor(STREET_MINT.red(), STREET_MINT.green(), STREET_MINT.blue(), 192))
        painter.drawText(QRectF(label_x + 45, y + 79, 62, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{self.g_lat_display:+.2f}")
        painter.setPen(QColor(STREET_AMBER.red(), STREET_AMBER.green(), STREET_AMBER.blue(), 188))
        painter.drawText(QRectF(label_x + 45, y + 98, 62, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{self.g_long_display:+.2f}")

        # Short load chips.  These are intentionally text-only and compact.
        load_col = QColor(STREET_MINT) if load_side != "CENTER" else QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 184)
        drive_col = QColor(STREET_AMBER) if drive_state != "NEUTRAL" else QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 132)

        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 158))
        painter.drawText(QRectF(label_x, y + 123, 42, 13), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "LOAD")
        painter.setFont(QFont("Arial Black", 10))
        painter.setPen(load_col)
        self.draw_sticker_slash(painter, label_x + 38, y + 120, 80, 17, load_col, 10)
        painter.drawText(QRectF(label_x + 42, y + 119, 82, 19), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, load_side)

        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 148))
        painter.drawText(QRectF(label_x, y + 142, 42, 13), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "MODE")
        painter.setFont(QFont("Arial Black", 10))
        painter.setPen(drive_col)
        self.draw_sticker_slash(painter, label_x + 38, y + 139, 80, 17, drive_col, 9)
        painter.drawText(QRectF(label_x + 42, y + 138, 82, 19), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, drive_state)

        # Tiny axis labels around the ball.
        painter.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        painter.setPen(QColor(240, 245, 255, 82))
        painter.drawText(QRectF(cx - radius - 18, cy + radius + 6, 36, 12), Qt.AlignmentFlag.AlignCenter, "LAT")
        painter.drawText(QRectF(cx + radius - 18, cy + radius + 6, 36, 12), Qt.AlignmentFlag.AlignCenter, "LAT")
        painter.drawText(QRectF(cx - 22, cy - radius - 14, 44, 12), Qt.AlignmentFlag.AlignCenter, "LONG")
        painter.restore()

    def draw_live_map(self, painter):
        x, y, w, h = self.map_panel_geometry()
        self.draw_cyber_panel(painter, x, y, w, h, "TRACK MAP", STREET_CORAL, 56)
        # LIVE110: map gets a clean sticker accent but stays mostly functional.
        self.draw_halftone_dots(painter, x + w - 58, y + 28, STREET_CORAL, rows=4, cols=5, spacing=4.0, radius=0.86, alpha=20)
        self.draw_marker_line(painter, x + 20, y + h - 22, x + 92, y + h - 24, STREET_CORAL, 2.1, 68)

        painter.setFont(QFont("Bahnschrift", 10, QFont.Weight.Bold))
        painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 150))
        painter.drawText(QRectF(x + w - 120, y + 8, 100, 22), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{len(self.live_map_points)} PTS")

        map_x = x + 20
        map_y = y + 42
        map_w = w - 40
        map_h = h - 80

        painter.setPen(QPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 18), 0.9))
        for i in range(1, 6):
            gx = map_x + map_w * i / 6
            painter.drawLine(QPointF(gx, map_y), QPointF(gx, map_y + map_h))
        for i in range(1, 4):
            gy = map_y + map_h * i / 4
            painter.drawLine(QPointF(map_x, gy), QPointF(map_x + map_w, gy))

        painter.setPen(QPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 62), 1.35))
        painter.setBrush(QColor(0, 0, 0, 0))
        painter.drawRoundedRect(QRectF(map_x, map_y, map_w, map_h), 8, 8)

        if not self.live_map_points:
            painter.setFont(QFont("Bahnschrift", 11, QFont.Weight.Bold))
            painter.setPen(QColor(220, 245, 255, 95))
            painter.drawText(QRectF(map_x, map_y, map_w, map_h), Qt.AlignmentFlag.AlignCenter, "LEARNING")
        else:
            xs = [p["x"] for p in self.live_map_points] + [m["x"] for m in self.live_map_misses]
            zs = [p["z"] for p in self.live_map_points] + [m["z"] for m in self.live_map_misses]
            if self.map_cursor_x is not None and self.map_cursor_z is not None:
                xs.append(self.map_cursor_x)
                zs.append(self.map_cursor_z)
            min_x, max_x = min(xs), max(xs)
            min_z, max_z = min(zs), max(zs)
            span_x = max(1.0, max_x - min_x)
            span_z = max(1.0, max_z - min_z)
            scale = min(map_w / span_x, map_h / span_z) * 0.86
            cx = (min_x + max_x) * 0.5
            cz = (min_z + max_z) * 0.5

            def mp(px, pz):
                return QPointF(map_x + map_w * 0.5 - (px - cx) * scale,
                               map_y + map_h * 0.5 - (pz - cz) * scale)

            prev = None
            prev_drift = False
            for p in self.live_map_points:
                q = mp(p["x"], p["z"])
                if prev is not None:
                    is_drift_line = (p["drift"] or prev_drift)
                    col = QColor(STREET_AMBER.red(), STREET_AMBER.green(), STREET_AMBER.blue(), 238) if is_drift_line else QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 118)
                    glow_col = QColor(col); glow_col.setAlpha(42 if is_drift_line else 18)
                    painter.setPen(QPen(glow_col, 7.4 if is_drift_line else 5.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                    painter.drawLine(prev, q)
                    painter.setPen(QPen(col, 5.7 if is_drift_line else 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                    painter.drawLine(prev, q)
                prev = q
                prev_drift = bool(p["drift"])

            for m in self.live_map_misses:
                q = mp(m["x"], m["z"])
                painter.setPen(QPen(QColor(255, 65, 72, 230), 2.8))
                painter.drawLine(QPointF(q.x() - 7, q.y() - 7), QPointF(q.x() + 7, q.y() + 7))
                painter.drawLine(QPointF(q.x() + 7, q.y() - 7), QPointF(q.x() - 7, q.y() + 7))

            px = self.map_cursor_x if self.map_cursor_x is not None else self.live_map_points[-1]["x"]
            pz = self.map_cursor_z if self.map_cursor_z is not None else self.live_map_points[-1]["z"]
            q = mp(px, pz)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(STREET_MINT.red(), STREET_MINT.green(), STREET_MINT.blue(), 124))
            painter.drawEllipse(q, 19, 19)
            painter.setBrush(QColor(STREET_MINT.red(), STREET_MINT.green(), STREET_MINT.blue(), 252))
            painter.drawEllipse(q, 8.2, 8.2)
            painter.setBrush(QColor(255, 255, 255, 238))
            painter.drawEllipse(q, 2.8, 2.8)

            # Emphasize the last few meters of the route so direction is easier to read.
            recent = self.live_map_points[-8:]
            if len(recent) >= 2:
                prev_recent = None
                for rp in recent:
                    rq = mp(rp["x"], rp["z"])
                    if prev_recent is not None:
                        recent_col = QColor(STREET_MINT.red(), STREET_MINT.green(), STREET_MINT.blue(), 112)
                        painter.setPen(QPen(recent_col, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                        painter.drawLine(prev_recent, rq)
                    prev_recent = rq

        fy = y + h - 30
        painter.setFont(QFont("Bahnschrift", 9, QFont.Weight.Bold))
        painter.setPen(QColor(200, 240, 255, 170))
        painter.drawText(QRectF(x + 20, fy, 48, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "YOU")
        painter.setPen(QPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 112), 3))
        painter.drawLine(QPointF(x + 54, fy + 9), QPointF(x + 82, fy + 9))
        painter.setPen(QColor(200, 240, 255, 170))
        painter.drawText(QRectF(x + 88, fy, 56, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "ROAD")
        painter.setPen(QPen(QColor(255, 142, 54, 232), 3.4))
        painter.drawLine(QPointF(x + 128, fy + 9), QPointF(x + 156, fy + 9))
        painter.setPen(QColor(200, 240, 255, 170))
        painter.drawText(QRectF(x + 162, fy, 92, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "DRIFT")
        self.draw_graffiti_arrow(painter, x + 214, fy + 8, x + 230, fy + 5, STREET_AMBER, 1.1, 38)
        self.draw_graffiti_cross(painter, x + 18, y + 24, STREET_MINT, 0.56, 28)

    def draw_drift_panel(self, painter):
        x, y, w, h = self.drift_panel_geometry()
        self.draw_cyber_panel(painter, x, y, w, h, None, STREET_CORAL, 62)

        state_colors = {
            "GRIP": QColor(190, 185, 172),
            "ENTRY": QColor(STREET_MINT),
            "HOLD": QColor(STREET_CORAL),
            "ANGLE": QColor(STREET_CORAL),
            "SMOKE": QColor(STREET_AMBER),
            "SPIN": QColor(255, 86, 94),
        }
        accent = state_colors.get(self.drift_state, QColor(144, 238, 255))

        def metric_bar(bx, by, bw, bh, value, color, max_value=100.0):
            pct = clamp(value / max_value, 0.0, 1.0)
            # LIVE109: less cyber outline, more chalky segmented sticker-bar feel.
            painter.setPen(QPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 32), 0.9))
            painter.setBrush(QColor(8, 10, 12, 20))
            painter.drawRoundedRect(QRectF(bx, by, bw, bh), 4, 4)
            fill_w = max(0.0, (bw - 2.0) * pct)
            if fill_w > 0.8:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(color.red(), color.green(), color.blue(), 44))
                painter.drawRoundedRect(QRectF(bx + 1, by + 1, fill_w, bh - 2), 4, 4)
                painter.setBrush(QColor(color.red(), color.green(), color.blue(), 202))
                painter.drawRoundedRect(QRectF(bx + 1, by + 1, max(1.4, fill_w - 1), bh - 2), 4, 4)
                painter.setBrush(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 28))
                painter.drawRoundedRect(QRectF(bx + 2, by + 2, max(1.0, min(fill_w * 0.20, 18.0)), bh - 4), 3, 3)
                # a tiny paint-marker end cap makes the active value easier to see.
                cap = QColor(color); cap.setAlpha(122)
                painter.setBrush(cap)
                painter.drawEllipse(QPointF(bx + 1 + fill_w, by + bh * 0.5), 2.0, 2.0)

        left = x + 20
        right = x + w - 20
        inner_w = right - left
        value_w = 60
        bar_w = inner_w - value_w - 10

        # Pull the content closer to the title and keep the whole block compact.
        # More compact vertical layout: tighter spacing, everything nudged upward,
        # and LIMIT safely inside the frame.
        top = y + 30
        state_label_y = top
        state_value_y = top + 14
        state_reason_y = top + 48
        sep1_y = top + 64
        flow_label_y = top + 72
        flow_bar_y = top + 91
        sep2_y = top + 116
        slip_label_y = top + 124
        slip_bar_y = top + 143
        sep3_y = top + 184
        limit_label_y = top + 191
        limit_bar_y = top + 208

        self.draw_street_label(painter, left, state_label_y - 2, "CAR STATUS", STREET_CORAL, max_w=150, compact=True)

        painter.setFont(QFont("Arial Black", 26))
        # Clean paint-word treatment: readable, but not a huge dirty poster word.
        self.draw_sticker_slash(painter, left - 8, state_value_y + 0, 188, 32, accent, 58)
        glow = QColor(accent); glow.setAlpha(96)
        painter.setPen(glow)
        painter.drawText(QRectF(left + 3, state_value_y + 3, inner_w, 34), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.drift_state)
        painter.setPen(accent)
        painter.drawText(QRectF(left, state_value_y - 2, inner_w, 36), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.drift_state)
        self.draw_marker_line(painter, left + 1, state_value_y + 35, left + 158, state_value_y + 28, accent, 3.6, 192)
        self.draw_graffiti_arrow(painter, left + 136, state_value_y + 26, left + 168, state_value_y + 17, accent, 2.1, 104)
        self.draw_clean_spray(painter, left + 170, state_value_y + 17, accent, 0.70, 34)
        self.draw_graffiti_cross(painter, left + 174, state_value_y + 9, accent, 0.86, 82)
        self.draw_halftone_dots(painter, right - 48, state_label_y + 4, STREET_CORAL, rows=3, cols=4, spacing=4.2, radius=0.95, alpha=24)

        painter.setFont(QFont("Bahnschrift", 8, QFont.Weight.Bold))
        painter.setPen(QColor(238, 250, 255, 178))
        painter.drawText(QRectF(left, state_reason_y, inner_w, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.state_reason)

        painter.setPen(QPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 42), 1.15))
        painter.drawLine(QPointF(left, sep1_y), QPointF(right, sep1_y))

        # DRIFT FLOW gauge
        painter.setFont(QFont("Bahnschrift", 11, QFont.Weight.Bold))
        painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 224))
        painter.drawText(QRectF(left, flow_label_y, 118, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "DRIFT FLOW")
        quality_col = QColor(STREET_MINT) if self.flow_quality_label in ("SMOOTH", "LOCKED") else QColor(STREET_OFFWHITE)
        if self.flow_quality_label == "CHASE":
            quality_col = QColor(STREET_AMBER)
        quality_col.setAlpha(230)
        self.draw_marker_line(painter, left + 1, flow_label_y + 17, left + 78, flow_label_y + 14, quality_col, 1.8, 78)
        self.draw_sticker_slash(painter, left + 116, flow_label_y + 3, 58, 12, quality_col, 14)
        painter.setFont(QFont("Arial Black", 9))
        painter.setPen(quality_col)
        painter.drawText(QRectF(left + 120, flow_label_y, 74, 17), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.flow_quality_label)
        flow_bar_x = left
        flow_bar_h = 12
        flow_col = QColor(STREET_MINT) if self.flow_quality_label in ("SMOOTH", "LOCKED") else QColor(STREET_AMBER)
        metric_bar(flow_bar_x, flow_bar_y, bar_w, flow_bar_h, self.flow_pct, flow_col, 100.0)
        self.draw_graffiti_arrow(painter, flow_bar_x + bar_w - 8, flow_bar_y - 4, flow_bar_x + bar_w + 10, flow_bar_y - 6, flow_col, 1.2, 44)
        painter.setFont(QFont("Bahnschrift", 13, QFont.Weight.Bold))
        painter.setPen(flow_col)
        painter.drawText(QRectF(flow_bar_x + bar_w + 10, flow_bar_y - 3, value_w, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{round(self.flow_pct):d}%")

        painter.setPen(QPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 22), 0.9))
        painter.drawLine(QPointF(left + 6, sep2_y), QPointF(right - 6, sep2_y))

        # REAR SLIP gauges (left / right rear tires)
        painter.setFont(QFont("Bahnschrift", 10, QFont.Weight.Bold))
        painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 212))
        painter.drawText(QRectF(left, slip_label_y, 132, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "REAR SLIP")
        slip_bar_x = left + 28
        slip_bar_h = 10
        slip_value_rl = clamp(self.rear_slip_rl / REAR_SLIP_DISPLAY_MAX * 100.0, 0.0, 100.0)
        slip_value_rr = clamp(self.rear_slip_rr / REAR_SLIP_DISPLAY_MAX * 100.0, 0.0, 100.0)
        slip_row1_y = slip_bar_y - 1
        slip_row2_y = slip_bar_y + 16
        lr_label_w = 24
        rear_bar_w = max(40.0, bar_w - 28)
        painter.setFont(QFont("Bahnschrift", 8, QFont.Weight.Bold))
        painter.setPen(QColor(232, 248, 255, 164))
        painter.drawText(QRectF(left, slip_row1_y - 1, lr_label_w, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "RL")
        painter.drawText(QRectF(left, slip_row2_y - 1, lr_label_w, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "RR")
        metric_bar(slip_bar_x, slip_row1_y, rear_bar_w, slip_bar_h, slip_value_rl, QColor(STREET_MINT), 100.0)
        metric_bar(slip_bar_x, slip_row2_y, rear_bar_w, slip_bar_h, slip_value_rr, QColor(STREET_AMBER), 100.0)
        painter.setFont(QFont("Bahnschrift", 12, QFont.Weight.Bold))
        painter.setPen(QColor(126, 249, 214, 236))
        painter.drawText(QRectF(slip_bar_x + rear_bar_w + 10, slip_row1_y - 2, value_w, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{self.rear_slip_rl:.2f}")
        painter.setPen(QColor(255, 142, 97, 236))
        painter.drawText(QRectF(slip_bar_x + rear_bar_w + 10, slip_row2_y - 2, value_w, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{self.rear_slip_rr:.2f}")

        painter.setPen(QPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 22), 0.9))
        painter.drawLine(QPointF(left + 6, sep3_y), QPointF(right - 6, sep3_y))

        # LIMIT gauge (replaces the old footer readout)
        limit_value = clamp(self.spin_risk, 0.0, 100.0)
        limit_col = QColor(STREET_MINT)
        if self.spin_label == "EDGE":
            limit_col = QColor(STREET_AMBER)
        elif self.spin_label == "RISK":
            limit_col = QColor(244, 118, 48)
        elif self.spin_label == "MAX":
            limit_col = QColor(255, 219, 95)
        painter.setFont(QFont("Bahnschrift", 12, QFont.Weight.Bold))
        painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 220))
        painter.drawText(QRectF(left, limit_label_y, 54, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "LIMIT")
        self.draw_sticker_slash(painter, left + 50, limit_label_y + 2, 70, 15, limit_col, 14)
        state_col = QColor(limit_col)
        if self.spin_label == "SAFE":
            state_col = QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 156)
        else:
            state_col.setAlpha(226)
        self.draw_marker_line(painter, left + 1, limit_label_y + 18, left + 96, limit_label_y + 15, limit_col, 2.2, 102)
        painter.setFont(QFont("Arial Black", 12))
        painter.setPen(state_col)
        painter.drawText(QRectF(left + 55, limit_label_y - 1, 76, 19), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.spin_label)
        if self.spin_label != "SAFE":
            self.draw_halftone_dots(painter, left + 128, limit_label_y + 4, limit_col, rows=2, cols=3, spacing=3.7, radius=0.76, alpha=18)
        limit_bar_x = left
        limit_bar_h = 12
        metric_bar(limit_bar_x, limit_bar_y, bar_w, limit_bar_h, limit_value, limit_col, 100.0)
        self.draw_graffiti_arrow(painter, limit_bar_x + bar_w - 6, limit_bar_y + 15, limit_bar_x + bar_w + 10, limit_bar_y + 12, limit_col, 1.25, 52)
        self.draw_graffiti_cross(painter, limit_bar_x - 10, limit_bar_y + 6, limit_col, 0.64, 46)
        painter.setFont(QFont("Bahnschrift", 15, QFont.Weight.Bold))
        painter.setPen(limit_col)
        painter.drawText(QRectF(limit_bar_x + bar_w + 10, limit_bar_y - 5, value_w, 22), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{round(self.spin_risk):d}%")


    def draw_style_panel(self, painter):
        x, y, w, h = self.style_panel_geometry()
        self.draw_cyber_panel(painter, x, y, w, h, None, STREET_CORAL, 38)

        # RUN STYLE is now an evaluation / flavor panel only.
        # Detailed analysis remains in CAR STATUS, so no HOLD/LIMIT duplicate here.
        self.draw_street_label(painter, x + 18, y + 8, "RUN STYLE", STREET_CORAL, max_w=150, compact=True)

        style_color = QColor(STREET_OFFWHITE)
        if self.style_label in ("DANGER", "EDGE"):
            style_color = QColor(STREET_AMBER)
        elif self.style_label in ("DEEP", "WILD"):
            style_color = QColor(STREET_CORAL)
        elif self.style_label in ("SAVE", "SMOOTH"):
            style_color = QColor(STREET_MINT)

        # Main style tag.
        painter.setFont(QFont("Arial Black", 18))
        shadow = QColor(0, 0, 0, 112)
        self.draw_sticker_slash(painter, x + 20, y + 47, 126, 18, style_color, 17)
        self.draw_halftone_dots(painter, x + 146, y + 48, style_color, rows=2, cols=4, spacing=4.0, radius=0.78, alpha=16)
        painter.setPen(shadow)
        painter.drawText(QRectF(x + 24, y + 40, 166, 30).translated(1, 1), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.style_label)
        painter.setPen(style_color)
        painter.drawText(QRectF(x + 24, y + 40, 166, 30), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.style_label)
        self.draw_marker_line(painter, x + 25, y + 70, x + 132, y + 66, STREET_CORAL, 2.0, 100)
        self.draw_graffiti_arrow(painter, x + 136, y + 68, x + 154, y + 64, style_color, 1.25, 52)

        # Star feel remains, but it is based on STYLE score impression, not a repeated status readout.
        angle_score = clamp(abs(self.display_angle) / 60.0 * 100.0, 0.0, 100.0)
        line_score = clamp(0.58 * self.flow_pct + 0.42 * angle_score, 0.0, 100.0)
        rhythm_score = clamp(100.0 - abs(self.steer_pct) * 0.22 + self.flow_pct * 0.28, 0.0, 100.0)
        commit_score = clamp(angle_score * 0.64 + min(self.hold_seconds, 8.0) / 8.0 * 36.0, 0.0, 100.0)
        style_score = clamp((line_score + rhythm_score + commit_score) / 3.0, 0.0, 100.0)
        stars = 1 + int(clamp(style_score / 25, 0, 4))

        painter.setFont(QFont("Arial Black", 15))
        for i in range(5):
            painter.setPen(QColor(STREET_AMBER.red(), STREET_AMBER.green(), STREET_AMBER.blue(), 205 if i < stars else 54))
            painter.drawText(QRectF(x + 176 + i * 22, y + 47, 20, 24), Qt.AlignmentFlag.AlignCenter, "★")

        # Flavor label: short, cinematic, not duplicate telemetry.
        if style_score >= 82:
            run_tag = "EDGE RUN"
        elif commit_score >= 74:
            run_tag = "COMMIT"
        elif rhythm_score >= 72:
            run_tag = "RHYTHM"
        elif line_score >= 68:
            run_tag = "CLEAN LINE"
        else:
            run_tag = "BUILD UP"

        painter.setFont(QFont("Bahnschrift", 8, QFont.Weight.Bold))
        painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 118))
        painter.drawText(QRectF(x + 24, y + 82, 86, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "RUN TYPE")
        painter.setFont(QFont("Bahnschrift", 11, QFont.Weight.Bold))
        painter.setPen(style_color)
        painter.drawText(QRectF(x + 106, y + 79, 210, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, run_tag)

        def eval_row(label, value, yy, color):
            label_col = QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 156)
            painter.setFont(QFont("Bahnschrift", 9, QFont.Weight.Bold))
            painter.setPen(label_col)
            painter.drawText(QRectF(x + 24, yy - 2, 70, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)

            bx = x + 94
            bw = 142
            bh = 8
            painter.setPen(QPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 24), 0.85))
            painter.setBrush(QColor(1, 4, 8, 64))
            painter.drawRoundedRect(QRectF(bx, yy + 4, bw, bh), 3, 3)
            fill_w = max(0.0, (bw - 4) * clamp(value, 0.0, 100.0) / 100.0)
            if fill_w > 1.0:
                c = QColor(color); c.setAlpha(196)
                soft = QColor(color); soft.setAlpha(50)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(soft)
                painter.drawRoundedRect(QRectF(bx + 2, yy + 4, fill_w, bh), 3, 3)
                painter.setBrush(c)
                painter.drawRoundedRect(QRectF(bx + 2, yy + 5, fill_w, max(1.0, bh - 2)), 2.2, 2.2)

            painter.setFont(QFont("Bahnschrift", 11, QFont.Weight.Bold))
            value_col = QColor(color); value_col.setAlpha(218)
            painter.setPen(value_col)
            painter.drawText(QRectF(x + 246, yy - 3, 66, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{round(value):02d}")

        eval_row("LINE", line_score, y + 105, QColor(STREET_MINT))
        eval_row("RHYTHM", rhythm_score, y + 128, QColor(STREET_AMBER))
        eval_row("COMMIT", commit_score, y + 151, style_color)

        # Small footer note to make the panel's role obvious.
        painter.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        painter.setPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 88))
        painter.drawText(QRectF(x + 24, y + h - 18, w - 48, 12), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "RUN STYLE / NOT TELEMETRY")
    def popup_drag_hint_visible(self):
        return bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier)

    def draw_hold_meter(self, painter, x, y, w, h, seconds, compact=False):
        pct = clamp(seconds / 8.0 * 100.0, 0.0, 100.0)
        hold_color = hold_color_for_seconds(seconds)

        bg = QColor(1, 4, 8, 118 if not compact else 92)
        edge = QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 36 if not compact else 26)
        painter.setPen(QPen(edge, 1.0))
        painter.setBrush(bg)
        painter.drawRoundedRect(QRectF(x, y, w, h), 3, 3)

        fill_w = max(0.0, (w - 4) * pct / 100.0)
        if fill_w > 1.0:
            grad = QLinearGradient(x + 2, y, x + w - 2, y)
            base = QColor(hold_color)
            soft = QColor(hold_color)
            soft.setAlpha(72 if compact else 86)
            strong = QColor(hold_color)
            strong.setAlpha(210 if compact else 232)
            grad.setColorAt(0.00, soft)
            grad.setColorAt(0.55, strong)
            grad.setColorAt(1.00, QColor(255, 252, 226, 225) if seconds >= 8.0 else strong)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(grad)
            painter.drawRoundedRect(QRectF(x + 2, y + 2, fill_w, max(1.0, h - 4)), 2.2, 2.2)

        tick_alpha = 62 if not compact else 42
        tick_pen = QPen(QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), tick_alpha), 0.9)
        painter.setPen(tick_pen)
        for mark in (3.0, 5.0, 8.0):
            tx = x + 2 + (w - 4) * clamp(mark / 8.0, 0.0, 1.0)
            painter.drawLine(QPointF(tx, y + 2), QPointF(tx, y + h - 2))

        if seconds >= 5.0 and not compact:
            self.draw_marker_line(painter, x + w * 0.18, y - 4, x + w * 0.82, y - 7, hold_color, 2.0, 94)
        if seconds >= 8.0 and not compact:
            self.draw_clean_spray(painter, x + w + 8, y + h * 0.5, hold_color, 0.58, 18)
            self.draw_graffiti_cross(painter, x + w + 17, y + h * 0.5 - 1, hold_color, 0.70, 58)

    def draw_popup_drag_hint(self, painter, x, y, w, h, label, accent):
        """Alt-only relocation guide for text-only popup panels.
        This keeps the normal stream overlay clean, but gives the user a real
        target when a popup has no active text.
        """
        if not self.popup_drag_hint_visible():
            return

        hint_color = QColor(accent)
        hint_color.setAlpha(POPUP_EMPTY_DRAG_HINT_ALPHA)
        fill_color = QColor(accent)
        fill_color.setAlpha(28)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(fill_color)
        pen = QPen(hint_color, 1.4)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRoundedRect(QRectF(x + 4, y + 4, w - 8, h - 8), 10, 10)

        painter.setFont(QFont("Arial Black", 10))
        painter.setPen(hint_color)
        painter.drawText(QRectF(x, y + h * 0.5 - 12, w, 24), Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()


    def draw_popup_tech_shell(self, painter, rect, accent, label="EVENT", hero=False):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        x = rect.x()
        y = rect.y()
        w = rect.width()
        h = rect.height()

        shadow_rect = rect.translated(0, 4 if hero else 3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 52 if hero else 40))
        painter.drawRoundedRect(shadow_rect, 14, 14)

        glass_alpha = 92 if hero else 74
        border_alpha = 128 if hero else 104
        accent_alpha = 204 if hero else 176

        painter.setBrush(QColor(4, 10, 17, glass_alpha))
        painter.setPen(QPen(QColor(240, 247, 252, border_alpha), 1.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawRoundedRect(rect, 14, 14)

        # Open-corner technical frame.
        corner = 24 if hero else 20
        frame = QColor(240, 247, 252, border_alpha)
        painter.setPen(QPen(frame, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(x + 12, y + 9), QPointF(x + 12 + corner, y + 9))
        painter.drawLine(QPointF(x + 9, y + 12), QPointF(x + 9, y + 12 + corner))
        painter.drawLine(QPointF(x + w - 12 - corner, y + 9), QPointF(x + w - 12, y + 9))
        painter.drawLine(QPointF(x + w - 9, y + 12), QPointF(x + w - 9, y + 12 + corner))
        painter.drawLine(QPointF(x + 9, y + h - 12 - corner), QPointF(x + 9, y + h - 12))
        painter.drawLine(QPointF(x + 12, y + h - 9), QPointF(x + 12 + corner, y + h - 9))
        painter.drawLine(QPointF(x + w - 12 - corner, y + h - 9), QPointF(x + w - 12, y + h - 9))
        painter.drawLine(QPointF(x + w - 9, y + h - 12 - corner), QPointF(x + w - 9, y + h - 12))

        accent_col = QColor(accent)
        accent_col.setAlpha(accent_alpha)
        accent_soft = QColor(accent)
        accent_soft.setAlpha(56 if hero else 42)

        # Accent rails
        painter.setPen(QPen(accent_soft, 4.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(x + 28, y + h - 13), QPointF(x + w - 28, y + h - 13))
        painter.setPen(QPen(accent_col, 2.0 if hero else 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(x + 28, y + h - 13), QPointF(x + min(w * (0.70 if hero else 0.62), w - 28), y + h - 13))

        # Small label and micro details.
        chip_w = 116 if hero else 104
        chip_h = 18
        chip = QRectF(x + 18, y + 13, chip_w, chip_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(5, 11, 19, 120))
        painter.drawRoundedRect(chip, 6, 6)
        painter.setPen(QPen(accent_col, 1.05, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(chip, 6, 6)

        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        painter.setPen(QColor(241, 247, 252, 230))
        painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, label)

        painter.setPen(QColor(214, 229, 240, 92))
        painter.drawText(QRectF(x + w - 96, y + 14, 78, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "093 LAB")
        painter.setPen(QPen(accent_soft, 1.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(x + 148, y + 22), QPointF(x + 182, y + 22))
        painter.drawLine(QPointF(x + w - 108, y + 22), QPointF(x + w - 104, y + 22))
        painter.drawLine(QPointF(x + w - 100, y + 22), QPointF(x + w - 96, y + 22))

        # Subtle right-side dot field for motion.
        dots = 4 if hero else 3
        base_x = x + w - 40
        base_y = y + (h * 0.5 - (dots - 1) * 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 46 if hero else 34))
        for row in range(dots):
            for col in range(2):
                painter.drawEllipse(QPointF(base_x - col * 8, base_y + row * 8), 1.3, 1.3)

        painter.restore()

    def draw_popup_text_layers(self, painter, text_rect, visible_text, accent, hero=False):
        accent_glow = QColor(accent)
        accent_glow.setAlpha(104 if hero else 78)

        # Soft accent haze
        painter.setPen(accent_glow)
        for ox, oy in ((-3, 0), (3, 0), (0, -3), (0, 3), (-2, -2), (2, 2)):
            painter.drawText(text_rect.translated(ox, oy), Qt.AlignmentFlag.AlignCenter, visible_text)

        # Crisp white body
        painter.setPen(QColor(255, 255, 255, 252))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, visible_text)

        # Tiny highlight pass
        painter.setPen(QColor(255, 255, 255, 60))
        painter.drawText(text_rect.translated(0, -1), Qt.AlignmentFlag.AlignCenter, visible_text)



    def draw_popup(self, painter):
        x, y, w, h = self.popup_panel_geometry()

        if not self.popup_text:
            self.draw_popup_drag_hint(painter, x, y, w, h, "POPUP MOVE", QColor(STREET_CORAL))
            return

        visible_text = self.popup_text

        color_map = {
            "ENTRY!": QColor(255, 219, 95, 242),
            "SMOKE RUN!": QColor(STREET_AMBER.red(), STREET_AMBER.green(), STREET_AMBER.blue(), 242),
            "BIG ANGLE!": QColor(STREET_MINT.red(), STREET_MINT.green(), STREET_MINT.blue(), 242),
            "FULL LOCK!": QColor(255, 120, 85, 242),
            "LIMIT!": QColor(255, 82, 120, 242),
            "CHASE LINE!": QColor(117, 233, 255, 242),
            "HOLD!": QColor(255, 236, 120, 242),
            "CLEAN!": QColor(237, 242, 248, 242),
            "EDGE!": QColor(255, 111, 92, 242),
            "SPIN SAVE!": QColor(255, 105, 120, 244),
        }
        accent = color_map.get(visible_text, QColor(245, 248, 255, 242))
        hero_popup = self.is_hero_popup(visible_text)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        inset_x = 10
        inset_y = 10 if hero_popup else 15
        shell_rect = QRectF(x + inset_x, y + inset_y, w - inset_x * 2, h - (20 if hero_popup else 30))

        # Background/frame removed by request. Keep text sizing and layout unchanged.
        underline_y = shell_rect.bottom() - 13
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 176), 2.8 if hero_popup else 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(shell_rect.left() + 110, underline_y), QPointF(shell_rect.right() - 44, underline_y))
        painter.setPen(QPen(QColor(248, 250, 252, 112), 1.25, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(shell_rect.left() + 132, underline_y - 5), QPointF(shell_rect.left() + 176, underline_y - 5))

        if hero_popup:
            font_short = int(self.hud_config.get("popup_hero_font_size", 34))
            font_long = int(self.hud_config.get("popup_hero_font_size_long", 30))
            painter.setFont(QFont("Arial Black", font_short if len(visible_text) <= 11 else font_long))
            text_rect = QRectF(shell_rect.left() + 16, shell_rect.top() + 18, shell_rect.width() - 32, shell_rect.height() - 22)
        else:
            font_short = int(self.hud_config.get("popup_normal_font_size", 25))
            font_long = int(self.hud_config.get("popup_normal_font_size_long", 21))
            painter.setFont(QFont("Arial Black", font_short if len(visible_text) <= 12 else font_long))
            text_rect = QRectF(shell_rect.left() + 14, shell_rect.top() + 15, shell_rect.width() - 28, shell_rect.height() - 18)

        self.draw_popup_text_layers(painter, text_rect, visible_text, accent, hero_popup)
        painter.restore()

    def draw_operation_popup(self, painter):
        if not bool(self.hud_config.get("operation_popup_enabled", True)):
            return
        x, y, w, h = self.operation_popup_panel_geometry()
        if not self.operation_popup_text:
            self.draw_popup_drag_hint(painter, x, y, w, h, "OPERATION MOVE", QColor(255, 156, 64))
            return

        color_map = {
            "HANDBRAKE!": QColor(255, 168, 64, 248),
            "CLUTCH KICK!": QColor(184, 118, 255, 248),
            "FOOT BRAKE!": QColor(255, 96, 88, 248),
        }
        visible_text = self.operation_popup_text
        accent = color_map.get(visible_text, QColor(245, 248, 255, 242))

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        shell_rect = QRectF(x + 14, y + 14, w - 28, h - 24)

        # Text-only operation popup: no frame / no solid background, but more readable and punchy.
        accent_soft = QColor(accent)
        accent_soft.setAlpha(42)
        accent_core = QColor(accent)
        accent_core.setAlpha(158)

        mid_y = shell_rect.center().y() + 7
        painter.setPen(QPen(accent_soft, 3.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(shell_rect.left() + 88, shell_rect.bottom() - 12), QPointF(shell_rect.right() - 38, shell_rect.bottom() - 12))
        painter.setPen(QPen(accent_core, 2.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(shell_rect.left() + 98, shell_rect.bottom() - 12), QPointF(shell_rect.right() - 72, shell_rect.bottom() - 12))
        painter.setPen(QPen(accent_core, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(shell_rect.left() + 18, mid_y), QPointF(shell_rect.left() + 54, mid_y - 4))
        painter.drawLine(QPointF(shell_rect.right() - 54, mid_y + 4), QPointF(shell_rect.right() - 18, mid_y))
        painter.setPen(QPen(QColor(248, 250, 252, 84), 1.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(shell_rect.left() + 34, mid_y + 9), QPointF(shell_rect.left() + 50, mid_y + 7))
        painter.drawLine(QPointF(shell_rect.right() - 50, mid_y - 7), QPointF(shell_rect.right() - 34, mid_y - 9))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 24))
        painter.drawEllipse(QPointF(shell_rect.left() + 28, mid_y), 6.0, 6.0)
        painter.drawEllipse(QPointF(shell_rect.right() - 28, mid_y), 6.0, 6.0)

        painter.setFont(QFont("Arial Black", 28 if len(visible_text) <= 12 else 24))
        text_rect = QRectF(shell_rect.left() + 18, shell_rect.top() + 10, shell_rect.width() - 36, shell_rect.height() - 12)
        self.draw_popup_text_layers(painter, text_rect, visible_text, accent, hero=True)

        painter.restore()
    def draw_text_block(self, painter):
        abs_angle = abs(self.display_angle)
        rate = rating_for_angle(abs_angle)
        color = color_for_angle(abs_angle)
        layout = self._layout()

        center_tick = self.curve_point(0.0, layout)
        # LIVE95: keep LOW / GOD / CAT at the LIVE94 height even though the gauge moved up.
        rate_y = min(center_tick.y() + 72, self.height() - 66)
        rate_rect = QRectF(layout.cx - 126, rate_y, 252, 58)
        if abs_angle > 60:
            word = self.god_word
            font_size = 34 if word == "GOD" else 34
            painter.setFont(QFont("Arial Black", int(font_size * 1.2), QFont.Weight.Black))

            core = QColor(255, 226, 78)
            outer = QColor(255, 166, 28)
            hot = QColor(255, 250, 215)
            shadow = QColor(60, 34, 0, 150)

            for spread, alpha, glow_color in [(5, 22, outer), (3, 45, outer), (2, 76, core)]:
                gc = QColor(glow_color)
                gc.setAlpha(alpha)
                painter.setPen(gc)
                for dx, dy in ((-spread, 0), (spread, 0), (0, -spread), (0, spread)):
                    painter.drawText(rate_rect.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, word)

            self.draw_sticker_slash(painter, rate_rect.x() + 40, rate_rect.y() + 17, 170, 28, core, 26)
            self.draw_halftone_dots(painter, rate_rect.x() + 176, rate_rect.y() + 14, outer, rows=3, cols=4, spacing=4.1, radius=0.86, alpha=20)
            painter.setPen(shadow)
            painter.drawText(rate_rect.translated(1, 2), Qt.AlignmentFlag.AlignCenter, word)
            painter.setPen(hot)
            painter.drawText(rate_rect, Qt.AlignmentFlag.AlignCenter, word)
            self.draw_marker_line(painter, rate_rect.x() + 78, rate_rect.y() + 46, rate_rect.x() + 184, rate_rect.y() + 42, outer, 2.4, 96)
            self.draw_graffiti_arrow(painter, rate_rect.x() + 46, rate_rect.y() + 42, rate_rect.x() + 70, rate_rect.y() + 38, outer, 1.6, 64)
            self.draw_graffiti_cross(painter, rate_rect.x() + 190, rate_rect.y() + 22, core, 0.76, 54)
        else:
            painter.setFont(QFont("Bahnschrift", 29, QFont.Weight.Black))
            # LIVE109: clean sticker-like splash behind the rating word.
            self.draw_sticker_slash(painter, rate_rect.x() + 42, rate_rect.y() + 18, 168, 26, color, 30)
            outer_glow = QColor(color)
            outer_glow.setAlpha(34)
            mid_glow = QColor(color)
            mid_glow.setAlpha(76)
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                painter.setPen(outer_glow)
                painter.drawText(rate_rect.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, rate)
            for dx, dy in ((-1, 0), (1, 0)):
                painter.setPen(mid_glow)
                painter.drawText(rate_rect.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, rate)
            painter.setPen(color)
            painter.drawText(rate_rect, Qt.AlignmentFlag.AlignCenter, rate)
            self.draw_marker_line(painter, rate_rect.x() + 70, rate_rect.y() + 46, rate_rect.x() + 184, rate_rect.y() + 42, color, 2.3, 104)
            self.draw_graffiti_arrow(painter, rate_rect.x() + 44, rate_rect.y() + 42, rate_rect.x() + 68, rate_rect.y() + 38, color, 1.5, 58)
            self.draw_halftone_dots(painter, rate_rect.x() + 176, rate_rect.y() + 15, color, rows=3, cols=4, spacing=4.0, radius=0.82, alpha=22)


        painter.setFont(QFont("Bahnschrift", 11, QFont.Weight.Bold))
        left_color = QColor(STREET_OFFWHITE.red(), STREET_OFFWHITE.green(), STREET_OFFWHITE.blue(), 210)
        right_color = QColor(STREET_CORAL.red(), STREET_CORAL.green(), STREET_CORAL.blue(), 220)
        lp = self.curve_point(-50.0 / 60.0, layout)
        painter.setPen(left_color)
        painter.drawText(QRectF(lp.x() - 48, lp.y() - 49, 96, 20), Qt.AlignmentFlag.AlignCenter, "LEFT")
        rp = self.curve_point(50.0 / 60.0, layout)
        painter.setPen(right_color)
        painter.drawText(QRectF(rp.x() - 52, rp.y() - 49, 104, 20), Qt.AlignmentFlag.AlignCenter, "RIGHT")

        angle_anchor = self.curve_point(0.88, layout)
        angle_font = QFont("Arial Black", 58)
        painter.setFont(angle_font)
        angle_text = f"{int(round(self.display_angle)):+d}°" if abs(self.display_angle) >= 0.5 else "0°"
        angle_y = min(angle_anchor.y() + 56, self.height() - 66)
        angle_rect = QRectF(angle_anchor.x() - 14, angle_y, 222, 66)
        angle_core = QColor(255, 255, 255, 255)
        angle_accent = QColor(255, 112, 142, 255)

        # Compact contrast plate so the number reads better against gameplay.
        plate_rect = QRectF(angle_rect.right() - 168, angle_rect.y() + 8, 164, 44)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 118))
        painter.drawRoundedRect(plate_rect.translated(0, 1), 9, 9)
        painter.setBrush(QColor(16, 18, 22, 148))
        painter.drawRoundedRect(plate_rect, 9, 9)
        painter.setPen(QPen(QColor(angle_accent.red(), angle_accent.green(), angle_accent.blue(), 78), 1.3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(plate_rect.adjusted(0.6, 0.6, -0.6, -0.6), 9, 9)

        # Higher-energy numeric stack: deeper shadow, stronger halo, crisp white core.
        for dx, dy, col in (
            (4, 4, QColor(0, 0, 0, 208)),
            (2, 3, QColor(0, 0, 0, 146)),
            (-4, 0, QColor(angle_accent.red(), angle_accent.green(), angle_accent.blue(), 112)),
            (4, 0, QColor(angle_accent.red(), angle_accent.green(), angle_accent.blue(), 112)),
            (0, -3, QColor(angle_accent.red(), angle_accent.green(), angle_accent.blue(), 168)),
            (0, 3, QColor(angle_accent.red(), angle_accent.green(), angle_accent.blue(), 118)),
            (-1, -1, QColor(255, 246, 250, 104)),
        ):
            painter.setPen(col)
            painter.drawText(angle_rect.translated(dx, dy), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, angle_text)
        painter.setPen(angle_core)
        painter.drawText(angle_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, angle_text)
        # Stronger accent under the numeric angle only.
        self.draw_marker_line(painter, angle_rect.x() + 6, angle_rect.y() + 58, angle_rect.x() + 146, angle_rect.y() + 52, angle_accent, 4.8, 220)
        self.draw_graffiti_arrow(painter, angle_rect.x() + 136, angle_rect.y() + 24, angle_rect.x() + 178, angle_rect.y() + 14, angle_accent, 2.7, 146)
        self.draw_clean_spray(painter, angle_rect.x() + 126, angle_rect.y() + 48, angle_accent, 0.82, 42)
        self.draw_graffiti_cross(painter, angle_rect.x() + 176, angle_rect.y() + 42, angle_accent, 1.02, 104)

        hold_anchor = self.curve_point(-0.96, layout)
        hold_color = hold_color_for_seconds(self.hold_seconds)
        hold_label_y = min(hold_anchor.y() + 52, self.height() - 92)
        hold_value_y = min(hold_anchor.y() + 74, self.height() - 68)
        hold_meter_y = min(hold_anchor.y() + 121, self.height() - 24)

        painter.setFont(QFont("Bahnschrift", 12, QFont.Weight.Bold))
        painter.setPen(QColor(235, 246, 255, 178))
        painter.drawText(QRectF(hold_anchor.x() - 42, hold_label_y, 82, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "HOLD")
        self.draw_marker_line(painter, hold_anchor.x() - 43, hold_label_y + 20, hold_anchor.x() + 5, hold_label_y + 18, hold_color, 1.9, 84)
        self.draw_halftone_dots(painter, hold_anchor.x() + 8, hold_label_y + 8, hold_color, rows=2, cols=3, spacing=3.8, radius=0.76, alpha=18)

        painter.setFont(QFont("Arial Black", 38))
        painter.setPen(QColor(0, 0, 0, 110))
        painter.drawText(QRectF(hold_anchor.x() - 30, hold_value_y, 156, 46).translated(1, 2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{self.hold_seconds:.1f}s")
        value_col = QColor(hold_color)
        value_col.setAlpha(242)
        painter.setPen(value_col)
        painter.drawText(QRectF(hold_anchor.x() - 30, hold_value_y, 156, 46), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{self.hold_seconds:.1f}s")

        self.draw_hold_meter(painter, hold_anchor.x() - 36, hold_meter_y, 128, 10, self.hold_seconds, compact=False)

        connected = self.last_packet_ms < 500 and self.packet_count > 0
        if self.udp_error:
            status = "UDP PORT ERROR / DEMO MODE"
            pen_color = QColor(255, 145, 58, 110)
        elif connected:
            status = "FH6 LIVE"
            pen_color = QColor(130, 245, 255, 90)
        else:
            status = "WAITING FH6 DATA  |  SPACE DEMO"
            pen_color = QColor(130, 245, 255, 58)

        painter.setFont(QFont("Bahnschrift", 8, QFont.Weight.Bold))
        painter.setPen(pen_color)
        painter.drawText(QRectF(layout.cx - 260, layout.cy + 138, 520, 18), Qt.AlignmentFlag.AlignCenter, status)
    def _splash_elapsed(self):
        return max(0.0, time.monotonic() - getattr(self, "splash_start_time", time.monotonic()))

    def _splash_ease(self, t):
        t = clamp(t, 0.0, 1.0)
        return 1.0 - pow(1.0 - t, 3)

    def _draw_splash_line(self, painter, cx, y, half_w, progress, color, width=2.0, alpha=170):
        progress = clamp(progress, 0.0, 1.0)
        if progress <= 0.0:
            return
        col = QColor(color)
        col.setAlpha(int(alpha * progress))
        painter.setPen(QPen(col, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        length = half_w * self._splash_ease(progress)
        painter.drawLine(QPointF(cx - length, y), QPointF(cx + length, y))

    def draw_startup_splash(self, painter):
        if not bool(self.hud_config.get("splash_enabled", True)):
            return False
        elapsed = self._splash_elapsed()
        if elapsed >= self.splash_duration:
            return False

        painter.save()
        W, H = self.width(), self.height()
        cx, cy = W * 0.5, H * 0.49

        # Fade out during the final half-second.
        fade = 1.0
        if elapsed > self.splash_duration - 0.72:
            fade = clamp((self.splash_duration - elapsed) / 0.72, 0.0, 1.0)
        painter.setOpacity(fade)

        # Deep blue-black boot plate.  Not fully opaque so it still feels like HUD glass.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(2, 5, 10, 186))
        painter.drawRect(QRectF(0, 0, W, H))

        # Subtle scan lines / telemetry traces.
        scan_alpha = 9 + int(4 * math.sin(elapsed * 5.2))
        painter.setPen(QPen(QColor(110, 230, 220, scan_alpha), 1.0))
        for i in range(0, int(H), 38):
            offset = (elapsed * 14.0) % 38.0
            y = i + offset
            painter.drawLine(QPointF(W * 0.18, y), QPointF(W * 0.82, y))

        # Main horizontal lines extend before/around the logo.
        top_prog = self._splash_ease((elapsed - 0.25) / 1.45)
        self._draw_splash_line(painter, cx, cy - 62, 120, top_prog, STREET_MINT, 1.2, 82)
        self._draw_splash_line(painter, cx, cy + 58, 104, top_prog * 0.85, STREET_CORAL, 1.0, 48)

        # 093 LAB. typing.
        logo = "093 LAB."
        type_t = clamp((elapsed - 0.85) / 2.05, 0.0, 1.0)
        chars = int(round(type_t * len(logo)))
        typed_logo = logo[:chars]
        cursor_on = int(elapsed * 3.2) % 2 == 0 and elapsed < 3.25
        if cursor_on:
            typed_logo += "_"

        painter.setFont(QFont("Arial Black", 15))
        fm = QFontMetrics(painter.font())
        logo_rect = QRectF(0, cy - 48, W, 24)
        glow_alpha = int(28 * clamp((elapsed - 0.85) / 1.30, 0.0, 1.0))
        painter.setPen(QColor(120, 235, 230, glow_alpha))
        for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            painter.drawText(logo_rect.translated(ox, oy), Qt.AlignmentFlag.AlignCenter, typed_logo)
        painter.setPen(QColor(248, 252, 255, int(214 * clamp((elapsed - 0.90) / 1.35, 0.0, 1.0))))
        painter.drawText(logo_rect, Qt.AlignmentFlag.AlignCenter, typed_logo)

        # DRIFT DATA SYSTEM reveal with bracket lines.
        system_alpha = int(218 * clamp((elapsed - 3.65) / 1.00, 0.0, 1.0))
        sys_prog = self._splash_ease((elapsed - 3.65) / 1.00)
        painter.setFont(QFont("Bahnschrift", 12, QFont.Weight.Bold))
        sys_rect = QRectF(0, cy - 4, W, 24)
        painter.setPen(QColor(220, 236, 246, system_alpha))
        painter.drawText(sys_rect, Qt.AlignmentFlag.AlignCenter, "DRIFT DATA SYSTEM")
        line_col = QColor(STREET_MINT)
        line_col.setAlpha(int(130 * sys_prog))
        painter.setPen(QPen(line_col, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        left_end = cx - 102
        right_start = cx + 102
        seg_len = 54 * sys_prog
        painter.drawLine(QPointF(left_end - seg_len, cy + 13), QPointF(left_end, cy + 13))
        painter.drawLine(QPointF(right_start, cy + 13), QPointF(right_start + seg_len, cy + 13))

        # Tagline fade + orange edge slash.
        tag_alpha = int(206 * clamp((elapsed - 4.35) / 0.75, 0.0, 1.0))
        painter.setFont(QFont("Bahnschrift", 12, QFont.Weight.Bold))
        tag_rect = QRectF(0, cy + 34, W, 22)
        painter.setPen(QColor(255, 232, 205, tag_alpha))
        painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, "TUNED FOR THE EDGE")
        orange_prog = self._splash_ease((elapsed - 4.80) / 0.80)
        self._draw_splash_line(painter, cx, cy + 58, 70, orange_prog, STREET_AMBER, 1.2, 96)

        # Boot log appears last, compact and technical.
        log_alpha = int(120 * clamp((elapsed - 4.90) / 0.70, 0.0, 1.0))
        painter.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        log_x = cx - 94
        log_y = cy + 86
        simhub_state = "OFF"
        simhub_color = QColor(160, 170, 180)
        if getattr(self, "simhub_forward_enabled", False):
            if getattr(self, "simhub_forward_error", ""):
                simhub_state = "ERROR"
                simhub_color = QColor(255, 92, 82)
            elif self.simhub_forward_count > 0:
                simhub_state = "LIVE"
                simhub_color = STREET_MINT
            else:
                simhub_state = "READY"
                simhub_color = STREET_AMBER
        rows = [
            ("HUD LAYER", "READY", STREET_MINT),
            ("SIMHUB OUT", simhub_state, simhub_color),
            ("UDP LINK", "WAITING" if self.packet_count <= 0 else "LIVE", STREET_AMBER if self.packet_count <= 0 else STREET_MINT),
        ]
        for idx, (name, state, color) in enumerate(rows):
            yy = log_y + idx * 13
            painter.setPen(QColor(210, 224, 236, log_alpha))
            painter.drawText(QRectF(log_x, yy, 82, 13), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
            state_col = QColor(color)
            state_col.setAlpha(log_alpha)
            painter.setPen(state_col)
            painter.drawText(QRectF(log_x + 96, yy, 64, 13), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, state)

        # Bottom phrase sequence: ミサキニテマツ -> backspace erase -> Waiting at the edge.....
        phrase_y = cy + 138
        jp_text = "ミサキニテマツ"
        en_text = "Waiting at the edge....."
        cursor_phase = int(elapsed * 2.6) % 2 == 0

        phrase = ""
        phrase_alpha = 0
        phrase_color = QColor(230, 236, 242)

        if elapsed >= 6.20:
            if elapsed < 7.60:
                prog = clamp((elapsed - 6.20) / 1.40, 0.0, 1.0)
                chars = max(0, min(len(jp_text), int(prog * len(jp_text) + 0.5)))
                phrase = jp_text[:chars]
                if cursor_phase and chars < len(jp_text):
                    phrase += "_"
                phrase_alpha = int(190 * clamp((elapsed - 6.10) / 0.45, 0.0, 1.0))
                phrase_color = QColor(242, 246, 250)
            elif elapsed < 8.12:
                # LIVE162A: let ミサキニテマツ linger for a breath before it disappears.
                phrase = jp_text
                linger = clamp((elapsed - 7.60) / 0.52, 0.0, 1.0)
                phrase_alpha = int(190 - 42 * linger)
                phrase_color = QColor(242, 246, 250)
            elif elapsed < 8.95:
                prog = clamp((elapsed - 8.12) / 0.83, 0.0, 1.0)
                remaining = max(0, len(jp_text) - int(prog * len(jp_text) + 0.5))
                phrase = jp_text[:remaining]
                if cursor_phase and remaining > 0:
                    phrase += "_"
                phrase_alpha = int(168 * clamp((8.95 - elapsed) / 0.83, 0.0, 1.0) + 34)
                phrase_color = QColor(225, 230, 236)
            else:
                prog = clamp((elapsed - 9.20) / 2.20, 0.0, 1.0)
                chars = max(0, min(len(en_text), int(prog * len(en_text) + 0.5)))
                typed = en_text[:chars]
                blink_final_dot = chars >= len(en_text) and cursor_phase
                if blink_final_dot and typed.endswith('.'):
                    typed = typed[:-1]
                elif chars < len(en_text) and cursor_phase:
                    typed += "_"
                phrase = typed
                phrase_alpha = int(210 * clamp((elapsed - 9.08) / 0.50, 0.0, 1.0))
                phrase_color = QColor(255, 232, 205)

        if phrase:
            painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            ghost = QColor(80, 210, 210, max(0, int(phrase_alpha * 0.16)))
            painter.setPen(ghost)
            painter.drawText(QRectF(0, phrase_y + 1, W, 18), Qt.AlignmentFlag.AlignCenter, phrase)
            col = QColor(phrase_color)
            col.setAlpha(phrase_alpha)
            painter.setPen(col)
            painter.drawText(QRectF(0, phrase_y, W, 18), Qt.AlignmentFlag.AlignCenter, phrase)

        # Small blinking edge marker.
        if int(elapsed * 2.2) % 2 == 0:
            blink = QColor(STREET_AMBER)
            blink.setAlpha(int(96 * clamp((elapsed - 3.0) / 0.45, 0.0, 1.0)))
            painter.setPen(QPen(blink, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(cx - 146, cy + 86), QPointF(cx - 128, cy + 86))
            painter.drawLine(QPointF(cx + 105, cy + 74), QPointF(cx + 118, cy + 74))

        painter.restore()
        return True

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        if self.draw_startup_splash(painter):
            return

        layout = self._layout()

        if not self.hud_visible:
            self.draw_key_help(painter)
            self.draw_control_notice(painter)
            return

        self.draw_segmented_arc(painter)
        self.draw_curve_ticks(painter)
        self.draw_angle_labels(painter)

        abs_angle = abs(self.display_angle)
        active_t = clamp(abs_angle / 60.0, 0.0, 1.0)
        if abs_angle > 0.08:
            signed_t = active_t if self.display_angle >= 0 else -active_t
            tip = self.curve_point(signed_t, layout)
            self.draw_triangle_marker(painter, tip, signed_t, layout)

        center = self.curve_point(0.0, layout)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 240))
        painter.drawEllipse(center, 3.2, 3.2)
        painter.setBrush(QColor(255, 255, 255, 34))
        painter.drawEllipse(center, 9.5, 9.5)

        if self.panel_visibility.get("input_car", True):
            self.draw_vehicle_info(painter)
            self.draw_core_data(painter)
        if self.panel_visibility.get("map", True):
            self.draw_live_map(painter)
        if self.panel_visibility.get("g_meter", True):
            self.draw_g_meter(painter)
        if self.panel_visibility.get("left", True):
            self.draw_drift_panel(painter)
        if self.panel_visibility.get("style", False):
            self.draw_style_panel(painter)

        self.draw_text_block(painter)
        self.draw_popup(painter)
        self.draw_operation_popup(painter)

        if self.panel_visibility.get("steer", True):
            self.draw_steer_panel(painter)

        self.draw_key_help(painter)
        self.draw_control_notice(painter)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    win = AngleOverlay()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
