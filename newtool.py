import sys
import os
import subprocess
import re
import cv2
import numpy as np
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QLabel,
    QTextEdit, QFileDialog, QSlider, QMessageBox, QHBoxLayout, 
    QListWidget, QProgressBar, QListWidgetItem, QSplitter,
    QGroupBox, QLineEdit, QCheckBox, QSpinBox, QTabWidget,
    QFormLayout, QGraphicsView, QGraphicsScene, QGraphicsRectItem, 
    QGraphicsPixmapItem, QDialog
)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtCore import Qt, QUrl, QTime, QThread, pyqtSignal, QTimer, QRectF
from PyQt5.QtGui import QPen, QBrush, QColor, QPainter, QImage, QPixmap

class ResizableRect(QGraphicsRectItem):
    HANDLE_SIZE = 10
    
    def __init__(self, rect, parent=None):
        super().__init__(rect, parent)
        self.setFlags(
            QGraphicsRectItem.ItemIsMovable |
            QGraphicsRectItem.ItemIsSelectable |
            QGraphicsRectItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setBrush(QBrush(Qt.transparent))
        self.setPen(QPen(Qt.red, 2))
        self.resizing = False
        self.crop_updated_callback = None
    
    def set_crop_callback(self, callback):
        self.crop_updated_callback = callback
    
    def hoverMoveEvent(self, event):
        if self._is_in_resize_area(event.pos()):
            self.setCursor(Qt.SizeFDiagCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        super().hoverMoveEvent(event)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._is_in_resize_area(event.pos()):
            self.resizing = True
            self.setCursor(Qt.SizeFDiagCursor)
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        if self.resizing:
            rect = self.rect()
            new_width = max(event.pos().x() - rect.x(), 20)
            new_height = max(event.pos().y() - rect.y(), 20)
            self.setRect(rect.x(), rect.y(), new_width, new_height)
            if self.crop_updated_callback:
                self.crop_updated_callback(self.sceneBoundingRect())
        else:
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        self.resizing = False
        self.setCursor(Qt.ArrowCursor)
        if self.crop_updated_callback:
            self.crop_updated_callback(self.sceneBoundingRect())
        super().mouseReleaseEvent(event)
    
    def itemChange(self, change, value):
        if change == QGraphicsRectItem.ItemPositionHasChanged:
            if self.crop_updated_callback:
                self.crop_updated_callback(self.sceneBoundingRect())
        return super().itemChange(change, value)
    
    def _is_in_resize_area(self, pos):
        rect = self.rect()
        return (
            rect.right() - self.HANDLE_SIZE <= pos.x() <= rect.right() and
            rect.bottom() - self.HANDLE_SIZE <= pos.y() <= rect.bottom()
        )

class CropView(QGraphicsView):
    crop_updated = pyqtSignal(QRectF)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.rect_item = None
        self.video_width = 0
        self.video_height = 0
        self.crop_updated_callback = None
    
    def set_crop_callback(self, callback):
        self.crop_updated_callback = callback
    
    def setVideoFrame(self, frame):
        try:
            if frame is None:
                print("Khung hình rỗng")
                return
                
            self.video_height, self.video_width = frame.shape[:2]
            self.scene.setSceneRect(0, 0, self.video_width, self.video_height)
            
            # Chuyển đổi frame OpenCV sang QImage
            if len(frame.shape) == 3:
                if frame.shape[2] == 3:  # RGB
                    q_img = QImage(frame.data, self.video_width, self.video_height, 
                                  frame.strides[0], QImage.Format_RGB888).rgbSwapped()
                elif frame.shape[2] == 4:  # RGBA
                    q_img = QImage(frame.data, self.video_width, self.video_height, 
                                  frame.strides[0], QImage.Format_RGBA8888)
                else:
                    print(f"Định dạng khung hình không mong muốn: {frame.shape}")
                    return
            else:  # Grayscale
                q_img = QImage(frame.data, self.video_width, self.video_height, 
                              frame.strides[0], QImage.Format_Grayscale8)
            
            pixmap = QPixmap.fromImage(q_img)
            self.scene.clear()
            self.scene.addPixmap(pixmap)
            
            if not self.rect_item:
                rect_width = self.video_width * 0.5
                rect_height = self.video_height * 0.5
                rect_x = (self.video_width - rect_width) / 2
                rect_y = (self.video_height - rect_height) / 2
                self.rect_item = ResizableRect(QRectF(rect_x, rect_y, rect_width, rect_height))
                self.rect_item.set_crop_callback(self.on_crop_updated)
            
            self.scene.addItem(self.rect_item)
            self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
            
        except Exception as e:
            print(f"Lỗi trong setVideoFrame: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def on_crop_updated(self, rect):
        if self.crop_updated_callback:
            self.crop_updated_callback(rect)
        self.crop_updated.emit(rect)
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.scene and self.scene.sceneRect().isValid():
            self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

class FrameCaptureThread(QThread):
    frame_captured = pyqtSignal(np.ndarray)
    
    def __init__(self, video_path):
        super().__init__()
        self.video_path = video_path
        
    def run(self):
        try:
            cap = cv2.VideoCapture(self.video_path)
            if cap.isOpened():
                ret, frame = cap.read()
                if ret:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    self.frame_captured.emit(frame_rgb)
            cap.release()
        except Exception as e:
            print(f"Lỗi khi chụp khung hình: {str(e)}")

class VideoSplitter(QThread):
    progress_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    finished_processing = pyqtSignal(int, str)
    
    def __init__(self, video_path, cut_points, moments, output_folder, crop_params=None):
        super().__init__()
        self.video_path = video_path
        self.cut_points = cut_points
        self.moments = moments
        self.output_folder = output_folder
        self.crop_params = crop_params
        
    def time_to_seconds(self, time_str):
        try:
            parts = time_str.split(':')
            if len(parts) == 3:  # HH:MM:SS
                h, m, s = map(int, parts)
                return h * 3600 + m * 60 + s
            elif len(parts) == 2:  # MM:SS
                m, s = map(int, parts)
                return m * 60 + s
            elif len(parts) == 1:  # SS
                return int(parts[0])
            else:
                return None
        except ValueError:
            return None
    
    def run(self):
        success_count = 0
        total_segments = len(self.cut_points)
        
        if not os.path.exists(self.output_folder):
            os.makedirs(self.output_folder)
            self.status_updated.emit(f"📁 Đã tạo thư mục output: {self.output_folder}")
        
        for i, cut_point in enumerate(self.cut_points):
            try:
                start_time, end_time = cut_point.split(" - ")
                start_seconds = self.time_to_seconds(start_time)
                end_seconds = self.time_to_seconds(end_time)
                
                if start_seconds is None or end_seconds is None:
                    self.status_updated.emit(f"⚠️ Lỗi định dạng thời gian cho đoạn '{self.moments[i]}'")
                    continue
                
                duration = end_seconds - start_seconds
                if duration <= 0:
                    self.status_updated.emit(f"⚠️ Khoảng thời gian không hợp lệ cho đoạn '{self.moments[i]}'")
                    continue
                
                safe_name = self.sanitize_filename(self.moments[i])
                output_file = os.path.join(self.output_folder, f"{safe_name}.mp4")
                
                self.status_updated.emit(f"🔪 Đang cắt đoạn {i+1}/{total_segments}: {safe_name}")
                
                command = [
                    "ffmpeg",
                    "-ss", start_time,
                    "-i", self.video_path,
                    "-t", str(duration),
                    "-c:v", "libx264",
                    "-c:a", "aac",
                    "-y",
                    output_file
                ]
                
                if self.crop_params:
                    crop_filter = f"crop={self.crop_params['width']}:{self.crop_params['height']}:{self.crop_params['x']}:{self.crop_params['y']}"
                    command.extend(["-vf", crop_filter])
                
                process = subprocess.Popen(
                    command, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.STDOUT,
                    universal_newlines=True
                )
                
                # Đọc tiến trình từ FFmpeg
                for line in process.stdout:
                    if "time=" in line:
                        time_str = line.split("time=")[1].split(" ")[0]
                        self.status_updated.emit(f"⏱️ {safe_name}: {time_str}")
                
                process.wait()
                
                if process.returncode == 0:
                    success_count += 1
                    self.status_updated.emit(f"✅ Đã xuất thành công: {safe_name}.mp4")
                else:
                    self.status_updated.emit(f"❌ Lỗi khi cắt đoạn '{safe_name}'")
                
                progress = int((i + 1) / total_segments * 100)
                self.progress_updated.emit(progress)
                
            except Exception as e:
                self.status_updated.emit(f"❌ Lỗi không xác định: {str(e)}")
        
        self.finished_processing.emit(success_count, self.output_folder)
    
    def sanitize_filename(self, name):
        return re.sub(r'[<>:"/\\|?*]', "_", name.strip())

class VideoSplitterApp(QWidget):
    SUPPORTED_FORMATS = "Video Files (*.mp4 *.avi *.mkv *.mov *.wmv *.flv)"
    DEFAULT_OUTPUT_FOLDER = "output_videos"
    
    def __init__(self):
        super().__init__()
        self.video_path = None
        self.cut_points = []
        self.video_duration = 0
        self.processor_thread = None
        self.video_width = 0
        self.video_height = 0
        self.crop_rect = None
        
        self.setFocusPolicy(Qt.StrongFocus)
        
        if not self.check_ffmpeg():
            self.show_dependency_error()
            return
            
        self.init_ui()
        self.setup_media_player()
        
    def check_ffmpeg(self):
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    def show_dependency_error(self):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("Thiếu phụ thuộc")
        msg.setText("Không tìm thấy FFmpeg!")
        msg.setInformativeText("Ứng dụng cần FFmpeg để hoạt động.")
        msg.exec_()
        sys.exit(1)
        
    def init_ui(self):
        self.setWindowTitle("Video Splitter Pro - Cắt Video Thông Minh")
        self.setGeometry(100, 100, 1200, 800)
        self.setup_styles()
        
        main_layout = QVBoxLayout()
        self.tab_widget = QTabWidget()
        
        split_crop_widget = QWidget()
        split_crop_layout = QHBoxLayout()
        
        left_panel = self.create_control_panel()
        right_panel = self.create_video_panel()
        
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        
        split_crop_layout.addWidget(splitter)
        split_crop_widget.setLayout(split_crop_layout)
        
        self.tab_widget.addTab(split_crop_widget, "🎬 Cắt & Crop Video")
        
        self.crop_tab = QWidget()
        crop_layout = QVBoxLayout()
        
        self.crop_view = CropView()
        crop_layout.addWidget(QLabel("Chọn vùng crop (kéo và thay đổi kích thước hình chữ nhật):"))
        crop_layout.addWidget(self.crop_view)
        
        crop_btn_layout = QHBoxLayout()
        self.confirm_crop_btn = QPushButton("Xác nhận vùng crop")
        self.confirm_crop_btn.clicked.connect(self.confirm_crop_selection)
        self.cancel_crop_btn = QPushButton("Hủy bỏ")
        self.cancel_crop_btn.clicked.connect(self.cancel_crop_selection)
        
        crop_btn_layout.addWidget(self.confirm_crop_btn)
        crop_btn_layout.addWidget(self.cancel_crop_btn)
        crop_layout.addLayout(crop_btn_layout)
        
        self.crop_tab.setLayout(crop_layout)
        self.tab_widget.addTab(self.crop_tab, "🔲 Chọn Vùng Crop")
        self.tab_widget.setTabEnabled(1, False)
        
        self.crop_view.crop_updated.connect(self.handle_crop_updated)
        
        main_layout.addWidget(self.tab_widget)
        self.setLayout(main_layout)
        
    def setup_styles(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #f5f5f5;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QPushButton {
                background-color: #4CAF50;
                border: none;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
            QGraphicsView {
                border: 1px solid #cccccc;
                background-color: #000000;
            }
            QProgressBar {
                border: 1px solid #cccccc;
                border-radius: 3px;
                text-align: center;
                background-color: #e0e0e0;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                width: 10px;
            }
        """)
        
    def create_control_panel(self):
        panel = QWidget()
        layout = QVBoxLayout()
        
        file_group = QGroupBox("Chọn Video")
        file_layout = QVBoxLayout()
        
        self.open_button = QPushButton("📁 Chọn File Video")
        self.open_button.clicked.connect(self.load_video)
        
        self.file_info_label = QLabel("Chưa chọn file...")
        self.file_info_label.setWordWrap(True)
        
        file_layout.addWidget(self.open_button)
        file_layout.addWidget(self.file_info_label)
        file_group.setLayout(file_layout)
        
        cut_group = QGroupBox("Điểm Cắt")
        cut_layout = QVBoxLayout()
        
        self.add_cut_button = QPushButton("✂️ Thêm Điểm Cắt")
        self.add_cut_button.clicked.connect(self.add_cut_point)
        self.add_cut_button.setEnabled(False)
        
        self.cut_list = QListWidget()
        self.cut_list.itemDoubleClicked.connect(self.jump_to_cut)
        
        self.clear_cuts_button = QPushButton("🗑️ Xóa Tất Cả Điểm Cắt")
        self.clear_cuts_button.clicked.connect(self.clear_all_cuts)
        
        cut_layout.addWidget(self.add_cut_button)
        cut_layout.addWidget(QLabel("Danh sách đoạn cắt (double-click):"))
        cut_layout.addWidget(self.cut_list)
        cut_layout.addWidget(self.clear_cuts_button)
        cut_group.setLayout(cut_layout)
        
        names_group = QGroupBox("Tên Các Đoạn")
        names_layout = QVBoxLayout()
        
        names_layout.addWidget(QLabel("Nhập tên cho từng đoạn (mỗi dòng một tên):"))
        self.moment_input = QTextEdit()
        self.moment_input.setMaximumHeight(100)
        self.moment_input.setPlaceholderText("Đoạn 1\nĐoạn 2\nĐoạn 3...")
        
        names_layout.addWidget(self.moment_input)
        names_group.setLayout(names_layout)
        
        output_group = QGroupBox("Cài Đặt Xuất")
        output_layout = QVBoxLayout()
        
        self.output_folder_input = QLineEdit(self.DEFAULT_OUTPUT_FOLDER)
        self.browse_output_button = QPushButton("📂 Chọn Thư Mục Xuất")
        self.browse_output_button.clicked.connect(self.browse_output_folder)
        
        self.auto_open_checkbox = QCheckBox("Tự động mở thư mục sau khi hoàn thành")
        self.auto_open_checkbox.setChecked(True)
        
        output_layout.addWidget(QLabel("Thư mục xuất:"))
        output_layout.addWidget(self.output_folder_input)
        output_layout.addWidget(self.browse_output_button)
        output_layout.addWidget(self.auto_open_checkbox)
        output_group.setLayout(output_layout)
        
        crop_group = QGroupBox("Cài Đặt Crop")
        crop_layout = QFormLayout()
        
        self.crop_x_spin = QSpinBox()
        self.crop_x_spin.setRange(0, 9999)
        self.crop_x_spin.setValue(0)
        self.crop_x_spin.setEnabled(False)
        
        self.crop_y_spin = QSpinBox()
        self.crop_y_spin.setRange(0, 9999)
        self.crop_y_spin.setValue(0)
        self.crop_y_spin.setEnabled(False)
        
        self.crop_width_spin = QSpinBox()
        self.crop_width_spin.setRange(1, 9999)
        self.crop_width_spin.setValue(1920)
        self.crop_width_spin.setEnabled(False)
        
        self.crop_height_spin = QSpinBox()
        self.crop_height_spin.setRange(1, 9999)
        self.crop_height_spin.setValue(1080)
        self.crop_height_spin.setEnabled(False)
        
        self.select_crop_btn = QPushButton("Chọn vùng crop...")
        self.select_crop_btn.clicked.connect(self.select_crop_region)
        self.select_crop_btn.setEnabled(False)
        
        crop_layout.addRow("Vị trí X:", self.crop_x_spin)
        crop_layout.addRow("Vị trí Y:", self.crop_y_spin)
        crop_layout.addRow("Chiều rộng:", self.crop_width_spin)
        crop_layout.addRow("Chiều cao:", self.crop_height_spin)
        crop_layout.addRow(self.select_crop_btn)
        
        crop_group.setLayout(crop_layout)
        
        self.cut_button = QPushButton("🎬 BẮT ĐẦU CẮT VIDEO")
        self.cut_button.clicked.connect(self.start_cutting)
        self.cut_button.setEnabled(False)
        self.cut_button.setStyleSheet("QPushButton { background-color: #FF6B35; font-size: 14px; }")
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        
        self.status_label = QLabel("Sẵn sàng...")
        self.status_label.setWordWrap(True)
        
        layout.addWidget(file_group)
        layout.addWidget(cut_group)
        layout.addWidget(names_group)
        layout.addWidget(crop_group)
        layout.addWidget(output_group)
        layout.addWidget(self.cut_button)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)
        layout.addStretch()
        
        panel.setLayout(layout)
        return panel
        
    def create_video_panel(self):
        panel = QWidget()
        layout = QVBoxLayout()
        
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(400)
        
        control_layout = QHBoxLayout()
        
        self.play_button = QPushButton("▶️")
        self.play_button.clicked.connect(self.toggle_play)
        self.play_button.setEnabled(False)
        
        self.stop_button = QPushButton("⏹️")
        self.stop_button.clicked.connect(self.stop_video)
        self.stop_button.setEnabled(False)
        
        self.time_label = QLabel("00:00:00 / 00:00:00")
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet("font-weight: bold;")
        
        control_layout.addWidget(self.play_button)
        control_layout.addWidget(self.stop_button)
        control_layout.addStretch()
        control_layout.addWidget(self.time_label)
        
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.set_position)
        self.slider.setEnabled(False)
        
        layout.addWidget(QLabel("Video Preview:"))
        layout.addWidget(self.video_widget)
        layout.addLayout(control_layout)
        layout.addWidget(self.slider)
        
        panel.setLayout(layout)
        return panel
        
    def setup_media_player(self):
        self.media_player = QMediaPlayer(None, QMediaPlayer.VideoSurface)
        self.media_player.setVideoOutput(self.video_widget)
        
        self.media_player.stateChanged.connect(self.media_state_changed)
        self.media_player.positionChanged.connect(self.position_changed)
        self.media_player.durationChanged.connect(self.duration_changed)
        self.media_player.error.connect(self.handle_media_error)
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_time_display)
        self.timer.start(100)
        
    def load_video(self):
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Chọn Video", "", self.SUPPORTED_FORMATS
            )
            
            if not file_path:
                return
                
            if not os.path.exists(file_path):
                self.show_error("File không tồn tại!")
                return
                
            if os.path.getsize(file_path) == 0:
                self.show_error("File rỗng!")
                return
            
            self.video_path = file_path
            self.media_player.setMedia(QMediaContent(QUrl.fromLocalFile(file_path)))
            
            file_name = os.path.basename(file_path)
            file_size = self.format_file_size(os.path.getsize(file_path))
            self.file_info_label.setText(f"📁 {file_name}\n💾 {file_size}")
            
            self.select_crop_btn.setEnabled(True)
            
            self.play_button.setEnabled(True)
            self.stop_button.setEnabled(True)
            self.slider.setEnabled(True)
            self.add_cut_button.setEnabled(True)
            
            self.cut_points.clear()
            self.cut_list.clear()
            self.update_cut_list()
            self.update_cut_button_state()
            
            self.status_label.setText("✅ Video đã được tải thành công! Nhấn vào cửa sổ để dùng phím mũi tên.")
            
        except Exception as e:
            self.show_error(f"Không thể tải video: {str(e)}")
    
    def select_crop_region(self):
        if not self.video_path:
            return
            
        self.tab_widget.setCurrentIndex(1)
        self.tab_widget.setTabEnabled(1, True)
        
        self.frame_capture_thread = FrameCaptureThread(self.video_path)
        self.frame_capture_thread.frame_captured.connect(self.show_frame_for_crop)
        self.frame_capture_thread.start()
    
    def show_frame_for_crop(self, frame):
        self.crop_view.setVideoFrame(frame)
        self.status_label.setText("Chọn vùng crop bằng cách kéo và thay đổi kích thước hình chữ nhật đỏ")
    
    def confirm_crop_selection(self):
        if self.crop_view.rect_item:
            scene_rect = self.crop_view.rect_item.sceneBoundingRect()
            self.crop_rect = scene_rect
            
            self.crop_x_spin.setValue(int(scene_rect.x()))
            self.crop_y_spin.setValue(int(scene_rect.y()))
            self.crop_width_spin.setValue(int(scene_rect.width()))
            self.crop_height_spin.setValue(int(scene_rect.height()))
            
            self.crop_x_spin.setEnabled(True)
            self.crop_y_spin.setEnabled(True)
            self.crop_width_spin.setEnabled(True)
            self.crop_height_spin.setEnabled(True)
            
            self.tab_widget.setCurrentIndex(0)
            self.status_label.setText("✅ Đã chọn vùng crop. Bạn có thể chỉnh sửa thủ công nếu cần.")
    
    def cancel_crop_selection(self):
        self.crop_rect = None
        self.tab_widget.setCurrentIndex(0)
        self.status_label.setText("Hủy bỏ chọn vùng crop")
    
    def handle_crop_updated(self, rect):
        self.crop_x_spin.setValue(int(rect.x()))
        self.crop_y_spin.setValue(int(rect.y()))
        self.crop_width_spin.setValue(int(rect.width()))
        self.crop_height_spin.setValue(int(rect.height()))
        self.crop_rect = rect
        self.status_label.setText("✅ Vùng crop đã được cập nhật.")
    
    def keyPressEvent(self, event):
        if not self.video_path or self.video_duration == 0:
            return
            
        if event.key() == Qt.Key_Left:
            new_position = max(0, self.media_player.position() - 5000)
            self.media_player.setPosition(new_position)
        elif event.key() == Qt.Key_Right:
            new_position = min(self.video_duration, self.media_player.position() + 5000)
            self.media_player.setPosition(new_position)
        elif event.key() == Qt.Key_Space:
            self.toggle_play()
        else:
            super().keyPressEvent(event)
    
    def format_file_size(self, size_bytes):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"
        
    def toggle_play(self):
        if self.media_player.state() == QMediaPlayer.PlayingState:
            self.media_player.pause()
        else:
            self.media_player.play()
            
    def stop_video(self):
        self.media_player.stop()
        
    def set_position(self, position):
        self.media_player.setPosition(position)
        
    def add_cut_point(self):
        if not self.video_path:
            return
            
        dialog = QDialog(self)
        dialog.setWindowTitle("Thêm Điểm Cắt")
        layout = QVBoxLayout()
        
        form_layout = QFormLayout()
        start_time_input = QLineEdit()
        start_time_input.setPlaceholderText("HH:MM:SS")
        end_time_input = QLineEdit()
        end_time_input.setPlaceholderText("HH:MM:SS")
        
        form_layout.addRow("Thời gian bắt đầu:", start_time_input)
        form_layout.addRow("Thời gian kết thúc:", end_time_input)
        
        button_box = QHBoxLayout()
        ok_button = QPushButton("OK")
        cancel_button = QPushButton("Hủy")
        
        button_box.addWidget(ok_button)
        button_box.addWidget(cancel_button)
        
        layout.addLayout(form_layout)
        layout.addLayout(button_box)
        
        dialog.setLayout(layout)
        
        def validate_and_add():
            start_time = start_time_input.text().strip()
            end_time = end_time_input.text().strip()
            
            time_pattern = r"^\d{2}:\d{2}:\d{2}$"
            if not (re.match(time_pattern, start_time) and re.match(time_pattern, end_time)):
                QMessageBox.warning(dialog, "Lỗi", "Định dạng thời gian phải là HH:MM:SS")
                return
                
            cut_point = f"{start_time} - {end_time}"
            if cut_point in self.cut_points:
                QMessageBox.warning(dialog, "Lỗi", "Điểm cắt này đã tồn tại!")
                return
                
            self.cut_points.append(cut_point)
            self.cut_points.sort(key=lambda x: self.time_to_seconds(x.split(" - ")[0]))
            self.update_cut_list()
            self.update_cut_button_state()
            self.status_label.setText(f"✅ Đã thêm điểm cắt: {cut_point}")
            dialog.accept()
        
        ok_button.clicked.connect(validate_and_add)
        cancel_button.clicked.connect(dialog.reject)
        
        dialog.exec_()
        
    def time_to_seconds(self, time_str):
        try:
            h, m, s = map(int, time_str.split(":"))
            return h * 3600 + m * 60 + s
        except ValueError:
            return None
    
    def update_cut_list(self):
        self.cut_list.clear()
        for i, cut_point in enumerate(self.cut_points):
            item = QListWidgetItem(f"{i+1:02d}. {cut_point}")
            item.setData(Qt.UserRole, cut_point)
            self.cut_list.addItem(item)
            
    def jump_to_cut(self, item):
        cut_point = item.data(Qt.UserRole)
        start_time = cut_point.split(" - ")[0]
        start_seconds = self.time_to_seconds(start_time)
        if start_seconds is not None:
            self.media_player.setPosition(start_seconds * 1000)
        
    def clear_all_cuts(self):
        reply = QMessageBox.question(
            self, "Xác nhận", "Bạn có chắc muốn xóa tất cả điểm cắt?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.cut_points.clear()
            self.cut_list.clear()
            self.update_cut_list()
            self.update_cut_button_state()
            self.status_label.setText("🗑️ Đã xóa tất cả điểm cắt")
            
    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục xuất")
        if folder:
            self.output_folder_input.setText(folder)
            
    def update_cut_button_state(self):
        has_video = self.video_path is not None
        has_enough_cuts = len(self.cut_points) >= 1
        self.cut_button.setEnabled(has_video and has_enough_cuts)
        
    def start_cutting(self):
        if not self.validate_inputs():
            return
            
        moments = self.get_segment_names()
        output_folder = self.output_folder_input.text().strip()
        
        crop_params = None
        if self.crop_rect:
            crop_params = {
                'x': self.crop_x_spin.value(),
                'y': self.crop_y_spin.value(),
                'width': self.crop_width_spin.value(),
                'height': self.crop_height_spin.value()
            }
            
            if not self.validate_crop_params(crop_params):
                return
        
        try:
            os.makedirs(output_folder, exist_ok=True)
        except Exception as e:
            self.show_error(f"Không thể tạo thư mục xuất: {str(e)}")
            return
            
        self.set_ui_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        self.processor_thread = VideoSplitter(
            self.video_path, self.cut_points, moments, output_folder, crop_params
        )
        self.processor_thread.progress_updated.connect(self.progress_bar.setValue)
        self.processor_thread.status_updated.connect(self.status_label.setText)
        self.processor_thread.finished_processing.connect(self.on_processing_finished)
        self.processor_thread.start()
    
    def validate_crop_params(self, crop_params):
        x, y, width, height = crop_params['x'], crop_params['y'], crop_params['width'], crop_params['height']
        
        # Lấy kích thước video thực tế
        cap = cv2.VideoCapture(self.video_path)
        if cap.isOpened():
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
        
        if x + width > self.video_width:
            self.show_error(f"Vùng crop vượt quá chiều rộng video!\nX + Width = {x + width} > {self.video_width}")
            #return False
            
        if y + height > self.video_height:
            self.show_error(f"Vùng crop vượt quá chiều cao video!\nY + Height = {y + height} > {self.video_height}")
           # return False
            
        if width < 1 or height < 1:
            self.show_error("Chiều rộng và chiều cao crop phải lớn hơn 0!")
            return False
            
        return True
        
    def validate_inputs(self):
        if not self.video_path:
            self.show_error("Vui lòng chọn video!")
            return False
            
        if len(self.cut_points) < 1:
            self.show_error("Cần ít nhất 1 điểm cắt!")
            return False
            
        moments = self.get_segment_names()
        expected_segments = len(self.cut_points)
        
        if len(moments) != expected_segments:
            self.show_error(
                f"Cần {expected_segments} tên đoạn nhưng chỉ có {len(moments)} tên!\n"
                f"Vui lòng nhập đủ tên cho từng đoạn."
            )
            return False
            
        if not all(name.strip() for name in moments):
            self.show_error("Tất cả tên đoạn phải khác rỗng!")
            return False
            
        for cut_point in self.cut_points:
            try:
                start_time, end_time = cut_point.split(" - ")
                start_seconds = self.time_to_seconds(start_time)
                end_seconds = self.time_to_seconds(end_time)
                if start_seconds is None or end_seconds is None:
                    self.show_error(f"Định dạng thời gian không hợp lệ: {cut_point}")
                    return False
                if end_seconds <= start_seconds:
                    self.show_error(f"Khoảng thời gian không hợp lệ: {cut_point}")
                    return False
            except ValueError:
                self.show_error(f"Định dạng điểm cắt không hợp lệ: {cut_point}")
                return False
                
        return True
        
    def get_segment_names(self):
        text = self.moment_input.toPlainText().strip()
        if not text:
            return []
        return [line.strip() for line in text.splitlines() if line.strip()]
        
    def set_ui_enabled(self, enabled):
        self.open_button.setEnabled(enabled)
        self.add_cut_button.setEnabled(enabled and self.video_path)
        self.cut_button.setEnabled(enabled and len(self.cut_points) >= 1)
        self.clear_cuts_button.setEnabled(enabled)
        self.select_crop_btn.setEnabled(enabled and self.video_path)
        self.browse_output_button.setEnabled(enabled)
        self.auto_open_checkbox.setEnabled(enabled)
        
    def on_processing_finished(self, success_count, output_folder):
        self.set_ui_enabled(True)
        self.progress_bar.setVisible(False)
        
        total_segments = len(self.cut_points)
        
        if success_count == total_segments:
            msg_text = f"🎉 Hoàn thành! Đã cắt thành công {success_count}/{total_segments} đoạn."
            self.status_label.setText(msg_text)
            
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Information)
            msg.setWindowTitle("Hoàn thành")
            msg.setText(msg_text)
            msg.setInformativeText(f"Các file đã được lưu trong:\n{output_folder}")
            
            if self.auto_open_checkbox.isChecked():
                msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Open)
                msg.setDefaultButton(QMessageBox.Open)
            else:
                msg.setStandardButtons(QMessageBox.Ok)
                
            result = msg.exec_()
            
            if result == QMessageBox.Open:
                self.open_output_folder(output_folder)
                
        else:
            self.show_error(f"Chỉ cắt thành công {success_count}/{total_segments} đoạn!")
            
    def open_output_folder(self, folder_path):
        try:
            if sys.platform == "win32":
                os.startfile(folder_path)
            elif sys.platform == "darwin":
                subprocess.run(["open", folder_path])
            else:
                subprocess.run(["xdg-open", folder_path])
        except Exception as e:
            self.show_error(f"Không thể mở thư mục: {str(e)}")
            
    def media_state_changed(self, state):
        if state == QMediaPlayer.PlayingState:
            self.play_button.setText("⏸️")
        else:
            self.play_button.setText("▶️")
            
    def position_changed(self, position):
        self.slider.setValue(position)
        
    def duration_changed(self, duration):
        self.slider.setRange(0, duration)
        self.video_duration = duration
        self.update_time_display()
        
    def update_time_display(self):
        if self.video_duration > 0:
            current_time = self.format_time(self.media_player.position())
            total_time = self.format_time(self.video_duration)
            self.time_label.setText(f"{current_time} / {total_time}")
            
    def format_time(self, ms):
        return QTime(0, 0, 0).addMSecs(ms).toString("HH:mm:ss")
        
    def handle_media_error(self):
        error = self.media_player.errorString()
        self.show_error(f"Lỗi phát video: {error}")
        
    def show_error(self, message):
        QMessageBox.critical(self, "Lỗi", message)
        self.status_label.setText(f"❌ {message}")
        
    def closeEvent(self, event):
        if hasattr(self, 'processor_thread') and self.processor_thread and self.processor_thread.isRunning():
            reply = QMessageBox.question(
                self, "Xác nhận thoát",
                "Đang xử lý video. Bạn có chắc muốn thoát?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.processor_thread.terminate()
                self.processor_thread.wait()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Video Splitter Pro")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("VideoTools")
    
    window = VideoSplitterApp()
    window.show()
    
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()