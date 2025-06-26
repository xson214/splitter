import sys
import os
import subprocess
import re
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QLabel,
    QTextEdit, QFileDialog, QSlider, QMessageBox, QHBoxLayout, 
    QListWidget, QProgressBar, QListWidgetItem, QSplitter,
    QGroupBox, QLineEdit, QCheckBox, QSpinBox, QTabWidget,
    QFormLayout, QGraphicsView, QGraphicsScene, QGraphicsRectItem
)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtCore import Qt, QUrl, QTime, QThread, pyqtSignal, QTimer, QRectF
from PyQt5.QtGui import QPen, QBrush, QColor, QPainter

class ResizableRect(QGraphicsRectItem):
    """A resizable rectangle for selecting crop region"""
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
        self.crop_updated = pyqtSignal(QRectF)
    
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
            self.crop_updated.emit(self.sceneBoundingRect())
        else:
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        self.resizing = False
        self.setCursor(Qt.ArrowCursor)
        self.crop_updated.emit(self.sceneBoundingRect())
        super().mouseReleaseEvent(event)
    
    def _is_in_resize_area(self, pos):
        rect = self.rect()
        return (
            rect.right() - self.HANDLE_SIZE <= pos.x() <= rect.right() and
            rect.bottom() - self.HANDLE_SIZE <= pos.y() <= rect.bottom()
        )

class CropView(QVideoWidget):
    """Custom video widget with a resizable crop rectangle"""
    crop_updated = pyqtSignal(QRectF)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene, self)
        self.view.setStyleSheet("border: 0px")
        self.view.setRenderHint(QPainter.Antialiasing)
        self.rect_item = None
        self.video_width = 0
        self.video_height = 0
    
    def setVideoSize(self, width, height):
        """Set video dimensions and initialize crop rectangle"""
        self.video_width = width
        self.video_height = height
        if width > 0 and height > 0:
            self.scene.setSceneRect(0, 0, width, height)
            self.view.setSceneRect(0, 0, width, height)
            # Initialize crop rectangle (default to 50% of video size, centered)
            rect_width = width * 0.5
            rect_height = height * 0.5
            rect_x = (width - rect_width) / 2
            rect_y = (height - rect_height) / 2
            self.rect_item = ResizableRect(QRectF(rect_x, rect_y, rect_width, rect_height))
            self.rect_item.crop_updated.connect(self.on_crop_updated)
            self.scene.addItem(self.rect_item)
    
    def on_crop_updated(self, rect):
        """Handle crop rectangle updates"""
        self.crop_updated.emit(rect)
    
    def resizeEvent(self, event):
        """Adjust view size to match widget size"""
        super().resizeEvent(event)
        self.view.setGeometry(0, 0, self.width(), self.height())
    
    def setCropEnabled(self, enabled):
        """Show or hide crop rectangle"""
        if self.rect_item:
            self.rect_item.setVisible(enabled)
            if not enabled:
                self.rect_item.setRect(QRectF(0, 0, self.video_width, self.video_height))

class VideoProcessor(QThread):
    """Separate thread for video processing to prevent UI freezing"""
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
        
    def run(self):
        """Process video cutting in background thread"""
        success_count = 0
        total_segments = len(self.cut_points) - 1
        
        for i in range(total_segments):
            try:
                start_ms = self.cut_points[i]
                end_ms = self.cut_points[i + 1]
                duration = (end_ms - start_ms) / 1000
                
                start_time = QTime(0, 0, 0).addMSecs(start_ms).toString("HH:mm:ss")
                safe_name = self.sanitize_filename(self.moments[i])
                output_file = os.path.join(self.output_folder, f"{safe_name}.mp4")
                
                self.status_updated.emit(f"Đang cắt đoạn {i+1}/{total_segments}: {safe_name}")
                
                command = ["ffmpeg", "-ss", start_time, "-i", self.video_path, "-t", str(duration)]
                
                if self.crop_params:
                    crop_filter = f"crop={self.crop_params['width']}:{self.crop_params['height']}:{self.crop_params['x']}:{self.crop_params['y']}"
                    command.extend(["-vf", crop_filter, "-c:a", "copy"])
                else:
                    command.extend(["-c", "copy"])
                
                command.extend(["-avoid_negative_ts", "make_zero", "-y", output_file])
                
                subprocess.run(command, check=True, capture_output=True, text=True, timeout=300)
                
                success_count += 1
                progress = int((i + 1) / total_segments * 100)
                self.progress_updated.emit(progress)
                
            except subprocess.CalledProcessError as e:
                self.status_updated.emit(f"Lỗi ffmpeg khi cắt đoạn '{self.moments[i]}': {e.stderr}")
            except subprocess.TimeoutExpired:
                self.status_updated.emit(f"Timeout khi cắt đoạn '{self.moments[i]}'")
            except Exception as e:
                self.status_updated.emit(f"Lỗi không xác định: {str(e)}")
        
        self.finished_processing.emit(success_count, self.output_folder)
    
    def sanitize_filename(self, name):
        """Remove invalid characters from filename"""
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
        msg.setInformativeText(
            "Ứng dụng cần FFmpeg để hoạt động.\n\n"
        )
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
        
        self.add_cut_button = QPushButton("✂️ Thêm Điểm Cắt Tại Vị Trí Hiện Tại")
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
        
        crop_group = QGroupBox("Cài Đặt Crop (Tùy chọn)")
        crop_layout = QFormLayout()
        
        self.enable_crop_checkbox = QCheckBox("Bật crop video")
        self.enable_crop_checkbox.stateChanged.connect(self.toggle_crop_controls)
        
        self.crop_controls_widget = QWidget()
        self.crop_controls_layout = QFormLayout()
        
        self.crop_x_spin = QSpinBox()
        self.crop_x_spin.setRange(0, 9999)
        self.crop_x_spin.setValue(0)
        
        self.crop_y_spin = QSpinBox()
        self.crop_y_spin.setRange(0, 9999)
        self.crop_y_spin.setValue(0)
        
        self.crop_width_spin = QSpinBox()
        self.crop_width_spin.setRange(1, 9999)
        self.crop_width_spin.setValue(1920)
        
        self.crop_height_spin = QSpinBox()
        self.crop_height_spin.setRange(1, 9999)
        self.crop_height_spin.setValue(1080)
        
        preset_layout = QHBoxLayout()
        self.preset_16_9_button = QPushButton("16:9")
        self.preset_4_3_button = QPushButton("4:3")
        self.preset_1_1_button = QPushButton("1:1")
        self.preset_center_button = QPushButton("Giữa màn hình")
        
        self.preset_16_9_button.clicked.connect(lambda: self.apply_crop_preset("16:9"))
        self.preset_4_3_button.clicked.connect(lambda: self.apply_crop_preset("4:3"))
        self.preset_1_1_button.clicked.connect(lambda: self.apply_crop_preset("1:1"))
        self.preset_center_button.clicked.connect(lambda: self.apply_crop_preset("center"))
        
        preset_layout.addWidget(self.preset_16_9_button)
        preset_layout.addWidget(self.preset_4_3_button)
        preset_layout.addWidget(self.preset_1_1_button)
        preset_layout.addWidget(self.preset_center_button)
        
        self.video_info_label = QLabel("Chưa có thông tin video")
        
        self.crop_controls_layout.addRow("Vị trí X:", self.crop_x_spin)
        self.crop_controls_layout.addRow("Vị trí Y:", self.crop_y_spin)
        self.crop_controls_layout.addRow("Chiều rộng:", self.crop_width_spin)
        self.crop_controls_layout.addRow("Chiều cao:", self.crop_height_spin)
        self.crop_controls_layout.addRow("Presets:", preset_layout)
        self.crop_controls_widget.setLayout(self.crop_controls_layout)
        self.crop_controls_widget.setVisible(False)
        
        crop_layout.addRow(self.enable_crop_checkbox)
        crop_layout.addRow(self.crop_controls_widget)
        crop_layout.addRow("Thông tin video:", self.video_info_label)
        
        crop_group.setLayout(crop_layout)
        
        self.cut_button = QPushButton("🎬 BẮT ĐẦU CẮT VIDEO")
        self.cut_button.clicked.connect(self.start_cutting)
        self.cut_button.setEnabled(False)
        self.cut_button.setStyleSheet("QPushButton { background-color: #FF6B35; }")
        
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
        
        self.video_widget = CropView()
        self.video_widget.setMinimumHeight(400)
        self.video_widget.crop_updated.connect(self.update_crop_from_video)
        
        control_layout = QHBoxLayout()
        
        self.play_button = QPushButton("▶️")
        self.play_button.clicked.connect(self.toggle_play)
        self.play_button.setEnabled(False)
        
        self.stop_button = QPushButton("⏹️")
        self.stop_button.clicked.connect(self.stop_video)
        self.stop_button.setEnabled(False)
        
        self.time_label = QLabel("00:00:00 / 00:00:00")
        self.time_label.setAlignment(Qt.AlignCenter)
        
        control_layout.addWidget(self.play_button)
        control_layout.addWidget(self.stop_button)
        control_layout.addStretch()
        control_layout.addWidget(self.time_label)
        
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.set_position)
        self.slider.setEnabled(False)
        
        layout.addWidget(QLabel("Video Preview (Kéo thả để chọn vùng crop khi bật crop):"))
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
            
            self.get_video_info(file_path)
            
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
    
    def get_video_info(self, file_path):
        try:
            command = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_streams", "-select_streams", "v:0", file_path
            ]
            
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            import json
            data = json.loads(result.stdout)
            
            if data.get("streams"):
                stream = data["streams"][0]
                self.video_width = int(stream.get("width", 0))
                self.video_height = int(stream.get("height", 0))
                
                self.video_info_label.setText(
                    f"📺 {self.video_width} x {self.video_height} pixels"
                )
                
                self.crop_x_spin.setMaximum(self.video_width - 1)
                self.crop_y_spin.setMaximum(self.video_height - 1)
                self.crop_width_spin.setMaximum(self.video_width)
                self.crop_height_spin.setMaximum(self.video_height)
                
                self.crop_width_spin.setValue(self.video_width)
                self.crop_height_spin.setValue(self.video_height)
                
                self.video_widget.setVideoSize(self.video_width, self.video_height)
                
                for btn in [self.preset_16_9_button, self.preset_4_3_button, 
                           self.preset_1_1_button, self.preset_center_button]:
                    btn.setEnabled(self.enable_crop_checkbox.isChecked())
                    
        except Exception as e:
            self.video_info_label.setText("❌ Không thể lấy thông tin video")
            print(f"Error getting video info: {e}")
    
    def keyPressEvent(self, event):
        if not self.video_path or self.video_duration == 0:
            return
            
        if event.key() == Qt.Key_Left:
            new_position = max(0, self.media_player.position() - 1000)
            self.media_player.setPosition(new_position)
        elif event.key() == Qt.Key_Right:
            new_position = min(self.video_duration, self.media_player.position() + 1000)
            self.media_player.setPosition(new_position)
        else:
            super().keyPressEvent(event)
    
    def toggle_crop_controls(self, state):
        enabled = state == Qt.Checked
        self.crop_controls_widget.setVisible(enabled)
        
        self.crop_x_spin.setEnabled(enabled)
        self.crop_y_spin.setEnabled(enabled)
        self.crop_width_spin.setEnabled(enabled)
        self.crop_height_spin.setEnabled(enabled)
        
        for btn in [self.preset_16_9_button, self.preset_4_3_button, 
                   self.preset_1_1_button, self.preset_center_button]:
            btn.setEnabled(enabled and self.video_width > 0)
        
        self.video_widget.setCropEnabled(enabled)
    
    def update_crop_from_video(self, crop_rect):
        if not self.enable_crop_checkbox.isChecked():
            return
            
        x = int(crop_rect.x())
        y = int(crop_rect.y())
        width = int(crop_rect.width())
        height = int(crop_rect.height())
        
        x = max(0, min(x, self.video_width - 1))
        y = max(0, min(y, self.video_height - 1))
        width = max(1, min(width, self.video_width - x))
        height = max(1, min(height, self.video_height - y))
        
        self.crop_x_spin.setValue(x)
        self.crop_y_spin.setValue(y)
        self.crop_width_spin.setValue(width)
        self.crop_height_spin.setValue(height)
    
    def apply_crop_preset(self, preset_type):
        if not self.video_width or not self.video_height:
            return
            
        if preset_type == "16:9":
            target_ratio = 16/9
            current_ratio = self.video_width / self.video_height
            if current_ratio > target_ratio:
                new_width = int(self.video_height * target_ratio)
                new_height = self.video_height
                x = (self.video_width - new_width) // 2
                y = 0
            else:
                new_width = self.video_width
                new_height = int(self.video_width / target_ratio)
                x = 0
                y = (self.video_height - new_height) // 2
        elif preset_type == "4:3":
            target_ratio = 4/3
            current_ratio = self.video_width / self.video_height
            if current_ratio > target_ratio:
                new_width = int(self.video_height * target_ratio)
                new_height = self.video_height
                x = (self.video_width - new_width) // 2
                y = 0
            else:
                new_width = self.video_width
                new_height = int(self.video_width / target_ratio)
                x = 0
                y = (self.video_height - new_height) // 2
        elif preset_type == "1:1":
            size = min(self.video_width, self.video_height)
            new_width = new_height = size
            x = (self.video_width - size) // 2
            y = (self.video_height - size) // 2
        elif preset_type == "center":
            new_width = int(self.video_width * 0.8)
            new_height = int(self.video_height * 0.8)
            x = (self.video_width - new_width) // 2
            y = (self.video_height - new_height) // 2
        
        self.crop_x_spin.setValue(x)
        self.crop_y_spin.setValue(y)
        self.crop_width_spin.setValue(new_width)
        self.crop_height_spin.setValue(new_height)
        
        if self.enable_crop_checkbox.isChecked() and self.video_widget.rect_item:
            self.video_widget.rect_item.setRect(QRectF(x, y, new_width, new_height))
    
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
            
        position_ms = self.media_player.position()
        
        if position_ms in self.cut_points:
            self.status_label.setText("⚠️ Điểm cắt này đã tồn tại!")
            return
            
        self.cut_points.append(position_ms)
        self.cut_points.sort()
        
        self.update_cut_list()
        self.update_cut_button_state()
        
        time_str = self.format_time(position_ms)
        self.status_label.setText(f"✅ Đã thêm điểm cắt tại {time_str}")
        
    def update_cut_list(self):
        self.cut_list.clear()
        for i in range(len(self.cut_points) - 1):
            start_ms = self.cut_points[i]
            end_ms = self.cut_points[i + 1]
            start_time = self.format_time(start_ms)
            end_time = self.format_time(end_ms)
            item = QListWidgetItem(f"{i+1:02d}. {start_time} - {end_time}")
            item.setData(Qt.UserRole, start_ms)
            self.cut_list.addItem(item)
            
    def jump_to_cut(self, item):
        position_ms = item.data(Qt.UserRole)
        self.media_player.setPosition(position_ms)
        
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
        has_enough_cuts = len(self.cut_points) >= 2
        self.cut_button.setEnabled(has_video and has_enough_cuts)
        
    def start_cutting(self):
        if not self.validate_inputs():
            return
            
        moments = self.get_segment_names()
        output_folder = self.output_folder_input.text().strip()
        
        crop_params = None
        if self.enable_crop_checkbox.isChecked():
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
        
        self.processor_thread = VideoProcessor(
            self.video_path, self.cut_points, moments, output_folder, crop_params
        )
        self.processor_thread.progress_updated.connect(self.progress_bar.setValue)
        self.processor_thread.status_updated.connect(self.status_label.setText)
        self.processor_thread.finished_processing.connect(self.on_processing_finished)
        self.processor_thread.start()
    
    def validate_crop_params(self, crop_params):
        x, y, width, height = crop_params['x'], crop_params['y'], crop_params['width'], crop_params['height']
        
        if x + width > self.video_width:
            self.show_error(f"Vùng crop vượt quá chiều rộng video!\nX + Width = {x + width} > {self.video_width}")
            return False
            
        if y + height > self.video_height:
            self.show_error(f"Vùng crop vượt quá chiều cao video!\nY + Height = {y + height} > {self.video_height}")
            return False
            
        if width < 1 or height < 1:
            self.show_error("Chiều rộng và chiều cao crop phải lớn hơn 0!")
            return False
            
        return True
        
    def validate_inputs(self):
        if not self.video_path:
            self.show_error("Vui lòng chọn video!")
            return False
            
        if len(self.cut_points) < 2:
            self.show_error("Cần ít nhất 2 điểm cắt!")
            return False
            
        moments = self.get_segment_names()
        expected_segments = len(self.cut_points) - 1
        
        if len(moments) != expected_segments:
            self.show_error(
                f"Cần {expected_segments} tên đoạn nhưng chỉ có {len(moments)} tên!\n"
                f"Vui lòng nhập đủ tên cho từng đoạn."
            )
            return False
            
        if not all(name.strip() for name in moments):
            self.show_error("Tất cả tên đoạn phải khác rỗng!")
            return False
            
        if self.enable_crop_checkbox.isChecked():
            if self.video_width == 0 or self.video_height == 0:
                self.show_error("Không thể crop: Chưa có thông tin kích thước video!")
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
        self.cut_button.setEnabled(enabled and len(self.cut_points) >= 2)
        self.clear_cuts_button.setEnabled(enabled)
        
    def on_processing_finished(self, success_count, output_folder):
        self.set_ui_enabled(True)
        self.progress_bar.setVisible(False)
        
        total_segments = len(self.cut_points) - 1
        
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
        if self.processor_thread and self.processor_thread.isRunning():
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
    app.setApplicationName("Video Splitter")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("VideoTools")
    
    window = VideoSplitterApp()
    window.show()
    
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()