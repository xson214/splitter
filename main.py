import sys
from PyQt5.QtWidgets import (
    QApplication, QGraphicsView, QGraphicsScene,
    QGraphicsRectItem, QGraphicsItem, QMainWindow, QFileDialog
)
from PyQt5.QtGui import QPen, QBrush, QPainter, QPixmap, QImage
from PyQt5.QtCore import Qt, QRectF
import cv2
import numpy as np


class ResizableRect(QGraphicsRectItem):
    HANDLE_SIZE = 10

    def __init__(self, rect):
        super().__init__(rect)
        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setBrush(QBrush(Qt.transparent))
        self.setPen(QPen(Qt.red, 2))
        self.resizing = False

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
            new_width = max(event.pos().x(), 20)
            new_height = max(event.pos().y(), 20)
            self.setRect(rect.x(), rect.y(), new_width, new_height)

            scene_rect = self.sceneBoundingRect()
            print(f"Resized to: x={int(scene_rect.x())}, y={int(scene_rect.y())}, w={int(scene_rect.width())}, h={int(scene_rect.height())}")
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.resizing = False
        self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def _is_in_resize_area(self, pos):
        rect = self.rect()
        return (
            rect.right() - self.HANDLE_SIZE <= pos.x() <= rect.right() and
            rect.bottom() - self.HANDLE_SIZE <= pos.y() <= rect.bottom()
        )


class CropView(QGraphicsView):
    def __init__(self, image_np):
        super().__init__()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        # Hiển thị ảnh từ numpy array (OpenCV)
        h, w, ch = image_np.shape
        bytes_per_line = ch * w
        image_qt = QImage(image_np.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(image_qt.rgbSwapped())  # BGR -> RGB
        self.scene.addPixmap(pixmap)

        # Tạo hình chữ nhật để crop
        self.rect_item = ResizableRect(QRectF(50, 50, 200, 150))
        self.scene.addItem(self.rect_item)

        self.setRenderHint(QPainter.Antialiasing)
        self.setSceneRect(0, 0, w, h)


class MainWindow(QMainWindow):
    def __init__(self, image_np):
        super().__init__()
        self.setWindowTitle("Crop Region Selector")
        self.view = CropView(image_np)
        self.setCentralWidget(self.view)
        self.resize(800, 600)


def main():
    app = QApplication(sys.argv)

    # Load một frame từ video hoặc ảnh bất kỳ
    filename, _ = QFileDialog.getOpenFileName(None, "Chọn ảnh hoặc video", "", "Video/Images (*.mp4 *.jpg *.png)")
    if not filename:
        print("Không chọn file.")
        return

    if filename.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
        cap = cv2.VideoCapture(filename)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            print("Không thể đọc video.")
            return
    else:
        frame = cv2.imread(filename)
        if frame is None:
            print("Không thể đọc ảnh.")
            return

    window = MainWindow(frame)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
