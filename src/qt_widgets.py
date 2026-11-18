"""Original lightweight Qt animations using the unchanged Astra brand asset."""
import math
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from src.qt_theme import ACCENT, CYAN, MUTED


class OrbitalLogo(QWidget):
    def __init__(self, icon_path, size=88, reduced_motion=False, parent=None):
        super().__init__(parent)
        self.pixmap = QPixmap(str(icon_path))
        self.phase = 0
        self.reduced_motion = reduced_motion
        self.setFixedSize(size, size)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    def _tick(self):
        if not self.reduced_motion:
            self.phase = (self.phase + 1) % 360
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = self.width() * 0.43
        for offset, color in ((0, ACCENT), (120, CYAN), (240, "#465578")):
            pen = QPen(QColor(color), 1.6, Qt.SolidLine, Qt.RoundCap)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawArc(QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2), (self.phase + offset) * 16, 54 * 16)
        glow = QColor(ACCENT)
        glow.setAlpha(24 + (0 if self.reduced_motion else int(12 * (1 + math.sin(math.radians(self.phase * 2))))))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(center, radius * 0.82, radius * 0.82)
        size = int(self.width() * 0.62)
        target = QRectF(center.x() - size / 2, center.y() - size / 2, size, size)
        painter.drawPixmap(target.toRect(), self.pixmap)


STATE_COLORS = {
    "idle": "#5a6a8c",
    "listening": CYAN,
    "recognizing": ACCENT,
    "speaking": "#7cf2c0",
    "error": "#ff6b7a",
}

STATE_HINTS = {
    "idle": "образ в покое",
    "listening": "слушает",
    "recognizing": "думает",
    "speaking": "говорит",
    "error": "нужна проверка",
}


class CharacterStage(QWidget):
    """Animated 2D stage: layered body/head motion, state glow and speaking frames."""

    fullscreen_requested = Signal()

    def __init__(self, image_path="", name="", speaking_path=None, reduced_motion=False, parent=None,
                 desktop_mode=False, transparent_background=False):
        super().__init__(parent)
        self.setMinimumSize(240 if desktop_mode else 340, 420 if desktop_mode else 520)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.image_path = image_path
        self.speaking_path = speaking_path
        self.name = name
        self.state = "Микрофон выключен"
        self.avatar_state = "idle"
        self.reduced_motion = reduced_motion
        self.desktop_mode = desktop_mode
        self.transparent_background = transparent_background
        self.phase = 0.0
        self._drag_offset = None
        self._idle_pixmap = QPixmap()
        self._speaking_pixmap = QPixmap()
        self._idle_layers = None
        self._speaking_layers = None
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0 if desktop_mode else 20, 0 if desktop_mode else 18, 0 if desktop_mode else 20, 0 if desktop_mode else 16)
        self.layout.addStretch(1)
        self.name_label = None
        self.state_label = None
        if not desktop_mode:
            self.name_label = QLabel(name)
            self.name_label.setObjectName("section")
            self.name_label.setAlignment(Qt.AlignCenter)
            self.layout.addWidget(self.name_label)
            self.state_label = QLabel(self.state)
            self.state_label.setObjectName("muted")
            self.state_label.setAlignment(Qt.AlignCenter)
            self.layout.addWidget(self.state_label)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)
        self.reload(image_path, name, speaking_path)

    def _tick(self):
        if not self.reduced_motion:
            self.phase += 0.033
            self.update()

    def mousePressEvent(self, event):
        if self.desktop_mode and event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.desktop_mode and self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.desktop_mode and event.button() == Qt.LeftButton:
            self._drag_offset = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, _event):
        self.fullscreen_requested.emit()

    def reload(self, image_path, name, speaking_path=None):
        self.image_path = str(image_path)
        self.name = name
        if self.name_label is not None:
            self.name_label.setText(name)
        self._idle_pixmap = QPixmap(self.image_path)
        if speaking_path is not None:
            self.speaking_path = str(speaking_path)
        self._speaking_pixmap = QPixmap(self.speaking_path) if self.speaking_path else QPixmap()
        self._idle_layers = self._prepare_layers(self._idle_pixmap)
        self._speaking_layers = self._prepare_layers(self._speaking_pixmap)
        self.update()

    def _prepare_layers(self, pixmap):
        if pixmap.isNull() or pixmap.height() <= pixmap.width():
            return None
        width = pixmap.width()
        height = pixmap.height()
        head_height = int(height * 0.32)
        body_y = int(height * 0.23)
        return {
            "head": pixmap.copy(QRect(0, 0, width, head_height)),
            "head_ratio": head_height / height,
            "body": pixmap.copy(QRect(0, body_y, width, height - body_y)),
            "body_offset": body_y / height,
        }

    def _active_layers(self):
        if self.avatar_state == "speaking" and self._speaking_layers is not None:
            return self._speaking_layers
        return self._idle_layers

    def set_state(self, text):
        self.state = text
        if self.state_label is not None:
            self.state_label.setText(text)
        lowered = text.casefold()
        if "ошибка" in lowered or "недоступ" in lowered:
            state = "error"
        elif "микрофон выключен" in lowered or "остановлен" in lowered or "пауза" in lowered:
            state = "idle"
        elif "говор" in lowered or "чита" in lowered or "отвеча" in lowered:
            state = "speaking"
        elif "слуш" in lowered or "жду" in lowered:
            state = "listening"
        elif "распозн" in lowered or "дума" in lowered or "переключ" in lowered:
            state = "recognizing"
        else:
            state = "idle"
        if state != self.avatar_state:
            self.avatar_state = state
        self.update()

    def _active_pixmap(self):
        if self.avatar_state == "speaking" and not self._speaking_pixmap.isNull():
            return self._speaking_pixmap
        return self._idle_pixmap

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)

        if not self.transparent_background:
            panel = QPainterPath()
            panel.addRoundedRect(rect, 22, 22)
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            gradient.setColorAt(0.0, QColor("#101623"))
            gradient.setColorAt(1.0, QColor("#080c16"))
            painter.fillPath(panel, QBrush(gradient))

        accent = QColor(STATE_COLORS.get(self.avatar_state, STATE_COLORS["idle"]))
        labels_reserve = 0.0 if self.desktop_mode else 74.0
        stage_margin_x = 8.0 if self.desktop_mode else 14.0
        stage_margin_y = 6.0 if self.desktop_mode else 12.0
        stage = QRectF(rect.left() + stage_margin_x, rect.top() + stage_margin_y, rect.width() - stage_margin_x * 2, rect.height() - labels_reserve - stage_margin_y * 2)
        if stage.height() < 80:
            return
        center_x = stage.center().x()
        floor_y = stage.bottom() - 6

        breathing = 0.0 if self.reduced_motion else math.sin(self.phase * 1.8)
        secondary = 0.0 if self.reduced_motion else math.sin(self.phase * 0.83 + 0.7)
        pulse = 0.5 if self.reduced_motion else 0.5 + 0.5 * math.sin(self.phase * (7.0 if self.avatar_state == "recognizing" else 2.6))

        halo_radius = min(stage.width(), stage.height()) * 0.46
        glow = QRadialGradient(QPointF(center_x, floor_y - halo_radius * 0.75), halo_radius * 1.25)
        glow_color = QColor(accent)
        glow_color.setAlpha(46 + int(30 * pulse) if self.avatar_state in {"listening", "speaking", "recognizing"} else 34)
        glow.setColorAt(0.0, glow_color)
        glow_color.setAlpha(0)
        glow.setColorAt(1.0, glow_color)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(QPointF(center_x, floor_y - halo_radius * 0.75), halo_radius * 1.25, halo_radius * 1.25)

        ring_alpha = 175 if self.avatar_state != "idle" else 92
        ring_speed = 46 if self.avatar_state in {"listening", "recognizing"} else 30
        for index, span in ((0, 112), (1, 82), (2, 58)):
            pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), max(28, ring_alpha - index * 48)), 2.0, Qt.SolidLine, Qt.RoundCap)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            radius = halo_radius * (0.94 + index * 0.105)
            start = int((self.phase * ring_speed + index * 118) % 360)
            painter.drawArc(QRectF(center_x - radius, floor_y - halo_radius * 0.75 - radius, radius * 2, radius * 2), start * 16, span * 16)

        pedestal = QRadialGradient(QPointF(center_x, floor_y), halo_radius * 0.85)
        pedestal_color = QColor(accent)
        pedestal_color.setAlpha(70 if self.avatar_state != "error" else 90)
        pedestal.setColorAt(0.0, pedestal_color)
        pedestal_color.setAlpha(0)
        pedestal.setColorAt(1.0, pedestal_color)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(pedestal))
        painter.drawEllipse(QPointF(center_x, floor_y), halo_radius * 0.85, halo_radius * 0.2)

        if not self.reduced_motion:
            particle_count = 8 if self.avatar_state in {"listening", "speaking", "recognizing"} else 4
            orbit_speed = 2.2 if self.avatar_state in {"listening", "recognizing"} else 1.55
            for index in range(particle_count):
                angle = self.phase * orbit_speed + index * math.tau / particle_count
                particle_x = center_x + math.cos(angle) * halo_radius * (0.54 + 0.045 * math.sin(self.phase * 2.4 + index))
                particle_y = floor_y - halo_radius * 0.76 + math.sin(angle) * halo_radius * (0.95 + 0.045 * math.cos(self.phase * 1.9 + index))
                particle_color = QColor(accent)
                particle_color.setAlpha(82 + int(72 * pulse) if self.avatar_state != "idle" else 52)
                painter.setBrush(particle_color)
                particle_radius = 2.0 + (1.4 if self.avatar_state == "recognizing" else 0.8) * (0.5 + 0.5 * math.sin(self.phase * 4.2 + index))
                painter.drawEllipse(QPointF(particle_x, particle_y), particle_radius, particle_radius)

        pixmap = self._active_pixmap()
        if pixmap.isNull():
            painter.setPen(QColor(MUTED))
            painter.drawText(stage, Qt.AlignCenter, "2D-образ недоступен")
            return
        max_height = stage.height() - 14
        max_width = stage.width()
        scale = min(max_width / pixmap.width(), max_height / pixmap.height())
        motion_scale = 0.014 * breathing + (0.006 * math.sin(self.phase * 10.0) if self.avatar_state == "speaking" else 0.0)
        scale *= 1.0 + (0.0 if self.reduced_motion else motion_scale)
        draw_width = pixmap.width() * scale
        draw_height = pixmap.height() * scale
        bob = 0.0 if self.reduced_motion else 5.0 * breathing + (2.4 * math.sin(self.phase * 10.0) if self.avatar_state == "speaking" else 0.0)
        pose_cycle = 0.0 if self.reduced_motion else math.sin(self.phase * 0.42)
        pose_shift = 7.0 * pose_cycle
        target = QRectF(center_x + pose_shift - draw_width / 2, floor_y - draw_height - 4 - bob, draw_width, draw_height)
        if not self.reduced_motion:
            reflection = QRectF(target.left(), floor_y + 5, draw_width, draw_height * 0.16)
            painter.save()
            painter.setClipRect(QRectF(stage.left(), floor_y + 2, stage.width(), stage.bottom() - floor_y - 2))
            painter.setOpacity(0.10 if self.avatar_state != "error" else 0.06)
            painter.drawPixmap(reflection.toRect(), pixmap)
            painter.restore()
        layers = self._active_layers()
        if self.avatar_state == "error":
            painter.setOpacity(0.82)
        if layers is not None:
            body_top = target.top() + draw_height * layers["body_offset"]
            body_rect = QRectF(target.left(), body_top, draw_width, target.bottom() - body_top)
            painter.save()
            painter.translate(center_x, floor_y - 4)
            body_sway = 0.0 if self.reduced_motion else 0.34 * breathing + 0.22 * secondary + 0.55 * pose_cycle + (0.42 if self.avatar_state == "listening" else 0.0) + (0.28 * math.sin(self.phase * 3.2) if self.avatar_state == "speaking" else 0.0)
            painter.rotate(body_sway)
            painter.translate(-center_x, -(floor_y - 4))
            painter.drawPixmap(body_rect.toRect(), layers["body"])
            painter.restore()

            head_height = draw_height * layers["head_ratio"]
            head_bob = 0.0 if self.reduced_motion else 2.4 * breathing + 1.4 * secondary + (1.5 * math.sin(self.phase * 9.0) if self.avatar_state == "speaking" else 0.0)
            head_rect = QRectF(target.left(), target.top() - head_bob, draw_width, head_height)
            pivot_y = target.top() + head_height * 0.94
            painter.save()
            painter.translate(center_x, pivot_y)
            head_sway = 0.0 if self.reduced_motion else 0.9 * breathing + 0.7 * secondary + 2.4 * pose_cycle
            if self.avatar_state == "listening":
                head_sway += 3.2 * math.sin(self.phase * 2.2)
            elif self.avatar_state == "recognizing":
                head_sway += 1.8 * math.sin(self.phase * 4.5)
            elif self.avatar_state == "speaking":
                head_sway += 1.0 * math.sin(self.phase * 8.0)
            painter.rotate(head_sway)
            painter.translate(-center_x, -pivot_y)
            painter.drawPixmap(head_rect.toRect(), layers["head"])
            painter.restore()
        else:
            painter.save()
            painter.translate(center_x, floor_y - 4)
            sway_degrees = 0.0 if self.reduced_motion else 0.45 * breathing + (0.35 if self.avatar_state == "listening" else 0.0)
            painter.rotate(sway_degrees)
            painter.translate(-center_x, -(floor_y - 4))
            painter.drawPixmap(target.toRect(), pixmap)
            painter.restore()
        painter.setOpacity(1.0)

        indicator_center = QPointF(center_x, target.top() + draw_height * 0.22)
        indicator_radius = max(28.0, draw_width * 0.18)
        if self.avatar_state == "listening":
            pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), 110 + int(70 * pulse)), 2.2, Qt.SolidLine, Qt.RoundCap)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            side = indicator_radius * (0.86 + 0.05 * math.sin(self.phase * 4.0))
            painter.drawArc(QRectF(indicator_center.x() - side, indicator_center.y() - side, side * 2, side * 2), 35 * 16, 58 * 16)
            painter.drawArc(QRectF(indicator_center.x() - side, indicator_center.y() - side, side * 2, side * 2), 267 * 16, 58 * 16)
        elif self.avatar_state == "recognizing":
            painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 82), 1.8, Qt.SolidLine, Qt.RoundCap))
            painter.setBrush(Qt.NoBrush)
            for index in range(3):
                radius = indicator_radius * (0.72 + index * 0.18 + 0.04 * pulse)
                start = int((self.phase * 52 + index * 72) % 360)
                painter.drawArc(QRectF(indicator_center.x() - radius, indicator_center.y() - radius, radius * 2, radius * 2), start * 16, 82 * 16)
        elif self.avatar_state == "speaking":
            pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), 92 + int(58 * pulse)), 2.0, Qt.SolidLine, Qt.RoundCap)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            for side in (-1, 1):
                for index in range(3):
                    arc_width = 12 + index * 8 + 4 * pulse
                    arc_height = 28 + index * 14
                    x = center_x + side * (draw_width * 0.17 + index * 9)
                    y = target.top() + draw_height * 0.30
                    painter.drawArc(QRectF(x - arc_width, y - arc_height / 2, arc_width * 2, arc_height), (35 if side < 0 else 145) * 16, 70 * 16)

        emotion_marks = {
            "listening": "◖ ◗",
            "recognizing": "···",
            "speaking": "♪",
            "error": "!",
        }
        emotion = emotion_marks.get(self.avatar_state)
        if emotion:
            emotion_font = painter.font()
            emotion_font.setPointSize(15)
            emotion_font.setBold(True)
            painter.setFont(emotion_font)
            painter.setPen(QColor(accent.red(), accent.green(), accent.blue(), 150 + int(70 * pulse)))
            emotion_rect = QRectF(target.right() - draw_width * 0.18, target.top() + draw_height * 0.07 + 3 * math.sin(self.phase * 2.0), draw_width * 0.16, 30)
            painter.drawText(emotion_rect, Qt.AlignCenter, emotion)

        if self.avatar_state == "speaking":
            pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), 120 + int(80 * pulse)), 2.2, Qt.SolidLine, Qt.RoundCap)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            mouth_ratio = 0.18 if pixmap.height() > pixmap.width() else 0.30
            mouth_y = target.top() + draw_height * mouth_ratio
            wave_width = 26 + 14 * pulse
            painter.drawArc(QRectF(center_x - wave_width, mouth_y - 8, wave_width * 2, 16), 200 * 16, 140 * 16)
            painter.drawArc(QRectF(center_x - wave_width * 0.65, mouth_y - 5, wave_width * 1.3, 10), 200 * 16, 140 * 16)
